package services

import (
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"math"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync/atomic"
	"time"

	"github.com/harry0703/moneyprinterturbo/go/internal/config"
	"github.com/harry0703/moneyprinterturbo/go/internal/models"
	"github.com/harry0703/moneyprinterturbo/go/internal/utils"
)

var apiKeyCounter uint64

func nextAPIKey(cfgKey string) string {
	keys := config.Get().AppStrings(cfgKey)
	if len(keys) == 0 {
		return ""
	}
	n := atomic.AddUint64(&apiKeyCounter, 1)
	return keys[int(n-1)%len(keys)]
}

// GetVideoMaterials 对应 Python get_video_materials：本地预处理 / LoomLoom / 库存下载 / WaveSpeed。
func GetVideoMaterials(taskID string, params models.VideoParams, terms []string, audioDur float64, loom *models.LoomLoomVideoRequest) ([]string, error) {
	source := strings.ToLower(strings.TrimSpace(params.VideoSource))
	if source == "" {
		source = "pexels"
	}
	switch source {
	case "local":
		return preprocessLocalMaterials(taskID, params)
	case "loomloom":
		return FetchLoomLoomVideos(taskID, params, terms, loom)
	case "wavespeed":
		return downloadWavespeedOnDemand(taskID, terms, params, audioDur)
	default:
		return downloadStockVideos(taskID, source, terms, params, audioDur)
	}
}

// preprocessLocalMaterials 校验并复制本地素材到任务目录，可选按片段时长裁剪。
func preprocessLocalMaterials(taskID string, params models.VideoParams) ([]string, error) {
	if len(params.VideoMaterials) == 0 {
		return nil, fmt.Errorf("no valid local video materials were found")
	}
	dir := utils.TaskDir(taskID)
	clip := params.VideoClipDuration
	if clip < 1 {
		clip = 4
	}
	var files []string
	for i, m := range params.VideoMaterials {
		src := strings.TrimSpace(m.URL)
		if src == "" {
			continue
		}
		if !filepath.IsAbs(src) {
			resolved, err := utils.ResolveWithinDirectory(utils.StorageDir("local_videos", true), src, true)
			if err != nil {
				resolved, err = utils.ResolveWithinDirectory(dir, src, true)
				if err != nil {
					return nil, fmt.Errorf("invalid local material %q: %w", src, err)
				}
			}
			src = resolved
		}
		if !fileExists(src) {
			return nil, fmt.Errorf("local material does not exist: %s", src)
		}
		dst := filepath.Join(dir, fmt.Sprintf("local-%02d%s", i+1, filepath.Ext(src)))
		if err := trimOrCopyVideo(src, dst, clip); err != nil {
			return nil, err
		}
		files = append(files, dst)
	}
	if len(files) == 0 {
		return nil, fmt.Errorf("no valid local video materials were found")
	}
	return files, nil
}

func trimOrCopyVideo(src, dst string, clipSec int) error {
	cmd := exec.Command(
		utils.FFmpegBinary(),
		"-y", "-i", src,
		"-t", fmt.Sprintf("%d", clipSec),
		"-c", "copy",
		dst,
	)
	if out, err := cmd.CombinedOutput(); err == nil && fileExists(dst) {
		return nil
	} else if err != nil {
		slog.Warn("ffmpeg copy-trim failed, fallback to full copy", "error", strings.TrimSpace(string(out)))
	}
	return copyFile(src, dst)
}

func downloadStockVideos(taskID, source string, terms []string, params models.VideoParams, audioDur float64) ([]string, error) {
	aspect := params.VideoAspect
	if aspect == "" {
		aspect = models.AspectPortrait
	}
	minDur := params.VideoClipDuration
	if minDur < 1 {
		minDur = 5
	}
	need := audioDur * float64(maxInt(params.VideoCount, 1))
	if need <= 0 {
		need = float64(minDur)
	}
	search := searchFunc(source)
	if search == nil {
		return nil, fmt.Errorf("unsupported video source: %s", source)
	}

	var items []models.MaterialInfo
	seen := map[string]bool{}
	for _, term := range terms {
		hits := search(term, minDur, aspect)
		for _, hit := range hits {
			if seen[hit.URL] {
				continue
			}
			seen[hit.URL] = true
			items = append(items, hit)
		}
	}
	if params.VideoConcatMode != models.ConcatSequential && !params.MatchMaterialsToScript {
		// 随机拼接时打乱候选，避免每次都用同一批热门素材。
		shuffleMaterials(items)
	}

	dir := materialSaveDir(taskID)
	var files []string
	var collected float64
	for _, hit := range items {
		if collected >= need {
			break
		}
		name := fmt.Sprintf("vid-%s.mp4", utils.MD5(hit.URL))
		dst := filepath.Join(dir, name)
		if err := downloadFile(hit.URL, dst); err != nil {
			slog.Warn("download material failed", "provider", hit.Provider, "error", err)
			continue
		}
		files = append(files, dst)
		if hit.Duration > 0 {
			collected += math.Min(float64(hit.Duration), float64(minDur))
		} else {
			collected += float64(minDur)
		}
	}
	if len(files) == 0 {
		return nil, fmt.Errorf("failed to download video materials from %s", source)
	}
	return files, nil
}

func materialSaveDir(taskID string) string {
	configured := strings.TrimSpace(config.Get().AppString("material_directory", ""))
	if configured == "task" || configured == "" {
		return utils.TaskDir(taskID)
	}
	if info, err := os.Stat(configured); err == nil && info.IsDir() {
		return configured
	}
	return utils.TaskDir(taskID)
}

func searchFunc(source string) func(string, int, models.VideoAspect) []models.MaterialInfo {
	switch source {
	case "pexels":
		return SearchPexels
	case "pixabay":
		return SearchPixabay
	case "coverr":
		return SearchCoverr
	default:
		return nil
	}
}

func shuffleMaterials(items []models.MaterialInfo) {
	for i := len(items) - 1; i > 0; i-- {
		j := int(time.Now().UnixNano() % int64(i+1))
		items[i], items[j] = items[j], items[i]
	}
}

type pexelsSearch struct {
	Videos []struct {
		Duration int    `json:"duration"`
		URL      string `json:"url"`
		Files    []struct {
			Width  int    `json:"width"`
			Height int    `json:"height"`
			Link   string `json:"link"`
		} `json:"video_files"`
	} `json:"videos"`
}

// SearchPexels 按关键词和画幅搜索 Pexels 库存视频。
func SearchPexels(term string, minDuration int, aspect models.VideoAspect) []models.MaterialInfo {
	w, h, err := aspect.Resolution()
	if err != nil {
		return nil
	}
	orientation := "portrait"
	switch aspect {
	case models.AspectLandscape:
		orientation = "landscape"
	case models.AspectSquare:
		orientation = "square"
	}
	key := nextAPIKey("pexels_api_keys")
	if key == "" {
		slog.Error("pexels_api_keys is empty")
		return nil
	}
	q := url.Values{}
	q.Set("query", term)
	q.Set("per_page", "20")
	q.Set("orientation", orientation)
	req, _ := http.NewRequest(http.MethodGet, "https://api.pexels.com/v1/videos/search?"+q.Encode(), nil)
	req.Header.Set("Authorization", key)
	req.Header.Set("User-Agent", "MoneyPrinterTurbo-Go")
	resp, err := (&http.Client{Timeout: 60 * time.Second}).Do(req)
	if err != nil {
		slog.Error("pexels video search failed", "error", err)
		return nil
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	var parsed pexelsSearch
	if err := json.Unmarshal(raw, &parsed); err != nil {
		slog.Error("pexels video search returned an unsupported response")
		return nil
	}
	var items []models.MaterialInfo
	for _, v := range parsed.Videos {
		if v.Duration < minDuration {
			continue
		}
		for _, f := range v.Files {
			if matchesAspect(f.Width, f.Height, aspect) || (f.Width == w && f.Height == h) {
				items = append(items, models.MaterialInfo{
					Provider: "pexels",
					URL:      f.Link,
					Duration: v.Duration,
					SourceInfo: map[string]any{
						"provider":    "pexels",
						"search_term": term,
						"source_page": v.URL,
					},
				})
				break
			}
		}
	}
	return items
}

// SearchPixabay 搜索 Pixabay 视频；方形画幅放宽方向，横竖屏必须匹配。
func SearchPixabay(term string, minDuration int, aspect models.VideoAspect) []models.MaterialInfo {
	key := nextAPIKey("pixabay_api_keys")
	if key == "" {
		slog.Error("pixabay_api_keys is empty")
		return nil
	}
	targetW, _, _ := aspect.Resolution()
	q := url.Values{}
	q.Set("q", term)
	q.Set("video_type", "all")
	q.Set("per_page", "50")
	q.Set("key", key)
	resp, err := http.Get("https://pixabay.com/api/videos/?" + q.Encode())
	if err != nil {
		slog.Error("pixabay search request failed", "error", err)
		return nil
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		slog.Error("pixabay search request failed", "status", resp.StatusCode)
		return nil
	}
	var parsed struct {
		Hits []struct {
			ID       any                    `json:"id"`
			Duration int                    `json:"duration"`
			PageURL  string                 `json:"pageURL"`
			User     string                 `json:"user"`
			Videos   map[string]pixabayFile `json:"videos"`
		} `json:"hits"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&parsed); err != nil {
		slog.Error("pixabay returned an unexpected non-JSON response")
		return nil
	}
	var items []models.MaterialInfo
	for _, v := range parsed.Hits {
		if v.Duration < minDuration {
			continue
		}
		for rendition, f := range v.Videos {
			ok := aspect == models.AspectSquare || matchesAspect(f.Width, f.Height, aspect)
			if ok && f.Width >= targetW && f.URL != "" {
				items = append(items, models.MaterialInfo{
					Provider: "pixabay",
					URL:      f.URL,
					Duration: v.Duration,
					SourceInfo: map[string]any{
						"provider":    "pixabay",
						"search_term": term,
						"asset_id":    fmt.Sprint(v.ID),
						"source_page": v.PageURL,
						"rendition":   rendition,
					},
				})
				break
			}
		}
	}
	return items
}

type pixabayFile struct {
	URL    string `json:"url"`
	Width  int    `json:"width"`
	Height int    `json:"height"`
}

// SearchCoverr 搜索 Coverr 免费高清素材，用 urls.mp4_download 作为下载地址。
func SearchCoverr(term string, minDuration int, aspect models.VideoAspect) []models.MaterialInfo {
	key := nextAPIKey("coverr_api_keys")
	if key == "" {
		slog.Error("coverr_api_keys is empty")
		return nil
	}
	q := url.Values{}
	q.Set("query", term)
	q.Set("page_size", "20")
	q.Set("urls", "true")
	q.Set("sort", "popular")
	if aspect == models.AspectPortrait {
		q.Set("filter", "is_vertical:true")
	} else if aspect == models.AspectLandscape {
		q.Set("filter", "is_vertical:false")
	}
	req, _ := http.NewRequest(http.MethodGet, "https://api.coverr.co/videos?"+q.Encode(), nil)
	req.Header.Set("Authorization", "Bearer "+key)
	resp, err := (&http.Client{Timeout: 60 * time.Second}).Do(req)
	if err != nil {
		slog.Error("coverr video search failed", "error", err)
		return nil
	}
	defer resp.Body.Close()
	var parsed struct {
		Hits []struct {
			ID          any     `json:"id"`
			Duration    any     `json:"duration"`
			MaxWidth    int     `json:"max_width"`
			MaxHeight   int     `json:"max_height"`
			IsVertical  bool    `json:"is_vertical"`
			CanonicalURL string `json:"canonical_url"`
			URLs        struct {
				MP4Download string `json:"mp4_download"`
			} `json:"urls"`
		} `json:"hits"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&parsed); err != nil {
		slog.Error("coverr video search returned an unsupported response")
		return nil
	}
	var items []models.MaterialInfo
	for _, v := range parsed.Hits {
		dur := anyToInt(v.Duration)
		if dur < minDuration || v.URLs.MP4Download == "" {
			continue
		}
		if aspect != models.AspectSquare && !matchesAspect(v.MaxWidth, v.MaxHeight, aspect) {
			continue
		}
		items = append(items, models.MaterialInfo{
			Provider: "coverr",
			URL:      v.URLs.MP4Download,
			Duration: dur,
			SourceInfo: map[string]any{
				"provider":    "coverr",
				"search_term": term,
				"asset_id":    fmt.Sprint(v.ID),
				"source_page": v.CanonicalURL,
			},
		})
	}
	return items
}

func matchesAspect(w, h int, aspect models.VideoAspect) bool {
	if w <= 0 || h <= 0 {
		return false
	}
	switch aspect {
	case models.AspectPortrait:
		return h > w
	case models.AspectLandscape:
		return w > h
	case models.AspectSquare:
		return true
	}
	return false
}

func anyToInt(v any) int {
	switch t := v.(type) {
	case float64:
		return int(t)
	case int:
		return t
	case string:
		var n float64
		_, _ = fmt.Sscanf(t, "%f", &n)
		return int(n)
	}
	return 0
}

const wavespeedAPI = "https://api.wavespeed.ai/api/v3"

func downloadWavespeedOnDemand(taskID string, terms []string, params models.VideoParams, audioDur float64) ([]string, error) {
	minDur := params.VideoClipDuration
	if minDur < 1 {
		minDur = 5
	}
	need := audioDur
	if need <= 0 {
		need = float64(minDur)
	}
	dir := materialSaveDir(taskID)
	var files []string
	var collected float64
	for _, term := range terms {
		if collected >= need {
			break
		}
		hits, err := generateWavespeed(term, minDur, params.VideoAspect)
		if err != nil {
			// 付费任务状态不明时停止继续下单，避免重复扣费。
			return filesOrErr(files, err)
		}
		for _, hit := range hits {
			dst := filepath.Join(dir, fmt.Sprintf("wavespeed-%s.mp4", utils.MD5(hit.URL)))
			if err := downloadFile(hit.URL, dst); err != nil {
				slog.Warn("wavespeed download failed", "error", err)
				continue
			}
			files = append(files, dst)
			collected += math.Min(float64(hit.Duration), float64(minDur))
			if collected >= need {
				break
			}
		}
	}
	if len(files) == 0 {
		return nil, fmt.Errorf("failed to download video materials from wavespeed")
	}
	return files, nil
}

func filesOrErr(files []string, err error) ([]string, error) {
	if len(files) > 0 {
		slog.Error("stop submitting new wavespeed tasks", "error", err)
		return files, nil
	}
	return nil, err
}

func generateWavespeed(term string, minDuration int, aspect models.VideoAspect) ([]models.MaterialInfo, error) {
	key := nextAPIKey("wavespeed_api_keys")
	if key == "" {
		return nil, fmt.Errorf("wavespeed_api_keys is empty")
	}
	model := strings.Trim(config.Get().AppString("wavespeed_text_to_video_model", "bytedance/seedance-2.0-fast/text-to-video"), "/")
	lo := config.Get().AppInt("wavespeed_min_duration", 4)
	hi := config.Get().AppInt("wavespeed_max_duration", 15)
	dur := minDuration
	if dur < lo {
		dur = lo
	}
	if dur > hi {
		dur = hi
	}
	if aspect == "" {
		aspect = models.AspectPortrait
	}
	payload, _ := json.Marshal(map[string]any{
		"prompt":       term,
		"aspect_ratio": string(aspect),
		"duration":     dur,
	})
	req, err := http.NewRequest(http.MethodPost, wavespeedAPI+"/"+model, strings.NewReader(string(payload)))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+key)
	req.Header.Set("Content-Type", "application/json")
	resp, err := (&http.Client{Timeout: 60 * time.Second}).Do(req)
	if err != nil {
		return nil, fmt.Errorf("wavespeed submission did not return a response, the task may already exist remotely: %w", err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 500 {
		return nil, fmt.Errorf("wavespeed submission failed with HTTP %d, the task may already exist remotely", resp.StatusCode)
	}
	var body map[string]any
	if err := json.Unmarshal(raw, &body); err != nil {
		return nil, fmt.Errorf("wavespeed submission returned an unreadable response")
	}
	code, _ := body["code"].(float64)
	if code != 200 {
		slog.Error("wavespeed video generation request rejected", "code", body["code"])
		return nil, nil
	}
	data, _ := body["data"].(map[string]any)
	predictionID, _ := data["id"].(string)
	if predictionID == "" {
		return nil, fmt.Errorf("wavespeed accepted the submission without returning a prediction id")
	}
	slog.Info("wavespeed prediction created", "id", predictionID)
	result, err := waitWavespeed(predictionID, key)
	if err != nil || result == nil {
		return nil, err
	}
	var items []models.MaterialInfo
	outputs, _ := result["outputs"].([]any)
	for _, out := range outputs {
		u, _ := out.(string)
		if strings.HasPrefix(u, "http") {
			items = append(items, models.MaterialInfo{
				Provider: "wavespeed",
				URL:      u,
				Duration: dur,
				SourceInfo: map[string]any{
					"provider":    "wavespeed",
					"search_term": term,
					"asset_id":    predictionID,
				},
			})
		}
	}
	return items, nil
}

func waitWavespeed(predictionID, key string) (map[string]any, error) {
	deadline := time.Now().Add(10 * time.Minute)
	failures := 0
	for {
		req, _ := http.NewRequest(http.MethodGet, wavespeedAPI+"/predictions/"+predictionID+"/result", nil)
		req.Header.Set("Authorization", "Bearer "+key)
		resp, err := (&http.Client{Timeout: 60 * time.Second}).Do(req)
		if err != nil {
			failures++
			if failures > 5 {
				return nil, fmt.Errorf("wavespeed prediction polling failed, prediction_id=%s: %w", predictionID, err)
			}
			time.Sleep(time.Duration(failures) * time.Second)
			continue
		}
		raw, _ := io.ReadAll(resp.Body)
		_ = resp.Body.Close()
		if resp.StatusCode == 429 || resp.StatusCode >= 500 {
			failures++
			if failures > 5 {
				return nil, fmt.Errorf("wavespeed prediction polling failed after retries, prediction_id=%s", predictionID)
			}
			time.Sleep(time.Duration(failures) * time.Second)
			continue
		}
		failures = 0
		var body map[string]any
		if err := json.Unmarshal(raw, &body); err != nil {
			return nil, fmt.Errorf("wavespeed prediction result payload is malformed, prediction_id=%s", predictionID)
		}
		if code, _ := body["code"].(float64); code != 200 {
			return nil, fmt.Errorf("wavespeed prediction status is unknown, prediction_id=%s", predictionID)
		}
		data, _ := body["data"].(map[string]any)
		status, _ := data["status"].(string)
		switch status {
		case "completed":
			return data, nil
		case "failed", "cancelled", "timeout":
			slog.Error("wavespeed prediction did not produce a video", "id", predictionID, "status", status)
			return nil, nil
		}
		if time.Now().After(deadline) {
			return nil, fmt.Errorf("wavespeed prediction is still %s after timeout, prediction_id=%s", status, predictionID)
		}
		time.Sleep(2 * time.Second)
	}
}

func downloadFile(rawURL, dst string) error {
	client := &http.Client{Timeout: 180 * time.Second}
	resp, err := client.Get(rawURL)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return fmt.Errorf("download status %d", resp.StatusCode)
	}
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}
	return os.WriteFile(dst, data, 0o644)
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}
