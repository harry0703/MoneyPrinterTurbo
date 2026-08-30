// 请求/任务数据结构，对应 app/models/schema.py。
package models

import (
	"encoding/json"
	"fmt"
	"strings"
)

// VideoConcatMode 素材拼接顺序。
type VideoConcatMode string

const (
	ConcatRandom     VideoConcatMode = "random"
	ConcatSequential VideoConcatMode = "sequential"
)

// VideoAspect 成片画幅。
type VideoAspect string

const (
	AspectLandscape VideoAspect = "16:9"
	AspectPortrait  VideoAspect = "9:16"
	AspectSquare    VideoAspect = "1:1"
)

// Resolution 返回画幅对应的像素宽高。
func (a VideoAspect) Resolution() (int, int, error) {
	switch a {
	case AspectLandscape:
		return 1920, 1080, nil
	case AspectPortrait:
		return 1080, 1920, nil
	case AspectSquare:
		return 1080, 1080, nil
	default:
		return 0, 0, fmt.Errorf("unsupported video aspect: %s", a)
	}
}

// MaterialInfo 单条视频/图片素材。
type MaterialInfo struct {
	Provider   string         `json:"provider"`
	URL        string         `json:"url"`
	Duration   int            `json:"duration"`
	SourceInfo map[string]any `json:"source_info,omitempty"`
}

// StringOrList 兼容 video_terms 既可能是逗号分隔字符串，也可能是字符串数组。
type StringOrList []string

func (s *StringOrList) UnmarshalJSON(data []byte) error {
	if string(data) == "null" {
		*s = nil
		return nil
	}
	var list []string
	if err := json.Unmarshal(data, &list); err == nil {
		*s = list
		return nil
	}
	var raw string
	if err := json.Unmarshal(data, &raw); err != nil {
		return err
	}
	if strings.TrimSpace(raw) == "" {
		*s = nil
		return nil
	}
	parts := strings.FieldsFunc(raw, func(r rune) bool {
		return r == ',' || r == '，'
	})
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		if t := strings.TrimSpace(p); t != "" {
			out = append(out, t)
		}
	}
	*s = out
	return nil
}

// BoolOrString 对应 text_background_color：false 关闭，true 用默认色，字符串为 #RRGGBB。
type BoolOrString struct {
	Enabled bool
	Color   string
	IsColor bool
}

func (b *BoolOrString) UnmarshalJSON(data []byte) error {
	if string(data) == "null" {
		*b = BoolOrString{}
		return nil
	}
	var flag bool
	if err := json.Unmarshal(data, &flag); err == nil {
		b.Enabled = flag
		b.IsColor = false
		return nil
	}
	var color string
	if err := json.Unmarshal(data, &color); err != nil {
		return err
	}
	b.Enabled = color != ""
	b.Color = color
	b.IsColor = color != ""
	return nil
}

func (b BoolOrString) MarshalJSON() ([]byte, error) {
	if b.IsColor {
		return json.Marshal(b.Color)
	}
	return json.Marshal(b.Enabled)
}

// VideoParams 一次视频生成任务的全部参数，对应 Python VideoParams。
type VideoParams struct {
	VideoSubject            string           `json:"video_subject"`
	VideoScript             string           `json:"video_script"`
	VideoTerms              StringOrList     `json:"video_terms"`
	VideoAspect             VideoAspect      `json:"video_aspect"`
	VideoConcatMode         VideoConcatMode  `json:"video_concat_mode"`
	VideoTransitionMode     string           `json:"video_transition_mode"`
	VideoClipDuration       int              `json:"video_clip_duration"`
	VideoClipSpeed          float64          `json:"video_clip_speed"`
	MatchMaterialsToScript  bool             `json:"match_materials_to_script"`
	VideoCount              int              `json:"video_count"`
	VideoSource             string           `json:"video_source"`
	VideoMaterials          []MaterialInfo   `json:"video_materials"`
	CustomAudioFile         string           `json:"custom_audio_file"`
	VideoLanguage           string           `json:"video_language"`
	VoiceName               string           `json:"voice_name"`
	VoiceVolume             float64          `json:"voice_volume"`
	VoiceRate               float64          `json:"voice_rate"`
	BGMType                 string           `json:"bgm_type"`
	BGMFile                 string           `json:"bgm_file"`
	BGMVolume               float64          `json:"bgm_volume"`
	VideoMusicPrompt        string           `json:"video_music_prompt"`
	SoniloBGMPrompt         string           `json:"sonilo_bgm_prompt"`
	SubtitleEnabled         *bool            `json:"subtitle_enabled"`
	SubtitlePosition        string           `json:"subtitle_position"`
	CustomPosition          float64          `json:"custom_position"`
	FontName                string           `json:"font_name"`
	TextForeColor           string           `json:"text_fore_color"`
	TextBackgroundColor     BoolOrString     `json:"text_background_color"`
	RoundedSubtitleBackground bool           `json:"rounded_subtitle_background"`
	FontSize                int              `json:"font_size"`
	StrokeColor             string           `json:"stroke_color"`
	StrokeWidth             float64          `json:"stroke_width"`
	NThreads                int              `json:"n_threads"`
	ParagraphNumber         int              `json:"paragraph_number"`
	VideoScriptPrompt       string           `json:"video_script_prompt"`
	CustomSystemPrompt      string           `json:"custom_system_prompt"`
}

// DefaultVideoParams 返回与 Python 模型一致的默认值。
func DefaultVideoParams() VideoParams {
	enabled := true
	return VideoParams{
		VideoAspect:       AspectPortrait,
		VideoConcatMode:   ConcatRandom,
		VideoClipDuration: 5,
		VideoClipSpeed:    1.0,
		VideoCount:        1,
		VideoSource:       "pexels",
		VoiceName:         "zh-CN-XiaoxiaoNeural-Female",
		VoiceVolume:       1.0,
		VoiceRate:         1.0,
		BGMType:           "random",
		BGMVolume:         0.2,
		SubtitleEnabled:   &enabled,
		SubtitlePosition:  "bottom",
		CustomPosition:    70,
		FontName:          "STHeitiMedium.ttc",
		TextForeColor:     "#FFFFFF",
		FontSize:          60,
		StrokeColor:       "#000000",
		StrokeWidth:       1.5,
		NThreads:          2,
		ParagraphNumber:   1,
	}
}

// SubtitlesOn 字幕默认开启。
func (p VideoParams) SubtitlesOn() bool {
	if p.SubtitleEnabled == nil {
		return true
	}
	return *p.SubtitleEnabled
}

// ScriptRequest 仅生成文案。
type ScriptRequest struct {
	VideoSubject       string `json:"video_subject"`
	VideoLanguage      string `json:"video_language"`
	ParagraphNumber    int    `json:"paragraph_number"`
	VideoScriptPrompt  string `json:"video_script_prompt"`
	CustomSystemPrompt string `json:"custom_system_prompt"`
}

// TermsRequest 仅生成素材关键词。
type TermsRequest struct {
	VideoSubject           string `json:"video_subject"`
	VideoScript            string `json:"video_script"`
	Amount                 int    `json:"amount"`
	MatchMaterialsToScript bool   `json:"match_materials_to_script"`
}

// SocialMetadataRequest 社交发布元数据。
type SocialMetadataRequest struct {
	VideoSubject string `json:"video_subject"`
	VideoScript  string `json:"video_script"`
	Language     string `json:"language"`
	Platform     string `json:"platform"`
}

// APIResponse 统一 JSON 外壳。
type APIResponse struct {
	Status  int    `json:"status"`
	Message string `json:"message,omitempty"`
	Data    any    `json:"data,omitempty"`
}

// VoicePreview WebUI 试听缓存。后台任务会再次核对文案和音色，过期则回退 TTS。
type VoicePreview struct {
	Script     string  `json:"script"`
	VoiceName  string  `json:"voice_name"`
	VoiceRate  float64 `json:"voice_rate"`
	VoiceVolume float64 `json:"voice_volume"`
	AudioFile  string  `json:"audio_file"`
	Duration   float64 `json:"duration"`
}

// LoomLoomVideoRequest 已确认报价的 LoomLoom 付费素材请求。
type LoomLoomVideoRequest struct {
	RunID             string `json:"run_id"`
	ListingVersionID  string `json:"listing_version_id"`
	ClientRequestID   string `json:"client_request_id"`
	APIToken          string `json:"api_token"`
	BaseURL           string `json:"base_url"`
}

// StartOptions 流水线可选入参，对应 Python start() 的关键字参数。
type StartOptions struct {
	StopAt          string
	AllowServerFile bool
	VoicePreview    *VoicePreview
	LoomLoomVideo   *LoomLoomVideoRequest
}

// TaskRecord 任务状态对外字段。
type TaskRecord struct {
	TaskID          string   `json:"task_id"`
	State           int      `json:"state"`
	Progress        int      `json:"progress"`
	Videos          []string `json:"videos,omitempty"`
	CombinedVideos  []string `json:"combined_videos,omitempty"`
	FailedStage     string   `json:"failed_stage,omitempty"`
	Error           string   `json:"error,omitempty"`
	Script          string   `json:"script,omitempty"`
	Terms           []string `json:"terms,omitempty"`
	AudioFile       string   `json:"audio_file,omitempty"`
	SubtitlePath    string   `json:"subtitle_path,omitempty"`
	Materials       []string `json:"materials,omitempty"`
	CrossPostState  string   `json:"cross_post_state,omitempty"`
	CrossPostError  string   `json:"cross_post_error,omitempty"`
	Warnings        []any    `json:"warnings,omitempty"`
	LoomLoomRunID   string   `json:"loomloom_run_id,omitempty"`
}

// MusicWarning 配乐降级时写入任务的警告。
func MusicWarning(code string, index int) map[string]any {
	return map[string]any{"code": code, "video_index": index}
}

// VideoMusicPrompt 读取当前配乐提示词：通用字段优先，Sonilo 兼容旧字段。
func (p VideoParams) VideoMusicPromptText() string {
	prompt := strings.TrimSpace(p.VideoMusicPrompt)
	if p.BGMType == "sonilo" && prompt == "" {
		return strings.TrimSpace(p.SoniloBGMPrompt)
	}
	return prompt
}

// IsBusy 判断任务是否仍在生成或发布，删除入口必须复用。
func (t *TaskRecord) IsBusy() bool {
	if t == nil {
		return false
	}
	if t.State == TaskStateProcessing {
		return true
	}
	switch t.CrossPostState {
	case CrossPostPending, CrossPostProcessing:
		return true
	}
	return false
}
