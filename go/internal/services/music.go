package services

import (
	"bufio"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"mime/multipart"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/harry0703/moneyprinterturbo/go/internal/config"
	"github.com/harry0703/moneyprinterturbo/go/internal/utils"
)

// MusicProvider 对应 Python _VIDEO_MUSIC_PROVIDERS 中的一条供应商配置。
// 供应商差异集中在 Key、扩展名、提示词上限和警告码；任务编排复用同一降级路径。
type MusicProvider struct {
	ID          string // sonilo / elevenlabs
	DisplayName string
	Suffix      string
	WarningCode string
	MaxPrompt   int
}

// IsVideoMusicType 判断 BGM 类型是否走付费视频配乐，而不是本地随机/自定义曲库。
func IsVideoMusicType(bgmType string) bool {
	_, ok := VideoMusicProvider(bgmType)
	return ok
}

// VideoMusicProvider 按 bgm_type 返回配乐供应商；未知类型返回 false。
func VideoMusicProvider(bgmType string) (MusicProvider, bool) {
	switch strings.ToLower(strings.TrimSpace(bgmType)) {
	case "sonilo":
		return MusicProvider{
			ID:          "sonilo",
			DisplayName: "Sonilo",
			Suffix:      ".m4a",
			WarningCode: "sonilo_bgm_failed",
			MaxPrompt:   2000,
		}, true
	case "elevenlabs":
		return MusicProvider{
			ID:          "elevenlabs",
			DisplayName: "ElevenLabs",
			Suffix:      ".mp3",
			WarningCode: "elevenlabs_bgm_failed",
			MaxPrompt:   1000,
		}, true
	default:
		return MusicProvider{}, false
	}
}

// Enabled 只要配置了可用 API Key 即为开启。
func (p MusicProvider) Enabled() bool {
	return strings.TrimSpace(p.apiKey()) != ""
}

func (p MusicProvider) apiKey() string {
	cfg := config.Get()
	switch p.ID {
	case "sonilo":
		key := cfg.AppString("sonilo_api_key", "")
		if key == "" {
			key = os.Getenv("SONILO_API_KEY")
		}
		return strings.TrimSpace(key)
	case "elevenlabs":
		key := cfg.SectionString("elevenlabs", "api_key", "")
		if key == "" {
			key = os.Getenv("ELEVENLABS_API_KEY")
		}
		return strings.TrimSpace(key)
	}
	return ""
}

// ValidateAccess 用不会消耗配乐额度的接口预检 Key；失败则任务不应进入成片。
func (p MusicProvider) ValidateAccess() error {
	if !p.Enabled() {
		return fmt.Errorf("%s background music requires an API key", p.DisplayName)
	}
	switch p.ID {
	case "sonilo":
		return validateSonilo(p.apiKey())
	case "elevenlabs":
		return validateElevenLabs(p.apiKey())
	}
	return nil
}

// Generate 为已拼接画面生成一条配乐。失败必须返回错误，由成片阶段降级为无 BGM。
func (p MusicProvider) Generate(videoPath, outputPath string, duration float64, prompt string) error {
	if !p.Enabled() {
		return fmt.Errorf("%s API key is required", p.DisplayName)
	}
	if duration <= 0 {
		return fmt.Errorf("%s video duration is invalid", p.DisplayName)
	}
	prompt = strings.TrimSpace(prompt)
	if p.MaxPrompt > 0 && len(prompt) > p.MaxPrompt {
		return fmt.Errorf("%s music prompt exceeds %d characters", p.DisplayName, p.MaxPrompt)
	}
	proxy, err := createVideoProxy(videoPath, "."+p.ID+"-proxy-")
	if err != nil {
		return err
	}
	defer os.Remove(proxy)
	switch p.ID {
	case "sonilo":
		if duration > 360 {
			return fmt.Errorf("Sonilo supports videos up to 360 seconds")
		}
		return requestSoniloBGM(p.apiKey(), proxy, outputPath, prompt)
	case "elevenlabs":
		if duration > 600 {
			return fmt.Errorf("ElevenLabs supports videos up to 600 seconds")
		}
		return requestElevenLabsBGM(p.apiKey(), proxy, outputPath, prompt)
	default:
		return fmt.Errorf("unknown music provider: %s", p.ID)
	}
}

func validateSonilo(apiKey string) error {
	base := strings.TrimRight(config.Get().AppString("sonilo_base_url", "https://api.sonilo.com"), "/")
	req, err := http.NewRequest(http.MethodGet, base+"/v1/account/services", nil)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+apiKey)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return fmt.Errorf("failed to connect to Sonilo: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return fmt.Errorf("Sonilo connection failed (%d)", resp.StatusCode)
	}
	var payload struct {
		AvailableServices []string `json:"available_services"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		return fmt.Errorf("Sonilo returned an invalid service response")
	}
	for _, id := range payload.AvailableServices {
		if strings.ReplaceAll(strings.ToLower(id), "-", "_") == "video_to_music" {
			return nil
		}
	}
	return fmt.Errorf("Sonilo video-to-music service is not available for this key")
}

func validateElevenLabs(apiKey string) error {
	base := strings.TrimRight(config.Get().SectionString("elevenlabs", "music_base_url", "https://api.elevenlabs.io"), "/")
	req, err := http.NewRequest(http.MethodGet, base+"/v1/user/subscription", nil)
	if err != nil {
		return err
	}
	req.Header.Set("xi-api-key", apiKey)
	resp, err := (&http.Client{Timeout: 30 * time.Second}).Do(req)
	if err != nil {
		return fmt.Errorf("failed to connect to ElevenLabs: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode == 401 {
		return fmt.Errorf("ElevenLabs API key was rejected (401)")
	}
	if resp.StatusCode >= 400 {
		return fmt.Errorf("ElevenLabs account check failed (%d)", resp.StatusCode)
	}
	var payload struct {
		Tier string `json:"tier"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		return fmt.Errorf("ElevenLabs returned an invalid subscription response")
	}
	if strings.EqualFold(strings.TrimSpace(payload.Tier), "free") {
		return fmt.Errorf("ElevenLabs Music API requires a paid plan; the current account is on the free tier")
	}
	if strings.TrimSpace(payload.Tier) == "" {
		return fmt.Errorf("ElevenLabs subscription response does not include an account tier")
	}
	return nil
}

// createVideoProxy 生成无音轨、最长边 1280 的代理视频，避免上传整段高清成片。
func createVideoProxy(videoPath, prefix string) (string, error) {
	dir := filepath.Dir(videoPath)
	tmp, err := os.CreateTemp(dir, prefix+"*.mp4")
	if err != nil {
		return "", err
	}
	proxy := tmp.Name()
	_ = tmp.Close()
	cmd := exec.Command(
		utils.FFmpegBinary(),
		"-nostdin", "-v", "error", "-y", "-i", videoPath,
		"-vf", "scale=w=1280:h=1280:force_original_aspect_ratio=decrease:force_divisible_by=2",
		"-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
		"-pix_fmt", "yuv420p", "-movflags", "+faststart",
		proxy,
	)
	out, err := cmd.CombinedOutput()
	if err != nil {
		_ = os.Remove(proxy)
		return "", fmt.Errorf("failed to generate video proxy: %s", strings.TrimSpace(string(out)))
	}
	info, err := os.Stat(proxy)
	if err != nil || info.Size() <= 0 {
		_ = os.Remove(proxy)
		return "", fmt.Errorf("video proxy is empty")
	}
	return proxy, nil
}

func requestSoniloBGM(apiKey, videoPath, outputPath, prompt string) error {
	base := strings.TrimRight(config.Get().AppString("sonilo_base_url", "https://api.sonilo.com"), "/")
	pr, pw := io.Pipe()
	w := multipart.NewWriter(pw)
	go func() {
		defer pw.Close()
		part, err := w.CreateFormFile("video", filepath.Base(videoPath))
		if err != nil {
			_ = pw.CloseWithError(err)
			return
		}
		f, err := os.Open(videoPath)
		if err != nil {
			_ = pw.CloseWithError(err)
			return
		}
		_, _ = io.Copy(part, f)
		_ = f.Close()
		if prompt != "" {
			_ = w.WriteField("prompt", prompt)
		}
		_ = w.Close()
	}()
	req, err := http.NewRequest(http.MethodPost, base+"/v1/video-to-music", pr)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+apiKey)
	req.Header.Set("Content-Type", w.FormDataContentType())
	client := &http.Client{Timeout: 30 * time.Minute}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("failed to request Sonilo music: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 500))
		return fmt.Errorf("Sonilo generation failed (%d): %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
	tmp := outputPath + ".tmp"
	out, err := os.Create(tmp)
	if err != nil {
		return err
	}
	completed := false
	total := 0
	sc := bufio.NewScanner(resp.Body)
	sc.Buffer(make([]byte, 0, 64*1024), 8*1024*1024)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" {
			continue
		}
		var event map[string]any
		if err := json.Unmarshal([]byte(line), &event); err != nil {
			_ = out.Close()
			_ = os.Remove(tmp)
			return fmt.Errorf("Sonilo returned malformed streaming data")
		}
		typ, _ := event["type"].(string)
		switch typ {
		case "error":
			_ = out.Close()
			_ = os.Remove(tmp)
			return fmt.Errorf("Sonilo generation failed: %v", event["message"])
		case "complete":
			completed = true
		case "audio_chunk":
			idx, _ := event["stream_index"].(float64)
			if idx != 0 {
				continue
			}
			enc, _ := event["data"].(string)
			if enc == "" {
				enc, _ = event["audio"].(string)
			}
			chunk, decErr := base64.StdEncoding.DecodeString(enc)
			if decErr != nil || len(chunk) == 0 {
				_ = out.Close()
				_ = os.Remove(tmp)
				return fmt.Errorf("Sonilo returned an invalid audio chunk")
			}
			total += len(chunk)
			if total > 30*1024*1024 {
				_ = out.Close()
				_ = os.Remove(tmp)
				return fmt.Errorf("Sonilo audio exceeds the 30 MB limit")
			}
			if _, err := out.Write(chunk); err != nil {
				_ = out.Close()
				_ = os.Remove(tmp)
				return err
			}
		}
	}
	_ = out.Close()
	if !completed || total <= 0 {
		_ = os.Remove(tmp)
		return fmt.Errorf("Sonilo stream ended before completion")
	}
	if _, err := ProbeDuration(tmp); err != nil {
		_ = os.Remove(tmp)
		return fmt.Errorf("Sonilo returned audio that FFmpeg cannot decode")
	}
	return os.Rename(tmp, outputPath)
}

func requestElevenLabsBGM(apiKey, videoPath, outputPath, prompt string) error {
	base := strings.TrimRight(config.Get().SectionString("elevenlabs", "music_base_url", "https://api.elevenlabs.io"), "/")
	model := config.Get().SectionString("elevenlabs", "music_model_id", "music_v2")
	if model != "music_v1" && model != "music_v2" {
		model = "music_v2"
	}
	pr, pw := io.Pipe()
	w := multipart.NewWriter(pw)
	go func() {
		defer pw.Close()
		part, err := w.CreateFormFile("videos", filepath.Base(videoPath))
		if err != nil {
			_ = pw.CloseWithError(err)
			return
		}
		f, err := os.Open(videoPath)
		if err != nil {
			_ = pw.CloseWithError(err)
			return
		}
		_, _ = io.Copy(part, f)
		_ = f.Close()
		_ = w.WriteField("model_id", model)
		if prompt != "" {
			_ = w.WriteField("description", prompt)
		}
		_ = w.Close()
	}()
	req, err := http.NewRequest(http.MethodPost, base+"/v1/music/video-to-music?output_format=mp3_44100_128", pr)
	if err != nil {
		return err
	}
	req.Header.Set("xi-api-key", apiKey)
	req.Header.Set("Content-Type", w.FormDataContentType())
	client := &http.Client{Timeout: 30 * time.Minute}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("failed to request ElevenLabs music: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 500))
		return fmt.Errorf("ElevenLabs generation failed (%d): %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
	tmp := outputPath + ".tmp"
	out, err := os.Create(tmp)
	if err != nil {
		return err
	}
	n, err := io.Copy(out, io.LimitReader(resp.Body, 50*1024*1024+1))
	_ = out.Close()
	if err != nil || n <= 0 {
		_ = os.Remove(tmp)
		return fmt.Errorf("ElevenLabs returned no audio data")
	}
	if n > 50*1024*1024 {
		_ = os.Remove(tmp)
		return fmt.Errorf("ElevenLabs audio exceeds the 50 MB limit")
	}
	if _, err := ProbeDuration(tmp); err != nil {
		_ = os.Remove(tmp)
		return fmt.Errorf("ElevenLabs returned audio that FFmpeg cannot decode")
	}
	slog.Info("ElevenLabs background music generated", "output", outputPath, "bytes", n)
	return os.Rename(tmp, outputPath)
}
