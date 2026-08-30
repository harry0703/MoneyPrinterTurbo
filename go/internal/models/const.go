// Package models 对应 Python 的 app/models：任务状态、素材类型和请求参数。
package models

// 任务状态与 Python app/models/const.py 保持一致。
const (
	TaskStateFailed     = -1
	TaskStateComplete   = 1
	TaskStateProcessing = 4

	CrossPostPending    = "pending"
	CrossPostProcessing = "processing"
	CrossPostComplete   = "complete"
	CrossPostFailed     = "failed"
)

// Punctuations 用于字幕断句，含中英文和阿拉伯语标点。
var Punctuations = []string{
	"?", ",", ".", "、", ";", ":", "!", "…",
	"：", "，", "。", "；", "：", "！", "...",
	"،", "؛", "؟",
}

var FileTypeVideos = []string{"mp4", "mov", "mkv", "webm"}
var FileTypeImages = []string{"jpg", "jpeg", "png", "bmp"}
