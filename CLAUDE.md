# MoneyPrinterTurbo 项目上下文

## 项目简介
MoneyPrinterTurbo 是一个 AI 自动生成短视频的工具，输入主题或文案后自动完成：文案生成 → 语音合成 → 字幕生成 → 视频素材搜索 → 视频合成。

## 仓库所有者
- GitHub: baohua01 (chianbaohua@gmail.com)
- 工作分支: `claude/cleanup-auto-save-h77am7`（当前功能开发分支）
- 远端: origin → git@github.com:baohua01/moneyprinterturbo.git

## 项目结构
```
MoneyPrinterTurbo/
├── app/
│   ├── config/config.py       # 配置加载（读取 config.toml）
│   ├── controllers/           # API 控制器（v1/ 下是 REST 接口）
│   ├── models/                # 数据模型（schema.py）
│   ├── services/              # 核心业务：视频/语音/字幕/素材/LLM
│   └── utils/                 # 工具函数
├── resource/
│   ├── fonts/                 # 字幕字体（中文：微软雅黑/苹方）
│   ├── songs/                 # 背景音乐（output000-029.mp3，约55MB）
│   └── public/index.html      # WebUI 入口
├── webui/                     # 前端 WebUI（Streamlit）
├── config.example.toml        # 配置模板（不要提交 config.toml，含密钥）
├── main.py                    # 启动入口
├── cli.py                     # CLI 命令行接口
└── storage/                   # 生成的视频输出目录（gitignored）
```

## 当前工作目标
- 本次分支 `claude/cleanup-auto-save-h77am7` 的目标：清理项目、设置自动保存机制和会话上下文持久化。
- 已完成：
  - 从 `.gitignore` 中移除 `CLAUDE.md`，使其持久化到 git
  - 创建本 `CLAUDE.md` 文件（每次会话自动读取）
  - 配置 `.claude/settings.json` 自动保存 hook

## 重要规则
- **不要提交 `config.toml`**（含 API key，已在 .gitignore 中）
- **不要提交 `storage/` 目录**（生成的视频文件）
- 所有开发在分支 `claude/cleanup-auto-save-h77am7` 上进行，完成后推送

## 自动保存说明
`.claude/settings.json` 中配置了 `Stop` hook：每次 Claude 会话结束时，自动将未提交的修改 commit 并 push 到当前分支，确保工作不丢失。

## 常用命令
```bash
# 启动 WebUI
python main.py

# 启动 API 服务
python -m uvicorn app.asgi:app --host 0.0.0.0 --port 8080

# 查看当前分支状态
git status && git log --oneline -5
```

## LLM 支持的提供商
openai / aihubmix / moonshot / azure / qwen / deepseek / gemini / ollama / oneapi 等。配置在 `config.toml` 的 `[app]` 段 `llm_provider` 字段。
