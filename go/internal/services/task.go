// Package services 对应 app/services：共享视频生成流水线及各阶段实现。
package services

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strings"

	"github.com/harry0703/moneyprinterturbo/go/internal/config"
	"github.com/harry0703/moneyprinterturbo/go/internal/models"
	"github.com/harry0703/moneyprinterturbo/go/internal/state"
	"github.com/harry0703/moneyprinterturbo/go/internal/utils"
)

// Pipeline 对应 Python task.start / _run_pipeline。
// API、CLI、WebUI 都必须走这里，保证预检、失败回写和发布只维护一份。
type Pipeline struct {
	State *state.Store
}

// NewPipeline 绑定任务状态仓库，供 API 与 CLI 共用。
func NewPipeline(st *state.Store) *Pipeline {
	return &Pipeline{State: st}
}

func (p *Pipeline) fail(taskID, stage, errMsg string) map[string]any {
	slog.Error("task failed", "task_id", taskID, "stage", stage, "error", errMsg)
	p.State.Update(taskID, models.TaskStateFailed, 0, &models.TaskRecord{
		FailedStage: stage,
		Error:       errMsg,
	})
	return map[string]any{
		"state":        models.TaskStateFailed,
		"failed_stage": stage,
		"error":        errMsg,
	}
}

// Start 执行完整流水线：预检 → 文案 → 关键词 → 配音 → 字幕 → 素材 → 成片 → 可选发布。
func (p *Pipeline) Start(taskID string, params models.VideoParams, opts models.StartOptions) (result map[string]any) {
	defer func() {
		if rec := recover(); rec != nil {
			result = p.fail(taskID, "runtime", fmt.Sprint(rec))
		}
	}()
	stopAt := opts.StopAt
	if stopAt == "" {
		stopAt = "video"
	}
	slog.Info("start task", "task_id", taskID, "stop_at", stopAt)
	p.State.Update(taskID, models.TaskStateProcessing, 5, nil)

	// 1. 预检：完整成片才检查配乐 Key；script/terms 不需要 FFmpeg。
	if err := preflight(params, stopAt); err != nil {
		return p.fail(taskID, "preflight", err.Error())
	}

	// 2. 文案：已有完整脚本则跳过 LLM。
	script, err := generateTaskScript(params)
	if err != nil || script == "" {
		msg := "failed to generate video script"
		if err != nil {
			msg = err.Error()
		}
		return p.fail(taskID, "script", msg)
	}
	p.State.Update(taskID, models.TaskStateProcessing, 10, &models.TaskRecord{Script: script})
	if stopAt == "script" {
		p.State.Update(taskID, models.TaskStateComplete, 100, &models.TaskRecord{Script: script})
		return map[string]any{"script": script, "state": models.TaskStateComplete}
	}

	// 3. 关键词：本地素材不检索；其它来源（含 LoomLoom）仍生成，供记录和可选重排。
	var terms []string
	if params.VideoSource != "local" {
		terms, err = generateTaskTerms(params, script)
		if err != nil || len(terms) == 0 {
			msg := "failed to generate video search terms"
			if err != nil {
				msg = err.Error()
			}
			return p.fail(taskID, "terms", msg)
		}
	}
	_ = writeScriptJSON(taskID, script, terms, params)
	if stopAt == "terms" {
		p.State.Update(taskID, models.TaskStateComplete, 100, &models.TaskRecord{Script: script, Terms: terms})
		return map[string]any{"script": script, "terms": terms, "state": models.TaskStateComplete}
	}

	// 4. 配音：自备音频 / 试听缓存 / TTS / 无配音静音轨。
	p.State.Update(taskID, models.TaskStateProcessing, 20, nil)
	audioFile, audioDur, hasSubMaker, err := GenerateAudio(taskID, params, script, opts.VoicePreview, opts.AllowServerFile)
	if err != nil || audioFile == "" {
		msg := "failed to prepare narration audio"
		if err != nil {
			msg = err.Error()
		}
		return p.fail(taskID, "audio", msg)
	}
	p.State.Update(taskID, models.TaskStateProcessing, 30, &models.TaskRecord{AudioFile: audioFile})
	if stopAt == "audio" {
		p.State.Update(taskID, models.TaskStateComplete, 100, &models.TaskRecord{AudioFile: audioFile})
		return map[string]any{"audio_file": audioFile, "audio_duration": audioDur, "state": models.TaskStateComplete}
	}

	// 5. 字幕：可关闭；Edge 无时间轴则跳过，不自动下载 Whisper。
	subPath, err := GenerateSubtitle(taskID, params, script, audioFile, audioDur, hasSubMaker)
	if err != nil {
		return p.fail(taskID, "subtitle", err.Error())
	}
	if stopAt == "subtitle" {
		p.State.Update(taskID, models.TaskStateComplete, 100, &models.TaskRecord{SubtitlePath: subPath})
		return map[string]any{"subtitle_path": subPath, "state": models.TaskStateComplete}
	}

	// 6. 素材：local / loomloom / pexels / pixabay / coverr / wavespeed。
	p.State.Update(taskID, models.TaskStateProcessing, 40, nil)
	materials, err := GetVideoMaterials(taskID, params, terms, audioDur, opts.LoomLoomVideo)
	if rec := readLoomLoomRun(taskID); rec != "" {
		p.State.Patch(taskID, &models.TaskRecord{LoomLoomRunID: rec})
	}
	if err != nil || len(materials) == 0 {
		msg := "failed to prepare video materials"
		if err != nil {
			msg = err.Error()
		}
		return p.fail(taskID, "materials", msg)
	}
	if stopAt == "materials" {
		p.State.Update(taskID, models.TaskStateComplete, 100, &models.TaskRecord{Materials: materials})
		return map[string]any{"materials": materials, "state": models.TaskStateComplete}
	}

	// 7. 成片：先拼接画面，再混音/字幕/BGM；AI 配乐失败则降级无 BGM。
	p.State.Update(taskID, models.TaskStateProcessing, 50, nil)
	videos, combined, warnings, err := GenerateFinalVideos(taskID, params, materials, audioFile, subPath, audioDur, func(progress int) {
		p.State.Update(taskID, models.TaskStateProcessing, progress, nil)
	})
	if err != nil || len(videos) == 0 {
		msg := "failed to generate final video"
		if err != nil {
			msg = err.Error()
		}
		return p.fail(taskID, "video", msg)
	}

	// 8. 先把生成标为完成，再按需异步跨平台发布，不占用生成并发。
	crossState := ""
	shouldPost := config.Get().AppBool("upload_post_enabled", false) &&
		config.Get().AppBool("upload_post_auto_upload", false)
	if shouldPost {
		crossState = models.CrossPostPending
	}
	rec := &models.TaskRecord{
		Videos:         videos,
		CombinedVideos: combined,
		Script:         script,
		Terms:          terms,
		AudioFile:      audioFile,
		SubtitlePath:   subPath,
		Materials:      materials,
		Warnings:       warnings,
		CrossPostState: crossState,
	}
	p.State.Update(taskID, models.TaskStateComplete, 100, rec)
	slog.Info("task finished", "task_id", taskID, "videos", len(videos))

	if shouldPost {
		// 发布放到独立 goroutine，避免占用生成并发名额。
		go ScheduleCrossPost(p.State, taskID, videos, params.VideoSubject, script, params.VideoLanguage)
	}

	return map[string]any{
		"state":            models.TaskStateComplete,
		"videos":           videos,
		"combined_videos":  combined,
		"script":           script,
		"terms":            terms,
		"audio_file":       audioFile,
		"audio_duration":   audioDur,
		"subtitle_path":    subPath,
		"materials":        materials,
		"warnings":         warnings,
		"cross_post_state": crossState,
	}
}

// preflight 对应 Python 预检：配乐 Key/提示词长度，以及 FFmpeg。
func preflight(params models.VideoParams, stopAt string) error {
	if stopAt == "video" && IsVideoMusicType(params.BGMType) && ShouldUseBGM(params.BGMType, params.BGMVolume) {
		prov, ok := VideoMusicProvider(params.BGMType)
		if ok {
			if !prov.Enabled() {
				return fmt.Errorf("%s background music requires an API key", prov.DisplayName)
			}
			prompt := params.VideoMusicPromptText()
			if prov.MaxPrompt > 0 && len(prompt) > prov.MaxPrompt {
				return fmt.Errorf("%s music prompt exceeds %d characters", prov.DisplayName, prov.MaxPrompt)
			}
			if err := prov.ValidateAccess(); err != nil {
				return err
			}
		}
	}
	if stopAt != "script" && stopAt != "terms" && !utils.CheckFFmpegReady(0) {
		return fmt.Errorf("ffmpeg is not available; install ffmpeg or set IMAGEIO_FFMPEG_EXE")
	}
	return nil
}

func generateTaskScript(params models.VideoParams) (string, error) {
	script := strings.TrimSpace(params.VideoScript)
	if script != "" {
		return script, nil
	}
	return GenerateScript(params.VideoSubject, params.VideoLanguage, params.ParagraphNumber, params.VideoScriptPrompt, params.CustomSystemPrompt)
}

func generateTaskTerms(params models.VideoParams, script string) ([]string, error) {
	if len(params.VideoTerms) > 0 {
		return []string(params.VideoTerms), nil
	}
	amount := 5
	if params.MatchMaterialsToScript {
		// 按文案顺序匹配时多取几个词，避免后面段落没有对应画面。
		amount = 8
	}
	return GenerateTerms(params.VideoSubject, script, amount, params.MatchMaterialsToScript)
}

func writeScriptJSON(taskID, script string, terms []string, params models.VideoParams) error {
	payload := map[string]any{
		"script":       script,
		"search_terms": terms,
		"params":       params,
	}
	data, err := json.MarshalIndent(payload, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(utils.TaskDir(taskID), "script.json"), data, 0o644)
}

// readLoomLoomRun 读取已落盘的付费 run id，供任务状态对外展示。
func readLoomLoomRun(taskID string) string {
	data, err := os.ReadFile(filepath.Join(utils.TaskDir(taskID), "loomloom.json"))
	if err != nil {
		return ""
	}
	var payload struct {
		RunID string `json:"loomloom_run_id"`
	}
	if json.Unmarshal(data, &payload) != nil {
		return ""
	}
	return payload.RunID
}
