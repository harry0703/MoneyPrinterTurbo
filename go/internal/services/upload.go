package services

import (
	"bytes"
	"encoding/json"
	"io"
	"log/slog"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/harry0703/moneyprinterturbo/go/internal/config"
	"github.com/harry0703/moneyprinterturbo/go/internal/models"
	"github.com/harry0703/moneyprinterturbo/go/internal/state"
)

var (
	crossPostSlots chan struct{}
	crossPostOnce  sync.Once
)

func crossPostPool() chan struct{} {
	crossPostOnce.Do(func() {
		n := config.Get().AppInt("upload_post_max_pending_tasks", 10)
		if n < 1 {
			n = 1
		}
		crossPostSlots = make(chan struct{}, n)
	})
	return crossPostSlots
}

// ScheduleCrossPost 对应 Python 成片后的异步跨平台发布。
// 不占用视频生成并发；状态写入失败只记日志，不回滚已完成的成片。
func ScheduleCrossPost(st *state.Store, taskID string, videos []string, subject, script, language string) {
	select {
	case crossPostPool() <- struct{}{}:
	default:
		st.Patch(taskID, &models.TaskRecord{
			CrossPostState: models.CrossPostFailed,
			CrossPostError: "cross-post queue is full",
		})
		return
	}
	defer func() { <-crossPostPool() }()

	st.Patch(taskID, &models.TaskRecord{CrossPostState: models.CrossPostProcessing})
	if len(videos) == 0 {
		st.Patch(taskID, &models.TaskRecord{
			CrossPostState: models.CrossPostFailed,
			CrossPostError: "no videos to publish",
		})
		return
	}

	meta, err := GenerateSocialMetadata(subject, script, language, firstUploadPlatform())
	title := subject
	if err == nil {
		if t, ok := meta["title"].(string); ok && t != "" {
			title = t
		}
	}
	result := CrossPost(videos[0], title, nil)
	success, _ := result["success"].(bool)
	if !success {
		msg := "upload-post failed"
		if e, ok := result["error"].(string); ok && e != "" {
			msg = e
		}
		st.Patch(taskID, &models.TaskRecord{
			CrossPostState: models.CrossPostFailed,
			CrossPostError: msg,
		})
		return
	}
	st.Patch(taskID, &models.TaskRecord{CrossPostState: models.CrossPostComplete})
}

func firstUploadPlatform() string {
	platforms := config.Get().AppStrings("upload_post_platforms")
	if len(platforms) == 0 {
		return "tiktok"
	}
	return platforms[0]
}

// CrossPost 把成片上传到 Upload-Post（对应 upload_post.py）。
func CrossPost(videoPath, title string, platforms []string) map[string]any {
	cfg := config.Get()
	if !cfg.AppBool("upload_post_enabled", false) {
		return map[string]any{"success": false, "error": "upload-post is disabled"}
	}
	apiKey := cfg.AppString("upload_post_api_key", "")
	username := cfg.AppString("upload_post_username", "")
	if apiKey == "" || username == "" {
		return map[string]any{"success": false, "error": "upload-post is not configured"}
	}
	if len(platforms) == 0 {
		platforms = cfg.AppStrings("upload_post_platforms")
	}
	if len(platforms) == 0 {
		platforms = []string{"tiktok", "instagram"}
	}

	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	_ = w.WriteField("user", username)
	_ = w.WriteField("title", title)
	for _, p := range platforms {
		_ = w.WriteField("platform[]", p)
	}
	f, err := os.Open(videoPath)
	if err != nil {
		return map[string]any{"success": false, "error": err.Error()}
	}
	defer f.Close()
	part, err := w.CreateFormFile("video", filepath.Base(videoPath))
	if err != nil {
		return map[string]any{"success": false, "error": err.Error()}
	}
	if _, err := io.Copy(part, f); err != nil {
		return map[string]any{"success": false, "error": err.Error()}
	}
	_ = w.Close()

	req, err := http.NewRequest(http.MethodPost, "https://api.upload-post.com/api/upload", &buf)
	if err != nil {
		return map[string]any{"success": false, "error": err.Error()}
	}
	req.Header.Set("Authorization", "Apikey "+apiKey)
	req.Header.Set("Content-Type", w.FormDataContentType())
	client := &http.Client{Timeout: 5 * time.Minute}
	resp, err := client.Do(req)
	if err != nil {
		slog.Error("Failed to upload video", "error", err)
		return map[string]any{"success": false, "error": err.Error()}
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	var parsed map[string]any
	if err := json.Unmarshal(raw, &parsed); err != nil {
		return map[string]any{"success": false, "error": string(raw)}
	}
	if parsed["success"] == nil {
		parsed["success"] = resp.StatusCode < 400
	}
	return parsed
}
