// Package utils 对应 app/utils：路径、UUID、FFmpeg 探测和统一响应。
package utils

import (
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/harry0703/moneyprinterturbo/go/internal/config"
	"github.com/harry0703/moneyprinterturbo/go/internal/models"
)

// Response 构造统一 JSON 外壳。
func Response(status int, data any, message string) models.APIResponse {
	return models.APIResponse{Status: status, Data: data, Message: message}
}

// NewUUID 生成任务 ID；removeHyphen 与 Python 行为一致。
func NewUUID(removeHyphen bool) string {
	id := uuid.NewString()
	if removeHyphen {
		return strings.ReplaceAll(id, "-", "")
	}
	return id
}

// RootDir 返回 Python 项目根目录。
func RootDir() string {
	return config.RootDir()
}

// StorageDir 返回 storage 子目录，可选自动创建。
func StorageDir(sub string, create bool) string {
	d := filepath.Join(RootDir(), "storage")
	if sub != "" {
		d = filepath.Join(d, sub)
	}
	if create {
		_ = os.MkdirAll(d, 0o755)
	}
	return d
}

// ResourceDir 返回 resource 子目录。
func ResourceDir(sub string) string {
	d := filepath.Join(RootDir(), "resource")
	if sub != "" {
		d = filepath.Join(d, sub)
	}
	return d
}

// TaskDir 返回任务产物目录 storage/tasks/<id>。
func TaskDir(taskID string) string {
	d := filepath.Join(StorageDir("", false), "tasks")
	if taskID != "" {
		d = filepath.Join(d, taskID)
	}
	_ = os.MkdirAll(d, 0o755)
	return d
}

// FontDir 返回字幕字体目录。
func FontDir() string {
	d := ResourceDir("fonts")
	_ = os.MkdirAll(d, 0o755)
	return d
}

// SongDir 返回内置 BGM 目录。
func SongDir() string {
	d := ResourceDir("songs")
	_ = os.MkdirAll(d, 0o755)
	return d
}

// PublicDir 返回静态站点目录。
func PublicDir() string {
	d := ResourceDir("public")
	_ = os.MkdirAll(d, 0o755)
	return d
}

// NormalizeClipSpeed 把素材倍速限制在 0.5–2，非法值回退默认。
func NormalizeClipSpeed(value float64, defaultValue float64) float64 {
	if math.IsNaN(value) || math.IsInf(value, 0) || value <= 0 {
		return defaultValue
	}
	if value < 0.5 {
		return 0.5
	}
	if value > 2 {
		return 2
	}
	return value
}

func MD5(text string) string {
	sum := md5.Sum([]byte(text))
	return hex.EncodeToString(sum[:])
}

// FFmpegBinary 优先使用 IMAGEIO_FFMPEG_EXE，否则查找 PATH 中的 ffmpeg。
func FFmpegBinary() string {
	if exe := os.Getenv("IMAGEIO_FFMPEG_EXE"); exe != "" {
		return exe
	}
	if path, err := exec.LookPath("ffmpeg"); err == nil {
		return path
	}
	return "ffmpeg"
}

// CheckFFmpegReady 探测 ffmpeg 是否可执行，超时视为不可用。
func CheckFFmpegReady(timeout time.Duration) bool {
	if timeout <= 0 {
		timeout = 10 * time.Second
	}
	bin := FFmpegBinary()
	cmd := exec.Command(bin, "-version")
	if err := cmd.Start(); err != nil {
		slog.Warn("no usable ffmpeg executable found", "bin", bin, "error", err)
		return false
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case err := <-done:
		if err != nil {
			slog.Warn("ffmpeg probe failed", "bin", bin, "error", err)
			return false
		}
		slog.Info("ffmpeg check passed", "bin", bin)
		return true
	case <-time.After(timeout):
		_ = cmd.Process.Kill()
		slog.Warn("ffmpeg probe timed out", "bin", bin)
		return false
	}
}

// SecondsToSRT 把秒数格式化为 SRT 时间戳。
func SecondsToSRT(seconds float64) string {
	if seconds < 0 {
		seconds = 0
	}
	h := int(seconds) / 3600
	m := (int(seconds) % 3600) / 60
	s := int(seconds) % 60
	ms := int(math.Mod(seconds, 1) * 1000)
	return fmt.Sprintf("%02d:%02d:%02d,%03d", h, m, s, ms)
}

func ContainsPunctuation(word string) bool {
	for _, p := range models.Punctuations {
		if strings.Contains(word, p) {
			return true
		}
	}
	return false
}

func ToJSON(v any) string {
	b, err := json.MarshalIndent(v, "", "    ")
	if err != nil {
		slog.Error("failed to serialize object to json", "error", err)
		return ""
	}
	return string(b)
}

func Extension(filename string) string {
	return strings.ToLower(strings.TrimPrefix(filepath.Ext(filename), "."))
}
