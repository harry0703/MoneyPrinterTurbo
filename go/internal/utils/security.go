package utils

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// ResolveWithinDirectory 确保用户路径不会逃出白名单目录。
func ResolveWithinDirectory(baseDir, unsafePath string, requireFile bool) (string, error) {
	if strings.TrimSpace(unsafePath) == "" {
		return "", fmt.Errorf("empty path is not allowed")
	}
	base, err := filepath.Abs(baseDir)
	if err != nil {
		return "", err
	}
	base, err = filepath.EvalSymlinks(base)
	if err != nil {
		base, _ = filepath.Abs(baseDir)
	}
	candidate := unsafePath
	if !filepath.IsAbs(candidate) {
		candidate = filepath.Join(base, candidate)
	}
	resolved, err := filepath.Abs(candidate)
	if err != nil {
		return "", err
	}
	if real, err := filepath.EvalSymlinks(resolved); err == nil {
		resolved = real
	}
	rel, err := filepath.Rel(base, resolved)
	if err != nil || strings.HasPrefix(rel, "..") {
		return "", fmt.Errorf("path is outside the allowed directory")
	}
	if requireFile {
		info, err := os.Stat(resolved)
		if err != nil || info.IsDir() {
			return "", fmt.Errorf("file does not exist")
		}
	}
	return resolved, nil
}

// SanitizeFilename 只保留纯文件名，拒绝目录穿越。
func SanitizeFilename(filename string) (string, error) {
	name := filepath.Base(strings.ReplaceAll(filename, "\\", "/"))
	name = strings.TrimSpace(name)
	if name == "" || name == "." || name == ".." {
		return "", fmt.Errorf("invalid filename")
	}
	return name, nil
}
