// Package auth 对应 app/controllers/base.py：API Key 校验与任务 ID 规范化。
package auth

import (
	"crypto/subtle"
	"net/http"
	"unicode"

	"github.com/google/uuid"
	"github.com/harry0703/moneyprinterturbo/go/internal/config"
)

// MaxTaskIDLength 与 Python 一致，超长或不安全字符会换成新的 UUID。
const MaxTaskIDLength = 128

// HTTPError 鉴权失败时带上状态码，供 API 层原样写出。
type HTTPError struct {
	TaskID     string
	StatusCode int
	Message    string
}

func (e *HTTPError) Error() string {
	return e.Message
}

// NormalizeTaskID 规范化客户端传入的任务 ID。
func NormalizeTaskID(value string) string {
	if value == "" || len(value) > MaxTaskIDLength {
		return uuid.NewString()
	}
	for _, r := range value {
		if !unicode.IsPrint(r) {
			return uuid.NewString()
		}
	}
	return value
}

// TaskIDFromRequest 读取 X-Task-Id 并规范化。
func TaskIDFromRequest(r *http.Request) string {
	return NormalizeTaskID(r.Header.Get("X-Task-Id"))
}

// APIKeyValues 读取全部 x-api-key，多于一个视为无效。
func APIKeyValues(r *http.Request) []string {
	return r.Header.Values("X-Api-Key")
}

// VerifyToken 空 Key 时放行；配置后要求恰好一个匹配的 x-api-key。
func VerifyToken(r *http.Request) *HTTPError {
	configured := config.Get().APIKey()
	if configured == "" {
		return nil
	}
	values := APIKeyValues(r)
	if len(values) != 1 {
		return &HTTPError{TaskID: TaskIDFromRequest(r), StatusCode: 401, Message: "invalid API key"}
	}
	if subtle.ConstantTimeCompare([]byte(values[0]), []byte(configured)) != 1 {
		return &HTTPError{TaskID: TaskIDFromRequest(r), StatusCode: 401, Message: "invalid API key"}
	}
	return nil
}
