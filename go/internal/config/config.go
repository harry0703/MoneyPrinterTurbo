// Package config 对应 app/config：读取项目根目录的 config.toml。
package config

import (
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"

	"github.com/pelletier/go-toml/v2"
)

// Config 运行期配置。App/UI 使用 map 以兼容 Python 里动态增减的键。
type Config struct {
	LogLevel    string
	ListenHost  string
	ListenPort  int
	ProjectName string
	App         map[string]any
	UI          map[string]any
	Whisper     map[string]any
	Proxy       map[string]any
	Elevenlabs  map[string]any // [elevenlabs]：TTS 与 Video-to-Music 共用 Key
	mu          sync.RWMutex
}

var global *Config

// Load 从项目根目录加载 config.toml；缺失时复制 config.example.toml。
func Load() (*Config, error) {
	root := RootDir()
	path := filepath.Join(root, "config.toml")
	if info, err := os.Stat(path); err == nil && info.IsDir() {
		_ = os.RemoveAll(path)
	}
	if _, err := os.Stat(path); os.IsNotExist(err) {
		example := filepath.Join(root, "config.example.toml")
		if _, err := os.Stat(example); err == nil {
			data, readErr := os.ReadFile(example)
			if readErr != nil {
				return nil, readErr
			}
			if writeErr := os.WriteFile(path, data, 0o644); writeErr != nil {
				return nil, writeErr
			}
			slog.Info("copy config.example.toml to config.toml")
		}
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("load config: %w", err)
	}
	var tree map[string]any
	if err := toml.Unmarshal(raw, &tree); err != nil {
		return nil, fmt.Errorf("parse config.toml: %w", err)
	}
	cfg := &Config{
		LogLevel:    asString(tree["log_level"], "DEBUG"),
		ListenHost:  asString(tree["listen_host"], "0.0.0.0"),
		ListenPort:  asInt(tree["listen_port"], 8080),
		ProjectName: asString(tree["project_name"], "MoneyPrinterTurbo"),
		App:         asMap(tree["app"]),
		UI:          asMap(tree["ui"]),
		Whisper:    asMap(tree["whisper"]),
		Proxy:      asMap(tree["proxy"]),
		Elevenlabs: asMap(tree["elevenlabs"]),
	}
	if cfg.App == nil {
		cfg.App = map[string]any{}
	}
	if host := os.Getenv("MPT_APP_REDIS_HOST"); host != "" {
		cfg.App["redis_host"] = host
	} else if host := os.Getenv("REDIS_HOST"); host != "" {
		cfg.App["redis_host"] = host
	}
	global = cfg
	slog.Info(fmt.Sprintf("%s loaded config from %s", cfg.ProjectName, path))
	return cfg, nil
}

// Get 返回进程级配置；未 Load 时尝试自动加载。
func Get() *Config {
	if global != nil {
		return global
	}
	if _, err := Load(); err != nil {
		slog.Error("failed to load config", "error", err)
		global = &Config{
			LogLevel:    "DEBUG",
			ListenHost:  "0.0.0.0",
			ListenPort:  8080,
			ProjectName: "MoneyPrinterTurbo",
			App:         map[string]any{},
			UI:          map[string]any{},
		}
	}
	return global
}

// AppString 读取 [app] 字符串配置。
func (c *Config) AppString(key, fallback string) string {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return asString(c.App[key], fallback)
}

// AppBool 读取 [app] 布尔配置。
func (c *Config) AppBool(key string, fallback bool) bool {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return asBool(c.App[key], fallback)
}

// AppInt 读取 [app] 整数配置。
func (c *Config) AppInt(key string, fallback int) int {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return asInt(c.App[key], fallback)
}

// AppStrings 读取 [app] 字符串列表（兼容单个字符串）。
func (c *Config) AppStrings(key string) []string {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return asStringSlice(c.App[key])
}

// APIKey 返回 HTTP API 鉴权密钥；空字符串表示不校验。
func (c *Config) APIKey() string {
	return c.AppString("api_key", "")
}

// SectionString 读取 TOML 顶层表（如 elevenlabs）中的字符串配置。
func (c *Config) SectionString(section, key, fallback string) string {
	c.mu.RLock()
	defer c.mu.RUnlock()
	var m map[string]any
	switch section {
	case "elevenlabs":
		m = c.Elevenlabs
	case "whisper":
		m = c.Whisper
	case "proxy":
		m = c.Proxy
	case "ui":
		m = c.UI
	default:
		m = c.App
	}
	return asString(m[key], fallback)
}

// RootDir 是包含 app/、storage/、config.toml 的 Python 项目根，即 go/ 的上一级。
func RootDir() string {
	wd, err := os.Getwd()
	if err != nil {
		return "."
	}
	// 从当前工作目录或可执行文件附近向上查找 config.example.toml。
	candidates := []string{wd}
	if exe, err := os.Executable(); err == nil {
		candidates = append(candidates, filepath.Dir(exe))
	}
	for _, start := range candidates {
		dir := start
		for i := 0; i < 6; i++ {
			if fileExists(filepath.Join(dir, "config.example.toml")) || fileExists(filepath.Join(dir, "config.toml")) {
				return dir
			}
			parent := filepath.Dir(dir)
			if parent == dir {
				break
			}
			dir = parent
		}
	}
	// go/ 目录内运行时，上一级就是项目根。
	if filepath.Base(wd) == "go" {
		return filepath.Dir(wd)
	}
	return wd
}

// fileExists 判断路径是否存在。
func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

// asMap 把 TOML 表转成 map，缺失时返回空表。
func asMap(v any) map[string]any {
	if m, ok := v.(map[string]any); ok {
		return m
	}
	return map[string]any{}
}

func asString(v any, fallback string) string {
	if v == nil {
		return fallback
	}
	switch t := v.(type) {
	case string:
		return t
	default:
		return fmt.Sprint(t)
	}
}

func asInt(v any, fallback int) int {
	switch t := v.(type) {
	case int:
		return t
	case int64:
		return int(t)
	case float64:
		return int(t)
	case string:
		n, err := strconv.Atoi(strings.TrimSpace(t))
		if err == nil {
			return n
		}
	}
	return fallback
}

func asBool(v any, fallback bool) bool {
	switch t := v.(type) {
	case bool:
		return t
	case string:
		s := strings.ToLower(strings.TrimSpace(t))
		if s == "true" || s == "1" || s == "yes" {
			return true
		}
		if s == "false" || s == "0" || s == "no" {
			return false
		}
	}
	return fallback
}

func asStringSlice(v any) []string {
	switch t := v.(type) {
	case []any:
		out := make([]string, 0, len(t))
		for _, item := range t {
			s := strings.TrimSpace(fmt.Sprint(item))
			if s != "" {
				out = append(out, s)
			}
		}
		return out
	case []string:
		return t
	case string:
		s := strings.TrimSpace(t)
		if s == "" {
			return nil
		}
		return []string{s}
	}
	return nil
}
