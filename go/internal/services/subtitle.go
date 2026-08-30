package services

import (
	"fmt"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"unicode/utf8"

	"github.com/harry0703/moneyprinterturbo/go/internal/config"
	"github.com/harry0703/moneyprinterturbo/go/internal/models"
	"github.com/harry0703/moneyprinterturbo/go/internal/utils"
)

// GenerateSubtitle 对应 Python generate_subtitle。
// 关闭字幕、供应商为空、或 Edge 缺少时间轴时返回空路径，绝不自动下载 Whisper。
func GenerateSubtitle(taskID string, params models.VideoParams, script, audioFile string, audioDur float64, hasSubMaker bool) (string, error) {
	if !params.SubtitlesOn() {
		return "", nil
	}
	provider := strings.ToLower(strings.TrimSpace(config.Get().AppString("subtitle_provider", "edge")))
	slog.Info("generating subtitle", "provider", provider)
	if provider == "" {
		slog.Info("subtitle provider is empty, skip subtitle generation")
		return "", nil
	}
	if !hasSubMaker && provider != "whisper" {
		// 自定义音频没有 TTS 逐词时间轴；只有 Whisper 能从音频转写。
		slog.Warn("subtitle maker is missing, skip subtitle generation", "provider", provider)
		return "", nil
	}

	path := filepath.Join(utils.TaskDir(taskID), "subtitle.srt")
	switch provider {
	case "edge":
		if err := writeTimedScriptSRT(path, script, audioDur); err != nil {
			return "", err
		}
		if !fileExists(path) {
			slog.Warn("edge subtitle generation did not produce a subtitle file; skip subtitles without falling back to whisper")
			return "", nil
		}
	case "whisper":
		if err := createWhisperSubtitle(audioFile, path); err != nil {
			slog.Warn("whisper subtitle generation failed", "error", err)
			return "", nil
		}
		correctSubtitle(path, script)
	default:
		slog.Warn("unknown subtitle provider, skip", "provider", provider)
		return "", nil
	}
	if !fileExists(path) {
		slog.Warn("subtitle file is invalid", "path", path)
		return "", nil
	}
	return path, nil
}

// writeTimedScriptSRT 按文案标点切句，再按字数比例分配配音时长。
func writeTimedScriptSRT(path, script string, duration float64) error {
	if strings.TrimSpace(script) == "" || duration <= 0 {
		return nil
	}
	lines := splitScriptLines(script)
	if len(lines) == 0 {
		return nil
	}
	weights := make([]int, len(lines))
	total := 0
	for i, line := range lines {
		n := utf8.RuneCountInString(line)
		if n < 1 {
			n = 1
		}
		weights[i] = n
		total += n
	}
	var b strings.Builder
	cursor := 0.0
	for i, line := range lines {
		seg := duration * float64(weights[i]) / float64(total)
		start := cursor
		end := cursor + seg
		if i == len(lines)-1 {
			end = duration
		}
		fmt.Fprintf(&b, "%d\n%s --> %s\n%s\n\n", i+1, utils.SecondsToSRT(start), utils.SecondsToSRT(end), line)
		cursor = end
	}
	return os.WriteFile(path, []byte(b.String()), 0o644)
}

// createWhisperSubtitle 仅在本机已安装 whisper CLI 时转写；不自动下载模型。
func createWhisperSubtitle(audioFile, subtitleFile string) error {
	bin := ""
	for _, name := range []string{"whisper", "faster-whisper", "whisper-ctranslate2"} {
		if path, err := exec.LookPath(name); err == nil {
			bin = path
			break
		}
	}
	if bin == "" {
		return fmt.Errorf("whisper CLI not found; install it locally or set subtitle_provider=edge")
	}
	dir := filepath.Dir(subtitleFile)
	base := strings.TrimSuffix(filepath.Base(subtitleFile), filepath.Ext(subtitleFile))
	cmd := exec.Command(bin, audioFile, "--output_format", "srt", "--output_dir", dir)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("whisper: %w: %s", err, string(out))
	}
	// whisper 默认写出 <audio>.srt，再复制到任务约定文件名。
	guess := filepath.Join(dir, strings.TrimSuffix(filepath.Base(audioFile), filepath.Ext(audioFile))+".srt")
	if fileExists(guess) && guess != subtitleFile {
		data, err := os.ReadFile(guess)
		if err != nil {
			return err
		}
		if err := os.WriteFile(subtitleFile, data, 0o644); err != nil {
			return err
		}
	}
	if !fileExists(subtitleFile) && fileExists(filepath.Join(dir, base+".srt")) {
		return nil
	}
	if !fileExists(subtitleFile) {
		return fmt.Errorf("whisper did not produce %s", subtitleFile)
	}
	return nil
}

// correctSubtitle 用文案逐行覆盖 Whisper 识别文本，保留原时间轴。
func correctSubtitle(path, script string) {
	data, err := os.ReadFile(path)
	if err != nil {
		return
	}
	expected := splitScriptLines(script)
	if len(expected) == 0 {
		return
	}
	blocks := strings.Split(strings.ReplaceAll(string(data), "\r\n", "\n"), "\n\n")
	var rebuilt strings.Builder
	idx := 0
	for _, block := range blocks {
		block = strings.TrimSpace(block)
		if block == "" {
			continue
		}
		lines := strings.Split(block, "\n")
		if len(lines) < 2 {
			continue
		}
		text := expected[idx%len(expected)]
		if idx < len(expected) {
			text = expected[idx]
		}
		fmt.Fprintf(&rebuilt, "%s\n%s\n%s\n\n", lines[0], lines[1], text)
		idx++
	}
	if rebuilt.Len() > 0 {
		_ = os.WriteFile(path, []byte(rebuilt.String()), 0o644)
	}
}

func splitScriptLines(script string) []string {
	script = strings.ReplaceAll(script, "\r\n", "\n")
	var lines []string
	var buf strings.Builder
	runes := []rune(script)
	for i, r := range runes {
		if r == '\n' {
			if t := strings.TrimSpace(buf.String()); t != "" {
				lines = append(lines, t)
			}
			buf.Reset()
			continue
		}
		buf.WriteRune(r)
		if utils.ContainsPunctuation(string(r)) {
			if i+1 < len(runes) && runes[i] == '.' && isDigit(runes, i-1) && isDigit(runes, i+1) {
				continue
			}
			if t := strings.TrimSpace(buf.String()); t != "" {
				lines = append(lines, strings.TrimRight(t, strings.Join(models.Punctuations, "")))
			}
			buf.Reset()
		}
	}
	if t := strings.TrimSpace(buf.String()); t != "" {
		lines = append(lines, t)
	}
	return lines
}

func isDigit(runes []rune, i int) bool {
	if i < 0 || i >= len(runes) {
		return false
	}
	return runes[i] >= '0' && runes[i] <= '9'
}
