// LLM 供应商元数据注册表，对应 Python llm_provider 配置，不发网络请求。
package models

import "strings"

// LLMProviderSpec 对应 Python LLMProviderSpec：只声明供应商元数据，不发请求。
type LLMProviderSpec struct {
	ID                 string
	Label              string
	Adapter            string
	APIKeyURL          string
	DefaultModel       string
	DefaultBaseURL     string
	RequiresAPIKey     bool
	RequiresModelName  bool
	RequiresBaseURL    bool
	DeprecatedModels   []string
	DeprecatedBaseURLs []string
}

// ConfigKey 拼出 config.toml 里该供应商的配置键，例如 moonshot_api_key。
func (p LLMProviderSpec) ConfigKey(suffix string) string {
	return p.ID + "_" + suffix
}

// ResolveModelName 空值或已废弃模型名回退到默认模型。
func (p LLMProviderSpec) ResolveModelName(configured string) string {
	name := strings.TrimSpace(configured)
	if name == "" {
		return p.DefaultModel
	}
	for _, deprecated := range p.DeprecatedModels {
		if name == deprecated {
			return p.DefaultModel
		}
	}
	return name
}

// ResolveBaseURL 空值或已废弃地址回退到默认 Base URL。
func (p LLMProviderSpec) ResolveBaseURL(configured string) string {
	url := strings.TrimSpace(configured)
	if url == "" {
		return p.DefaultBaseURL
	}
	normalized := strings.TrimRight(url, "/")
	for _, deprecated := range p.DeprecatedBaseURLs {
		if strings.TrimRight(deprecated, "/") == normalized {
			return p.DefaultBaseURL
		}
	}
	return url
}

const DefaultLLMProviderID = "moonshot"

// LLMProviderRegistry 顺序与 WebUI 下拉框一致。
var LLMProviderRegistry = []LLMProviderSpec{
	{ID: "moonshot", Label: "Kimi / Moonshot AI", Adapter: "openai_compatible", DefaultModel: "kimi-k3", DefaultBaseURL: "https://api.moonshot.cn/v1", RequiresAPIKey: true, RequiresModelName: true, RequiresBaseURL: true},
	{ID: "openai", Label: "OpenAI", Adapter: "openai_compatible", APIKeyURL: "https://platform.openai.com/api-keys", DefaultModel: "gpt-5.5", DefaultBaseURL: "https://api.openai.com/v1", RequiresAPIKey: true, RequiresModelName: true, RequiresBaseURL: true},
	{ID: "anthropic", Label: "Anthropic Claude", Adapter: "openai_compatible", DefaultModel: "claude-sonnet-5", DefaultBaseURL: "https://api.anthropic.com/v1/", RequiresAPIKey: true, RequiresModelName: true, RequiresBaseURL: true},
	{ID: "gemini", Label: "Google Gemini", Adapter: "gemini", APIKeyURL: "https://aistudio.google.com/app/apikey", DefaultModel: "gemini-3.1-pro-preview", RequiresAPIKey: true, RequiresModelName: true, DeprecatedModels: []string{"gemini-pro", "gemini-1.0-pro"}},
	{ID: "deepseek", Label: "DeepSeek", Adapter: "openai_compatible", DefaultModel: "deepseek-v4-pro", DefaultBaseURL: "https://api.deepseek.com", RequiresAPIKey: true, RequiresModelName: true, RequiresBaseURL: true},
	{ID: "qwen", Label: "Alibaba Cloud Qwen", Adapter: "qwen", DefaultModel: "qwen-max", RequiresAPIKey: true, RequiresModelName: true},
	{ID: "azure", Label: "Microsoft Azure OpenAI", Adapter: "azure", DefaultModel: "gpt-35-turbo", RequiresAPIKey: true, RequiresModelName: true},
	{ID: "volcengine", Label: "ByteDance VolcEngine Ark", Adapter: "openai_compatible", DefaultModel: "doubao-seed-2-1-turbo-260628", DefaultBaseURL: "https://ark.cn-beijing.volces.com/api/v3", RequiresAPIKey: true, RequiresModelName: true, RequiresBaseURL: true},
	{ID: "grok", Label: "xAI Grok", Adapter: "openai_compatible", DefaultModel: "grok-4.3", DefaultBaseURL: "https://api.x.ai/v1", RequiresAPIKey: true, RequiresModelName: true, RequiresBaseURL: true},
	{ID: "minimax", Label: "MiniMax", Adapter: "openai_compatible", DefaultModel: "MiniMax-M3", DefaultBaseURL: "https://api.minimax.io/v1", RequiresAPIKey: true, RequiresModelName: true, RequiresBaseURL: true},
	{ID: "mimo", Label: "Xiaomi MiMo", Adapter: "openai_compatible", DefaultModel: "mimo-v2.5-pro", DefaultBaseURL: "https://api.xiaomimimo.com/v1", RequiresAPIKey: true, RequiresModelName: true, RequiresBaseURL: true},
	{ID: "ollama", Label: "Ollama", Adapter: "openai_compatible", RequiresModelName: true, DefaultBaseURL: "http://localhost:11434/v1"},
	{ID: "oneapi", Label: "OneAPI", Adapter: "openai_compatible", RequiresAPIKey: true, RequiresModelName: true, RequiresBaseURL: true},
	{ID: "groq", Label: "Groq", Adapter: "openai_compatible", DefaultModel: "llama-3.3-70b-versatile", DefaultBaseURL: "https://api.groq.com/openai/v1", RequiresAPIKey: true, RequiresModelName: true, RequiresBaseURL: true},
}

var llmProviders = func() map[string]LLMProviderSpec {
	out := make(map[string]LLMProviderSpec, len(LLMProviderRegistry))
	for _, p := range LLMProviderRegistry {
		out[p.ID] = p
	}
	return out
}()

// GetLLMProvider 按 ID 查找供应商；未知 ID 返回 false。
func GetLLMProvider(id string) (LLMProviderSpec, bool) {
	p, ok := llmProviders[strings.ToLower(strings.TrimSpace(id))]
	return p, ok
}
