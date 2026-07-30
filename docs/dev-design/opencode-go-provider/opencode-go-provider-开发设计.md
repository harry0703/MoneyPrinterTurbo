# 开发设计文档：OpenCode Go Provider

> **版本号**：1.0  
> **编写日期**：2026-07-29  
> **需求来源**：用户增量需求  
> **适用范围**：MoneyPrinterTurbo `main` / v1.3.3

## 1. 需求概述与设计目标

### 1.1 功能清单

| 序号 | 功能 | 说明 |
|---|---|---|
| 1 | OpenCode Go Provider | 在 WebUI 大模型提供商中增加独立的 OpenCode Go 选项 |
| 2 | 配置与连接测试 | 支持 API Key、模型名及连接测试 |
| 3 | 视频生成链路 | 支持文案和素材关键词生成 |
| 4 | 文档与测试 | 补充中英文说明、示例配置、单元测试和可选真实接口测试 |
| 5 | Fork、构建与部署 | 推送到用户 Fork，构建独立镜像并重新部署到 `192.168.5.90` |

### 1.2 关键约束

- 首版仅支持 OpenCode Go 官方标注为 `POST /chat/completions` 的模型，不宣称支持走 `POST /messages` 的 MiniMax、Qwen 等模型。
- 直接 API 请求使用原始模型 ID，如 `mimo-v2.5`，不使用 OpenCode 客户端中的 `opencode-go/mimo-v2.5` 格式。
- API Key 不进入源码、提交记录、镜像、Compose 文件或普通测试夹具。
- 不破坏现有 Provider 的配置、默认值、排序和生成链路。

### 1.3 设计目标

- 复用现有 OpenAI-compatible 适配器，减少协议分支和维护成本。
- 默认配置开箱可用，用户只需填写 API Key。
- 页面连接测试、脚本生成和关键词生成均通过真实端到端验证。
- 自定义镜像与服务器实际运行代码一致，不再依赖宿主源码覆盖镜像。

## 2. 系统上下文与架构影响

### 2.1 系统上下文

```text
[WebUI Provider 设置]
          |
          v
[LLM Provider Registry] ---> [OpenAI-compatible Adapter]
                                      |
                                      v
                    [OpenCode Go /zen/go/v1/chat/completions]
```

### 2.2 影响范围

| 模块 | 影响类型 | 说明 |
|---|---|---|
| Provider Registry | 扩展 | 新增稳定 ID `opencode_go` 及默认元数据 |
| WebUI | 自动复用 | 下拉、密码框、模型输入、连接测试由 Registry 驱动 |
| LLM 服务 | 复用 | 复用现有 OpenAI-compatible 请求与响应解析 |
| 示例配置 | 扩展 | 新增三项空覆盖字段 |
| i18n | 扩展 | 中文、英文增加标签和提示 |
| README | 扩展 | 记录支持范围及模型 ID 规则 |
| 测试 | 扩展 | Registry、配置、请求参数、异常和集成测试 |
| Docker 部署 | 调整 | 构建自定义镜像并避免宿主源码覆盖镜像代码 |

### 2.3 复用与新增

- **直接复用**：Provider 通用表单、配置持久化、连接测试、OpenAI SDK 客户端、响应正文提取、错误清洗、脚本及关键词生成。
- **新增**：Registry 条目、配置键、中英文提示、README 说明及 Provider 专项测试。
- **不新增**：数据库、HTTP API、独立网络客户端、独立页面或状态存储。

## 3. 外部接口契约

| 用途 | 方法与地址 | 鉴权 | 数据格式 |
|---|---|---|---|
| 模型列表验证 | `GET https://opencode.ai/zen/go/v1/models` | Bearer Key | JSON |
| 文本生成 | `POST https://opencode.ai/zen/go/v1/chat/completions` | Bearer Key | OpenAI Chat Completions JSON |

Provider 默认值：

| 项目 | 值 |
|---|---|
| Provider ID | `opencode_go` |
| 默认 Base URL | `https://opencode.ai/zen/go/v1` |
| 默认模型 | `mimo-v2.5` |
| 配置键 | `opencode_go_api_key`、`opencode_go_base_url`、`opencode_go_model_name` |

选择 `mimo-v2.5` 的理由：官方明确标注为 Chat Completions 协议，额度充足，且已用真实密钥验证能返回最终正文。Base URL 只配置到 `/v1`，由 OpenAI SDK追加 `/chat/completions`。

## 4. 核心流程

```text
用户选择 OpenCode Go
    -> 填写 API Key
    -> 使用默认或自定义 Chat Completions 模型
    -> 点击连接测试
    -> Registry 解析配置
    -> OpenAI-compatible Adapter 发起最小请求
    -> 提取 message.content
    -> 成功时显示模型与耗时；失败时显示清洗后的诊断信息
```

生成视频时沿用同一调用链。若上游只返回 `reasoning_content` 而最终 `content` 为空，应明确报错，不把推理内容当作文案或字幕。

## 5. WebUI 与国际化设计

- Provider 放在“聚合与统一接入平台”分组。
- API Key 使用现有密码输入框。
- Base URL 使用 Registry 默认值；首版保留高级用户覆盖能力，但提示只填写到 `/v1`。
- 模型继续使用可编辑文本输入框。首版不动态展示 `/models` 的全部结果，因为该列表混合 Chat Completions 与 Messages 协议，盲目展示会允许用户选到当前适配器无法调用的模型。
- 中文、英文提供完整提示；其它语言按项目现有机制回退英文。
- 提示明确说明订阅要求、原始模型 ID 格式和额度限制。

## 6. 安全、兼容性与可观测性

### 6.1 安全

- 真实密钥只通过运行时环境变量执行集成测试，默认跳过。
- 服务器 `config.toml` 权限收紧为仅 root 可读写。
- 错误返回继续清理 URL 凭据和查询参数；增加对当前 API Key 字面值的脱敏保护。
- 用户提供的测试密钥已出现在会话中，交付后建议立即轮换。

### 6.2 兼容性

- 不修改现有 Provider ID 和配置语义。
- Registry 默认值不写死到用户配置；用户未覆盖时可随版本升级。
- 首版只支持官方 Chat Completions 模型；Messages 协议作为后续独立能力。

### 6.3 可观测性

- 沿用现有 Provider、模型、连接耗时日志。
- 日志不记录 API Key、Authorization Header 或完整敏感错误体。
- 401/403、429、无效模型、空正文需保留可诊断但已脱敏的信息。

## 7. 关键技术决策

| 决策点 | 选择 | 备选方案 | 理由 |
|---|---|---|---|
| 接入方式 | 复用 OpenAI-compatible adapter | 新建专用 adapter | 当前目标模型使用标准 Chat Completions，无需重复实现 |
| 默认模型 | `mimo-v2.5` | `kimi-k3`、`deepseek-v4-flash` | 已真实验证最终正文，成本和额度友好 |
| 模型选择 | 可编辑文本输入 | 动态下拉全部模型 | `/models` 不含协议类型，全部展示会产生不可调用选项 |
| Messages 模型 | 首版不支持 | 同时实现 Anthropic adapter | 避免扩大范围和双协议风险 |
| 部署 | 自定义版本镜像 | 继续使用官方 latest + 源码目录挂载 | 保证构建产物就是服务器实际运行代码 |

## 8. 修改清单

| 文件 | 修改说明 |
|---|---|
| `app/models/llm_provider.py` | 新增 `opencode_go` Registry 条目 |
| `config.example.toml` | 新增三项空配置 |
| `webui/i18n/zh.json` | 新增中文标签与提示 |
| `webui/i18n/en.json` | 新增英文标签与提示 |
| `README.md` | 增加 OpenCode Go 支持说明 |
| `README-en.md` | 增加英文支持说明 |
| `test/services/test_llm.py` | Registry、默认值、请求、响应和异常测试 |
| `test/services/test_config.py` | 验证示例配置覆盖 Provider |
| Docker/Compose 部署配置 | 使用自定义镜像标签，保留配置与 storage 持久化且支持原子保存 |

不需要修改：

- `webui/Main.py`：现有 UI 完全由 Registry 驱动。
- `app/services/llm.py` 的主请求分支：复用现有 OpenAI-compatible fallback；仅在必要时增强密钥脱敏错误处理。
- API Controller 和数据模型：没有新增对外 API。
- 数据库：无数据结构变化。

## 9. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| Go 模型列表持续变化 | 硬编码列表过期 | 默认模型由 Registry 管理，允许手工覆盖 |
| 选到 `/messages` 模型 | 请求失败 | 文档明确首版支持范围，不展示混合动态列表 |
| 推理模型先消耗 reasoning token | 极小输出额度时正文为空 | 连接测试和真实验收使用足够输出额度；空正文明确报错 |
| 密钥明文保存在全局 TOML | 主机用户可能读取 | 文件权限 600、只允许 root、密钥不进入仓库 |
| Compose 源码覆盖镜像 | 打包结果未真正运行 | 改为配置目录持久化方案并验证容器镜像代码版本 |
| Fork 缺少 GitHub 写权限 | 无法创建远程 Fork | 用户连接 GitHub 或提供已认证的 GitHub 环境后执行 |

## 10. 验证策略与验收标准

1. 单元测试覆盖 Provider 唯一性、顺序、默认值、示例配置及多语言提示。
2. Mock OpenAI 客户端验证 Base URL、模型 ID、API Key 和消息结构。
3. 覆盖缺 Key、错误 Key、错误 Base URL、无效模型、429、空 choices、空 content 和密钥脱敏。
4. 真实测试仅在显式启用且从环境变量读取密钥时运行。
5. 构建自定义镜像，部署到 `192.168.5.90`，验证容器使用目标提交。
6. WebUI 连接测试、脚本生成、关键词生成均成功。
7. WebUI 与 API 返回 HTTP 200，现有 Provider 回归测试通过。

## 11. 已完成的接口预验证

- `GET /zen/go/v1/models`：HTTP 200。
- `POST /zen/go/v1/chat/completions`，模型 `mimo-v2.5`：HTTP 200。
- 正常输出额度下最终正文为 `OK`；响应同时包含 reasoning token，现有代码只使用最终 `content`，符合视频文案安全要求。

## 文档版本控制

| 版本 | 日期 | 作者 | 修改说明 |
|---|---|---|---|
| 1.0 | 2026-07-29 | Codex | 初始方案 |
