// MoneyPrinterTurbo 命令行入口（对应 Python cli.py）。
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"strings"

	"github.com/harry0703/moneyprinterturbo/go/internal/config"
	"github.com/harry0703/moneyprinterturbo/go/internal/models"
	"github.com/harry0703/moneyprinterturbo/go/internal/services"
	"github.com/harry0703/moneyprinterturbo/go/internal/state"
	"github.com/harry0703/moneyprinterturbo/go/internal/utils"
)

func main() {
	subject := flag.String("video-subject", "", "视频主题；未提供 --video-script 时必填")
	script := flag.String("video-script", "", "完整文案；提供后跳过 LLM 写稿")
	terms := flag.String("video-terms", "", "逗号分隔的素材搜索词")
	language := flag.String("video-language", "", "文案语言，例如 zh-CN")
	source := flag.String("video-source", "pexels", "pexels / pixabay / coverr / wavespeed / loomloom / local")
	materials := flag.String("video-materials", "", "本地素材路径，仅 video-source=local")
	stopAt := flag.String("stop-at", "video", "script / terms / audio / subtitle / materials / video")
	aspect := flag.String("video-aspect", "9:16", "9:16 / 16:9 / 1:1")
	count := flag.Int("video-count", 1, "输出成片数量")
	clipDur := flag.Int("video-clip-duration", 5, "单段素材时长（秒）")
	clipSpeed := flag.Float64("video-clip-speed", 1.0, "素材播放倍速 0.5-2")
	matchScript := flag.Bool("match-materials-to-script", false, "按文案顺序匹配素材")
	voice := flag.String("voice-name", "zh-CN-XiaoxiaoNeural-Female", "TTS 音色，或 no-voice")
	voiceRate := flag.Float64("voice-rate", 1.0, "语速")
	voiceVol := flag.Float64("voice-volume", 1.0, "旁白音量")
	customAudio := flag.String("custom-audio-file", "", "已有旁白文件")
	bgmType := flag.String("bgm-type", "random", "none / random / custom / sonilo / elevenlabs")
	bgmFile := flag.String("bgm-file", "", "自定义 BGM 文件名")
	bgmVol := flag.Float64("bgm-volume", 0.2, "BGM 音量")
	musicPrompt := flag.String("video-music-prompt", "", "Sonilo / ElevenLabs 配乐提示词")
	noSubtitle := flag.Bool("no-subtitle-enabled", false, "关闭字幕")
	taskID := flag.String("task-id", "", "自定义任务 UUID，省略则自动生成")
	flag.Parse()

	if strings.TrimSpace(*subject) == "" && strings.TrimSpace(*script) == "" {
		fmt.Fprintln(os.Stderr, "one of --video-subject or --video-script is required")
		os.Exit(2)
	}

	if _, err := config.Load(); err != nil {
		slog.Error("load config failed", "error", err)
		os.Exit(2)
	}

	params := models.DefaultVideoParams()
	params.VideoSubject = strings.TrimSpace(*subject)
	params.VideoScript = *script
	params.VideoSource = *source
	params.VideoAspect = models.VideoAspect(*aspect)
	params.VideoCount = *count
	params.VoiceName = *voice
	params.CustomAudioFile = *customAudio
	params.BGMType = *bgmType
	params.BGMFile = *bgmFile
	params.BGMVolume = *bgmVol
	params.VideoMusicPrompt = *musicPrompt
	params.VideoLanguage = *language
	params.VideoClipDuration = *clipDur
	params.VideoClipSpeed = *clipSpeed
	params.MatchMaterialsToScript = *matchScript
	params.VoiceRate = *voiceRate
	params.VoiceVolume = *voiceVol
	if *terms != "" {
		raw, _ := json.Marshal(*terms)
		_ = params.VideoTerms.UnmarshalJSON(raw)
	}
	if *materials != "" {
		for _, item := range strings.Split(*materials, ",") {
			item = strings.TrimSpace(item)
			if item == "" {
				continue
			}
			params.VideoMaterials = append(params.VideoMaterials, models.MaterialInfo{
				Provider: "local",
				URL:      item,
			})
		}
	}
	if *noSubtitle {
		off := false
		params.SubtitleEnabled = &off
	}

	id := strings.TrimSpace(*taskID)
	if id == "" {
		id = utils.NewUUID(false)
	}
	pipe := services.NewPipeline(state.New())
	slog.Info("start CLI task", "task_id", id, "stop_at", *stopAt)
	result := pipe.Start(id, params, models.StartOptions{StopAt: *stopAt, AllowServerFile: true})
	if stateVal, _ := result["state"].(int); stateVal == models.TaskStateFailed {
		slog.Error("CLI task failed", "task_id", id, "stage", result["failed_stage"], "error", result["error"])
		os.Exit(1)
	}
	out, _ := json.Marshal(map[string]any{"task_id": id, "result": result})
	fmt.Println(string(out))
}
