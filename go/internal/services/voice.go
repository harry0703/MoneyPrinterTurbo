package services

import (
	"fmt"
	"log/slog"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/harry0703/moneyprinterturbo/go/internal/models"
	"github.com/harry0703/moneyprinterturbo/go/internal/utils"
)

// NoVoiceName 与 Python voice.NO_VOICE_NAME 一致：不自动配音。
const NoVoiceName = "no-voice"

// ParseVoiceName 去掉 WebUI 附加的 -Female/-Male 展示后缀。
func ParseVoiceName(name string) string {
	name = strings.TrimSpace(name)
	name = strings.TrimSuffix(name, "-Female")
	name = strings.TrimSuffix(name, "-Male")
	return name
}

// ResolveCustomAudioFile 对应 Python resolve_custom_audio_file。
// HTTP/WebUI 只能读当前任务目录；CLI 可显式允许本机路径。
func ResolveCustomAudioFile(taskID, customAudio string, allowServerFile bool) (string, error) {
	requested := strings.TrimSpace(customAudio)
	if requested == "" {
		return "", nil
	}
	taskDir := utils.TaskDir(taskID)
	resolved, err := utils.ResolveWithinDirectory(taskDir, requested, true)
	if err == nil {
		return resolved, nil
	}
	// 任务目录内缺失文件可以精确报错；越界路径统一模糊，避免探测宿主机。
	if strings.Contains(err.Error(), "file does not exist") && isUnder(taskDir, requested) {
		return "", err
	}
	if !allowServerFile {
		return "", fmt.Errorf("custom audio file must be stored within the current task directory")
	}
	abs := requested
	if !filepath.IsAbs(abs) {
		abs = filepath.Join(utils.RootDir(), requested)
	}
	abs, _ = filepath.Abs(abs)
	if !filepath.IsAbs(requested) {
		root, _ := filepath.Abs(utils.RootDir())
		rel, relErr := filepath.Rel(root, abs)
		if relErr != nil || strings.HasPrefix(rel, "..") {
			return "", fmt.Errorf("relative custom audio paths must stay within the project directory")
		}
	}
	info, statErr := os.Stat(abs)
	if statErr != nil || info.IsDir() {
		return "", fmt.Errorf("custom audio file does not exist or is not a file")
	}
	return abs, nil
}

func isUnder(base, candidate string) bool {
	absBase, _ := filepath.Abs(base)
	absCand := candidate
	if !filepath.IsAbs(absCand) {
		absCand = filepath.Join(absBase, candidate)
	}
	rel, err := filepath.Rel(absBase, absCand)
	return err == nil && !strings.HasPrefix(rel, "..")
}

// ResolveVoicePreview 校验 WebUI 试听缓存；文案或音色变化则丢弃。
func ResolveVoicePreview(taskID string, params models.VideoParams, script string, preview *models.VoicePreview) (string, float64, bool) {
	if preview == nil {
		return "", 0, false
	}
	if strings.TrimSpace(preview.Script) != strings.TrimSpace(script) ||
		preview.VoiceName != params.VoiceName ||
		preview.VoiceRate != params.VoiceRate ||
		!almostEqual(preview.VoiceVolume, params.VoiceVolume) {
		slog.Info("skip stale voice preview cache", "task_id", taskID)
		return "", 0, false
	}
	file := preview.AudioFile
	taskRoot := utils.TaskDir(taskID)
	abs, err := filepath.Abs(file)
	if err != nil {
		return "", 0, false
	}
	if !isUnder(taskRoot, abs) || !fileExists(abs) || preview.Duration <= 0 || math.IsInf(preview.Duration, 0) {
		slog.Warn("skip invalid voice preview cache", "task_id", taskID)
		return "", 0, false
	}
	slog.Info("using full voice preview audio", "task_id", taskID, "duration", preview.Duration)
	return abs, math.Ceil(preview.Duration), true
}

func almostEqual(a, b float64) bool {
	return math.Abs(a-b) < 1e-9
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

// GenerateAudio 对应 Python generate_audio。
// 返回路径、时长、是否具备 TTS 逐词时间轴（供 Edge 字幕使用）。
func GenerateAudio(taskID string, params models.VideoParams, script string, preview *models.VoicePreview, allowServerFile bool) (string, float64, bool, error) {
	slog.Info("generating audio")
	custom, err := ResolveCustomAudioFile(taskID, params.CustomAudioFile, allowServerFile)
	if err != nil {
		return "", 0, false, fmt.Errorf("invalid custom audio file: %w", err)
	}
	if custom != "" {
		d, err := ProbeDuration(custom)
		if err != nil || d <= 0 {
			return "", 0, false, fmt.Errorf("custom audio duration is zero")
		}
		return custom, math.Ceil(d), false, nil
	}
	if path, dur, ok := ResolveVoicePreview(taskID, params, script, preview); ok {
		return path, dur, true, nil
	}

	out := filepath.Join(utils.TaskDir(taskID), "audio.mp3")
	voice := ParseVoiceName(params.VoiceName)
	if voice == "" || strings.EqualFold(voice, NoVoiceName) {
		// 无配音：用静音轨撑住时间线，后续素材仍按此时长下载。
		if err := WriteSilentAudio(out, 8); err != nil {
			return "", 0, false, err
		}
		return out, 8, false, nil
	}

	if err := SynthesizeSpeech(script, voice, params.VoiceRate, params.VoiceVolume, out); err != nil {
		// 与 Python 一致：TTS 失败直接让任务失败，不用静音轨伪装成功。
		return "", 0, false, fmt.Errorf("failed to synthesize audio; verify the selected voice and TTS connectivity: %w", err)
	}
	d, err := ProbeDuration(out)
	if err != nil || d <= 0 {
		return "", 0, false, fmt.Errorf("generated audio duration is zero")
	}
	return out, math.Ceil(d), true, nil
}

// SynthesizeSpeech 按音色前缀分发 TTS。未识别前缀走 Edge TTS。
func SynthesizeSpeech(text, voice string, rate, volume float64, out string) error {
	switch {
	case strings.HasPrefix(voice, "gemini:"):
		return fmt.Errorf("gemini TTS is not implemented in the Go port; use Edge TTS or custom audio")
	case strings.HasPrefix(voice, "elevenlabs:"):
		return fmt.Errorf("elevenlabs TTS is not implemented in the Go port; use Edge TTS or custom audio")
	case strings.HasPrefix(voice, "chatterbox:"):
		return fmt.Errorf("chatterbox TTS is not implemented in the Go port; use Edge TTS or custom audio")
	case strings.HasPrefix(voice, "fish_audio:"):
		return fmt.Errorf("fish audio TTS is not implemented in the Go port; use Edge TTS or custom audio")
	case strings.HasPrefix(voice, "minimax:") || strings.HasPrefix(voice, "mimo:"):
		return fmt.Errorf("this TTS provider is not implemented in the Go port; use Edge TTS or custom audio")
	default:
		return edgeTTS(text, voice, rate, out)
	}
}

func edgeTTS(text, voice string, rate float64, out string) error {
	if _, err := exec.LookPath("edge-tts"); err != nil {
		return fmt.Errorf("edge-tts CLI not found in PATH")
	}
	percent := int((rate - 1) * 100)
	rateArg := fmt.Sprintf("%+d%%", percent)
	cmd := exec.Command("edge-tts", "--voice", voice, "--rate", rateArg, "--text", text, "--write-media", out)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("edge-tts: %w: %s", err, string(output))
	}
	return nil
}

// WriteSilentAudio 用 FFmpeg 生成指定秒数的静音 MP3。
func WriteSilentAudio(path string, seconds float64) error {
	if seconds < 1 {
		seconds = 1
	}
	cmd := exec.Command(
		utils.FFmpegBinary(),
		"-y", "-f", "lavfi",
		"-i", "anullsrc=r=44100:cl=stereo",
		"-t", fmt.Sprintf("%.2f", seconds),
		"-q:a", "9",
		path,
	)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("silent audio: %w: %s", err, string(out))
	}
	return nil
}

// ProbeDuration 读取任意受支持音频/视频的时长（秒）。
func ProbeDuration(path string) (float64, error) {
	bin := "ffprobe"
	if _, err := exec.LookPath(bin); err != nil {
		bin = utils.FFmpegBinary()
	}
	cmd := exec.Command(bin, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path)
	out, err := cmd.Output()
	if err != nil {
		return 0, err
	}
	var d float64
	_, err = fmt.Sscanf(strings.TrimSpace(string(out)), "%f", &d)
	return d, err
}

func copyFile(src, dst string) error {
	in, err := os.ReadFile(src)
	if err != nil {
		return err
	}
	return os.WriteFile(dst, in, 0o644)
}
