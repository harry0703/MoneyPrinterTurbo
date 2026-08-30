package services

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/harry0703/moneyprinterturbo/go/internal/config"
	"github.com/harry0703/moneyprinterturbo/go/internal/models"
	"github.com/harry0703/moneyprinterturbo/go/internal/utils"
)

const (
	defaultLoomLoomBaseURL      = "https://loomloom.shengsuanyun.com/loom/v1"
	defaultLoomLoomVideoListing = "019fd60d-5c26-78f7-bba0-5584f9ee7337"
	maxLoomLoomVideoScenes      = 5
)

// FetchLoomLoomVideos 对应 Python get_video_materials 的 loomloom 分支。
// 必须已有确认报价；付费 run 一旦创建就先落盘 run_id，再轮询下载。
func FetchLoomLoomVideos(taskID string, params models.VideoParams, terms []string, req *models.LoomLoomVideoRequest) ([]string, error) {
	if req == nil {
		return nil, fmt.Errorf("LoomLoom video generation requires a confirmed quote")
	}
	if strings.TrimSpace(req.ListingVersionID) == "" {
		return nil, fmt.Errorf("listing_version_id from the quote is required")
	}
	if strings.TrimSpace(req.ClientRequestID) == "" {
		return nil, fmt.Errorf("client_request_id is required")
	}
	token := strings.TrimSpace(req.APIToken)
	if token == "" {
		token = resolveLoomLoomToken()
	}
	if token == "" {
		return nil, fmt.Errorf("loomloom_api_token is required")
	}
	base := strings.TrimRight(strings.TrimSpace(req.BaseURL), "/")
	if base == "" {
		base = strings.TrimRight(config.Get().AppString("loomloom_base_url", defaultLoomLoomBaseURL), "/")
	}
	listingID := config.Get().AppString("loomloom_market_listing_id", defaultLoomLoomVideoListing)
	client := &loomLoomClient{base: base, token: token, listingID: listingID}

	runID := strings.TrimSpace(req.RunID)
	if runID == "" {
		rows := buildLoomLoomScenes(params, terms)
		slog.Info("generating LoomLoom video materials", "scenes", len(rows))
		id, err := client.execute(rows, req.ClientRequestID, req.ListingVersionID)
		if err != nil {
			return nil, err
		}
		runID = id
	}
	slog.Info("LoomLoom paid video run created", "task_id", taskID, "run_id", runID, "listing_version_id", req.ListingVersionID)
	_ = os.WriteFile(filepath.Join(utils.TaskDir(taskID), "loomloom.json"), []byte(`{"loomloom_run_id":"`+runID+`","loomloom_listing_version_id":"`+req.ListingVersionID+`"}`), 0o644)
	if err := client.waitForRun(runID); err != nil {
		return nil, err
	}
	return client.downloadVideos(runID, utils.TaskDir(taskID))
}

func resolveLoomLoomToken() string {
	cfg := config.Get()
	if strings.EqualFold(cfg.AppString("llm_provider", ""), "shengsuanyun") {
		return cfg.AppString("shengsuanyun_api_key", "")
	}
	return cfg.AppString("loomloom_api_token", "")
}

func buildLoomLoomScenes(params models.VideoParams, terms []string) []map[string]string {
	scenes := terms
	if len(scenes) == 0 && strings.TrimSpace(params.VideoSubject) != "" {
		scenes = []string{params.VideoSubject}
	}
	if len(scenes) > maxLoomLoomVideoScenes {
		scenes = scenes[:maxLoomLoomVideoScenes]
	}
	aspect := string(params.VideoAspect)
	if aspect == "" {
		aspect = string(models.AspectPortrait)
	}
	rows := make([]map[string]string, 0, len(scenes))
	for i, scene := range scenes {
		rows = append(rows, map[string]string{
			"scenePrompt": fmt.Sprintf(
				"Create cinematic stock-footage-style video for a short video about %s. Scene focus: %s. No text, subtitles, captions, watermarks, logos, or spoken audio.",
				params.VideoSubject, scene,
			),
			"aspectRatio": aspect,
			"sceneIndex":  fmt.Sprintf("%d", i+1),
		})
	}
	return rows
}

type loomLoomClient struct {
	base      string
	token     string
	listingID string
}

func (c *loomLoomClient) execute(rows []map[string]string, clientRequestID, listingVersionID string) (string, error) {
	if len(rows) == 0 {
		return "", fmt.Errorf("input_rows is required")
	}
	payload := map[string]any{
		"inputRows":         rows,
		"listingVersionId":  listingVersionID,
		"clientRequestId":   clientRequestID,
		"confirm":           true,
	}
	body, _ := json.Marshal(payload)
	path := fmt.Sprintf("/marketListings/%s:execute", url.PathEscape(c.listingID))
	var last error
	for attempt := 1; attempt <= 3; attempt++ {
		resp, err := c.request(http.MethodPost, path, body, nil)
		if err == nil {
			runID, _ := resp["runId"].(string)
			if strings.TrimSpace(runID) == "" {
				return "", fmt.Errorf("LoomLoom execute returned no runId")
			}
			return runID, nil
		}
		last = err
		time.Sleep(time.Duration(attempt) * time.Second)
	}
	return "", last
}

func (c *loomLoomClient) waitForRun(runID string) error {
	deadline := time.Now().Add(30 * time.Minute)
	for {
		resp, err := c.request(http.MethodGet, "/users/me/runs/"+url.PathEscape(runID), nil, nil)
		if err != nil {
			if time.Now().After(deadline) {
				return fmt.Errorf("LoomLoom run %s could not be queried: %w", runID, err)
			}
			time.Sleep(2 * time.Second)
			continue
		}
		run, _ := resp["run"].(map[string]any)
		status, _ := run["status"].(string)
		status = strings.ToLower(status)
		slog.Info("LoomLoom run progress", "run_id", runID, "status", status)
		switch status {
		case "completed":
			return nil
		case "failed", "cancelled", "canceled":
			detail, _ := run["firstErrorMessage"].(string)
			if detail == "" {
				detail = status
			}
			return fmt.Errorf("LoomLoom run %s ended with %s", runID, detail)
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("LoomLoom run %s did not complete within timeout", runID)
		}
		time.Sleep(2 * time.Second)
	}
}

func (c *loomLoomClient) downloadVideos(runID, destDir string) ([]string, error) {
	rows, err := c.listResultRows(runID)
	if err != nil {
		return nil, err
	}
	if len(rows) == 0 {
		return nil, fmt.Errorf("LoomLoom video run returned no result rows")
	}
	var files []string
	for i, row := range rows {
		status, _ := row["status"].(string)
		if strings.ToLower(status) != "completed" {
			detail, _ := row["errorMessage"].(string)
			if detail == "" {
				detail = status
			}
			return nil, fmt.Errorf("LoomLoom video row %d ended with %s", i+1, detail)
		}
		accessURL, err := videoArtifactURL(row)
		if err != nil {
			return nil, err
		}
		dst := filepath.Join(destDir, fmt.Sprintf("loomloom-video-%02d.mp4", i+1))
		if err := downloadFile(accessURL, dst); err != nil {
			return nil, err
		}
		files = append(files, dst)
	}
	return files, nil
}

func (c *loomLoomClient) listResultRows(runID string) ([]map[string]any, error) {
	var rows []map[string]any
	pageToken := ""
	for {
		q := url.Values{}
		q.Set("pageSize", "200")
		if pageToken != "" {
			q.Set("pageToken", pageToken)
		}
		resp, err := c.request(http.MethodGet, "/users/me/runs/"+url.PathEscape(runID)+"/resultRows", nil, q)
		if err != nil {
			return nil, err
		}
		items, _ := resp["items"].([]any)
		for _, item := range items {
			if m, ok := item.(map[string]any); ok {
				rows = append(rows, m)
			}
		}
		pageToken, _ = resp["nextPageToken"].(string)
		if strings.TrimSpace(pageToken) == "" {
			return rows, nil
		}
	}
}

func (c *loomLoomClient) request(method, path string, body []byte, query url.Values) (map[string]any, error) {
	u := c.base + path
	if query != nil {
		u += "?" + query.Encode()
	}
	var rdr io.Reader
	if body != nil {
		rdr = bytes.NewReader(body)
	}
	req, err := http.NewRequest(method, u, rdr)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := (&http.Client{Timeout: 60 * time.Second}).Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("LoomLoom API %s %s: %d %s", method, path, resp.StatusCode, strings.TrimSpace(string(raw)))
	}
	var parsed map[string]any
	if err := json.Unmarshal(raw, &parsed); err != nil {
		return nil, fmt.Errorf("LoomLoom returned invalid JSON")
	}
	return parsed, nil
}

func videoArtifactURL(row map[string]any) (string, error) {
	artifacts, _ := row["artifacts"].([]any)
	for _, item := range artifacts {
		art, ok := item.(map[string]any)
		if !ok {
			continue
		}
		port, _ := art["portName"].(string)
		mime, _ := art["mimeType"].(string)
		if strings.TrimSpace(port) == "output" && strings.EqualFold(mime, "video/mp4") {
			u, _ := art["accessUrl"].(string)
			if strings.HasPrefix(u, "http") {
				return u, nil
			}
		}
	}
	return "", fmt.Errorf("expected one output video/mp4 artifact")
}
