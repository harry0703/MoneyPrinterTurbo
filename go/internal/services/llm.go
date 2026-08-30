// LLM 文案、关键词与社交元数据：对应 app/services/llm.py。
// 系统提示保持英文，与 Python 版一致，避免改写后影响模型输出格式。
package services

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"regexp"
	"strings"
	"time"

	"github.com/harry0703/moneyprinterturbo/go/internal/config"
	"github.com/harry0703/moneyprinterturbo/go/internal/models"
)

const (
	maxScriptRetries       = 5
	maxScriptPromptLen     = 2000
	maxSystemPromptLen     = 8000
	defaultScriptSystem = `# Role: Video Script Generator

## Goals:
Generate a script for a video, depending on the subject of the video.

## Constrains:
1. the script is to be returned as a string with the specified number of paragraphs.
2. do not under any circumstance reference this prompt in your response.
3. get straight to the point, don't start with unnecessary things like, "welcome to this video".
4. you must not include any type of markdown or formatting in the script, never use a title.
5. only return the raw content of the script.
6. do not include "voiceover", "narrator" or similar indicators of what should be spoken at the beginning of each paragraph or line.
7. you must not mention the prompt, or anything about the script itself. also, never talk about the amount of paragraphs or lines. just write the script.
8. respond in the same language as the video subject.`
)

var (
	thinkBlockRe         = regexp.MustCompile(`(?is)<think\b[^>]*>.*?</think>`)
	unclosedThinkBlockRe = regexp.MustCompile(`(?is)<think\b[^>]*>.*$`)
	urlUserinfoRe        = regexp.MustCompile(`(?i)((?:https?|wss?)://)([^/\s?#@]*:[^/\s?#@]*@)`)
	sensitiveQueryRe     = regexp.MustCompile(`(?i)([?&](?:api[_-]?key|access[_-]?token|token|key|secret|password)=)([^&#\s]+)`)
)

func limitText(text string, maxLen int) string {
	text = strings.TrimSpace(text)
	if len(text) <= maxLen {
		return text
	}
	return text[:maxLen]
}

func normalizeParagraphs(n int) int {
	if n < 1 {
		return 1
	}
	if n > 10 {
		return 10
	}
	return n
}

func sanitizeError(err error) string {
	msg := err.Error()
	msg = urlUserinfoRe.ReplaceAllString(msg, "${1}***:***@")
	msg = sensitiveQueryRe.ReplaceAllString(msg, "${1}***")
	return msg
}

func normalizeLLMText(content, provider string) (string, error) {
	content = thinkBlockRe.ReplaceAllString(content, "")
	content = unclosedThinkBlockRe.ReplaceAllString(content, "")
	content = strings.TrimSpace(content)
	if content == "" {
		return "", fmt.Errorf("[%s] returned empty text content", provider)
	}
	return content, nil
}

// BuildScriptPrompt 拼装写稿提示词；用户附加要求和系统提示有长度上限。
func BuildScriptPrompt(subject, language string, paragraphs int, extra, system string) string {
	paragraphs = normalizeParagraphs(paragraphs)
	extra = limitText(extra, maxScriptPromptLen)
	system = limitText(system, maxSystemPromptLen)
	prompt := system
	if prompt == "" {
		prompt = defaultScriptSystem
	}
	prompt += fmt.Sprintf("\n\n# Initialization:\n- video subject: %s\n- number of paragraphs: %d", subject, paragraphs)
	if language != "" {
		prompt += "\n- language: " + language
	}
	if extra != "" {
		prompt += "\n\n# Additional User Requirements:\n" + extra
	}
	return prompt
}

type chatRequest struct {
	Model    string       `json:"model"`
	Messages []chatMessage `json:"messages"`
}

type chatMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type chatResponse struct {
	Choices []struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
	} `json:"choices"`
	Error *struct {
		Message string `json:"message"`
	} `json:"error"`
}

// generateLLMResponse 调用当前配置的 OpenAI 兼容接口。
func generateLLMResponse(prompt string) (string, error) {
	cfg := config.Get()
	providerID := strings.ToLower(cfg.AppString("llm_provider", models.DefaultLLMProviderID))
	provider, ok := models.GetLLMProvider(providerID)
	if !ok {
		return "", fmt.Errorf("%s: unsupported llm provider", providerID)
	}
	apiKey := cfg.AppString(provider.ConfigKey("api_key"), "")
	modelName := provider.ResolveModelName(cfg.AppString(provider.ConfigKey("model_name"), ""))
	baseURL := provider.ResolveBaseURL(cfg.AppString(provider.ConfigKey("base_url"), ""))
	if providerID == "ollama" {
		if apiKey == "" {
			apiKey = "ollama"
		}
		if baseURL == "" {
			baseURL = "http://localhost:11434/v1"
		}
	}
	if provider.RequiresAPIKey && apiKey == "" {
		return "", fmt.Errorf("%s: api_key is not set, please set it in the config.toml file", providerID)
	}
	if provider.RequiresModelName && modelName == "" {
		return "", fmt.Errorf("%s: model_name is not set, please set it in the config.toml file", providerID)
	}
	if provider.RequiresBaseURL && baseURL == "" {
		return "", fmt.Errorf("%s: base_url is not set, please set it in the config.toml file", providerID)
	}
	slog.Info("llm provider", "provider", providerID, "model", modelName)

	endpoint := strings.TrimRight(baseURL, "/") + "/chat/completions"
	body, _ := json.Marshal(chatRequest{
		Model:    modelName,
		Messages: []chatMessage{{Role: "user", Content: prompt}},
	})
	req, err := http.NewRequest(http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	if apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+apiKey)
	}
	client := &http.Client{Timeout: 120 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return "", fmt.Errorf("%s", sanitizeError(err))
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	var parsed chatResponse
	if err := json.Unmarshal(raw, &parsed); err != nil {
		return "", fmt.Errorf("[%s] invalid json: %s", providerID, sanitizeError(err))
	}
	if parsed.Error != nil && parsed.Error.Message != "" {
		return "", fmt.Errorf("[%s] %s", providerID, parsed.Error.Message)
	}
	if len(parsed.Choices) == 0 {
		return "", fmt.Errorf("[%s] returned empty choices", providerID)
	}
	return normalizeLLMText(parsed.Choices[0].Message.Content, providerID)
}

func formatScript(text string) string {
	text = strings.ReplaceAll(text, "*", "")
	text = strings.ReplaceAll(text, "#", "")
	reLink := regexp.MustCompile(`\[.*\]`)
	reParen := regexp.MustCompile(`\(.*\)`)
	text = reLink.ReplaceAllString(text, "")
	text = reParen.ReplaceAllString(text, "")
	return strings.TrimSpace(text)
}

// GenerateScript 根据主题生成视频文案。
func GenerateScript(subject, language string, paragraphs int, extra, system string) (string, error) {
	prompt := BuildScriptPrompt(subject, language, paragraphs, extra, system)
	var last error
	for i := 0; i < maxScriptRetries; i++ {
		text, err := generateLLMResponse(prompt)
		if err != nil {
			last = err
			slog.Warn("failed to generate video script, retrying", "try", i+1, "error", err)
			continue
		}
		return formatScript(text), nil
	}
	if last != nil {
		return "", last
	}
	return "", fmt.Errorf("failed to generate video script")
}

// GenerateTerms 从文案提炼素材搜索关键词。
func GenerateTerms(subject, script string, amount int, matchOrder bool) ([]string, error) {
	if amount < 1 {
		amount = 5
	}
	goal := fmt.Sprintf("Generate %d search terms for stock videos, depending on the subject of a video.", amount)
	ordering := ""
	example := `["search term 1", "search term 2", "search term 3", "search term 4", "search term 5"]`
	if matchOrder {
		goal = fmt.Sprintf("Generate %d chronological stock-video search terms that follow the order of topics in the video script.", amount)
		ordering = "6. keep the terms in the same order as the script narration; earlier terms must describe earlier visual moments."
	}
	prompt := fmt.Sprintf(`# Role: Video Search Terms Generator

## Goals:
%s

## Constrains:
1. the search terms are to be returned as a json-array of strings.
2. each search term should consist of 1-3 words, always add the main subject of the video.
3. you must only return the json-array of strings. you must not return anything else. you must not return the script.
4. the search terms must be related to the subject of the video.
5. reply with english search terms only.
%s

## Output Example:
%s

## Context:
### Video Subject
%s

### Video Script
%s

Please note that you must use English for generating video search terms; Chinese is not accepted.`, goal, ordering, example, subject, script)

	var last error
	for i := 0; i < maxScriptRetries; i++ {
		text, err := generateLLMResponse(prompt)
		if err != nil {
			last = err
			continue
		}
		terms, err := parseTermsJSON(text)
		if err != nil {
			last = err
			continue
		}
		if len(terms) > 0 {
			return terms, nil
		}
	}
	if last != nil {
		return nil, last
	}
	return nil, fmt.Errorf("failed to generate video search terms")
}

func parseTermsJSON(text string) ([]string, error) {
	text = strings.TrimSpace(text)
	text = strings.TrimPrefix(text, "```json")
	text = strings.TrimPrefix(text, "```")
	text = strings.TrimSuffix(text, "```")
	text = strings.TrimSpace(text)
	var terms []string
	if err := json.Unmarshal([]byte(text), &terms); err == nil {
		return terms, nil
	}
	re := regexp.MustCompile(`\[[\s\S]*\]`)
	match := re.FindString(text)
	if match == "" {
		return nil, fmt.Errorf("terms response is not a json array")
	}
	if err := json.Unmarshal([]byte(match), &terms); err != nil {
		return nil, err
	}
	return terms, nil
}

// GenerateSocialMetadata 生成短视频发布标题、简介和标签。
func GenerateSocialMetadata(subject, script, language, platform string) (map[string]any, error) {
	if platform == "" {
		platform = "tiktok"
	}
	if language == "" {
		language = "auto"
	}
	prompt := fmt.Sprintf(`# Role: Short-Video Social Media Copywriter
Return JSON only: {"title":"...","caption":"...","hashtags":["#a","#b"]}
Platform: %s
Language: %s
Subject: %s
Script: %s`, platform, language, subject, script)
	text, err := generateLLMResponse(prompt)
	if err != nil {
		return fallbackSocial(subject, platform), nil
	}
	text = strings.TrimSpace(text)
	text = strings.TrimPrefix(text, "```json")
	text = strings.TrimPrefix(text, "```")
	text = strings.TrimSuffix(text, "```")
	var parsed map[string]any
	if err := json.Unmarshal([]byte(strings.TrimSpace(text)), &parsed); err != nil {
		return fallbackSocial(subject, platform), nil
	}
	return parsed, nil
}

func fallbackSocial(subject, platform string) map[string]any {
	return map[string]any{
		"title":    subject,
		"caption":  subject,
		"hashtags": []string{"#shorts", "#viral", "#fyp"},
		"platform": platform,
	}
}
