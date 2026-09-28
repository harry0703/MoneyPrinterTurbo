# MoneyPrinterTurbo 工作约定

## 上下文

- 本仓库在 Independent-Media 中负责从主题、脚本、素材、字幕和 TTS 生成视频。
- 开始行为变更前读取 `../AGENTS.md`；跨仓库目标与契约以 `../docs/自媒体自动化工作流实施方案.md` 为准。
- 需要变更产物时写入 `../docs/changes/<change-id>/`。

## 入口与边界

- API 服务入口：`main.py`；CLI 入口：`cli.py`；WebUI 位于 `webui/`；业务逻辑位于 `app/`。
- Python 版本基线为 3.11+，依赖和开发工具以 `pyproject.toml`、`uv.lock` 为准。
- 配置沿用 `config.example.toml` / 项目现有配置加载方式；不得硬编码 Provider URL、API Key 或机器路径。
- 跨项目集成只使用公开入口和版本化文件/接口，不直接耦合其他子仓库的私有实现。

## 实施与验证

- 先检查 `test/` 的相邻测试；行为变化需要回归保护。
- 相关最小测试：`uv run python -X utf8 -m pytest -q <target>`。
- 完整测试：`uv run python -X utf8 -m pytest -q test`。
- Lint：`uv run ruff check .`。
- 完整覆盖率门禁：`uv run python -X utf8 -m coverage run -m pytest -q test`，再运行 `uv run python -m coverage report`；当前配置底线为 70% 分支覆盖率。
- WebUI 变化除自动检查外还需真实浏览器验证；外部模型、TTS、素材或 FFmpeg 不可用时披露验证盲区。

## 安全

- 不读取或提交 `config.toml`、密钥、用户素材、生成媒体、缓存和日志。
- 不因测试方便调用产生费用的真实 Provider；除非用户明确授权本次调用并接受成本。
- 不把“视频已生成”视为“内容可发布”；发布审批由总控流程处理。
