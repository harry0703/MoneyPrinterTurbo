// 本地背景音乐解析：随机曲库、自定义文件与是否启用 BGM。
// 付费视频配乐（Sonilo / ElevenLabs）在 music.go，不走这里。
package services

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/harry0703/moneyprinterturbo/go/internal/utils"
)

// SupportedBGMExtensions 本地曲库允许的音频后缀。
var SupportedBGMExtensions = []string{".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma"}

// ShouldUseBGM 音量为 0 或类型为空时跳过配乐，避免无意义的 API/文件读取。
func ShouldUseBGM(bgmType string, volume float64) bool {
	return bgmType != "" && bgmType != "none" && volume > 0
}

// ResolveBGM 解析 random / custom 本地配乐路径；付费供应商不要调用本函数。
func ResolveBGM(bgmType, bgmFile string) (string, error) {
	if bgmType == "" || bgmType == "none" {
		return "", nil
	}
	if bgmType == "custom" && strings.TrimSpace(bgmFile) != "" {
		for _, dir := range []string{utils.StorageDir("bgm", true), utils.SongDir()} {
			if resolved, err := utils.ResolveWithinDirectory(dir, bgmFile, true); err == nil {
				return resolved, nil
			}
		}
		return "", fmt.Errorf("background music file must exist inside storage/bgm or resource/songs")
	}
	// random：从内置歌曲或上传目录任选一个。
	for _, dir := range []string{utils.SongDir(), utils.StorageDir("bgm", true)} {
		entries, err := os.ReadDir(dir)
		if err != nil {
			continue
		}
		for _, e := range entries {
			if e.IsDir() {
				continue
			}
			ext := strings.ToLower(filepath.Ext(e.Name()))
			for _, allowed := range SupportedBGMExtensions {
				if ext == allowed {
					return filepath.Join(dir, e.Name()), nil
				}
			}
		}
	}
	return "", nil
}

// ListBGMFiles 列出内置歌曲与用户上传的 BGM，供 API /musics 使用。
func ListBGMFiles() []string {
	var files []string
	for _, dir := range []string{utils.StorageDir("bgm", true), utils.SongDir()} {
		entries, err := os.ReadDir(dir)
		if err != nil {
			continue
		}
		for _, e := range entries {
			if e.IsDir() {
				continue
			}
			ext := strings.ToLower(filepath.Ext(e.Name()))
			for _, allowed := range SupportedBGMExtensions {
				if ext == allowed {
					files = append(files, filepath.Join(dir, e.Name()))
				}
			}
		}
	}
	return files
}
