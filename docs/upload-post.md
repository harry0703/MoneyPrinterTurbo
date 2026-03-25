# Upload-Post Integration / Upload-Post 集成

[English](#english) | [中文](#中文)

## English

### Overview

Upload-Post integration allows you to automatically cross-post generated videos to TikTok and Instagram.

### What is Upload-Post?

[Upload-Post](https://upload-post.com) is an API service that allows you to upload videos to multiple social media platforms with a single API call.

- **Website:** https://upload-post.com
- **API Docs:** https://docs.upload-post.com
- **Free tier available**

### Setup

1. Create an account at [upload-post.com](https://upload-post.com)
2. Connect your TikTok and/or Instagram accounts in the dashboard
3. Get your API key from the dashboard
4. Add the following to your `config.toml`:

```toml
upload_post_enabled = true
upload_post_api_key = "your-api-key"
upload_post_username = "your-username"
upload_post_platforms = ["tiktok", "instagram"]
upload_post_auto_upload = true
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `upload_post_enabled` | bool | `false` | Enable/disable Upload-Post integration |
| `upload_post_api_key` | string | `""` | Your Upload-Post API key |
| `upload_post_username` | string | `""` | Your Upload-Post username |
| `upload_post_platforms` | array | `["tiktok", "instagram"]` | Platforms to cross-post to |
| `upload_post_auto_upload` | bool | `false` | Automatically cross-post after video generation |

### Usage

When `upload_post_auto_upload` is set to `true`, videos will be automatically cross-posted to the configured platforms after generation.

The cross-posting results will be included in the task response under `cross_post_results`.

---

## 中文

### 概述

Upload-Post 集成允许您自动将生成的视频发布到 TikTok 和 Instagram。

### 什么是 Upload-Post？

[Upload-Post](https://upload-post.com) 是一个 API 服务，允许您通过单个 API 调用将视频上传到多个社交媒体平台。

- **网站：** https://upload-post.com
- **API 文档：** https://docs.upload-post.com
- **提供免费套餐**

### 设置

1. 在 [upload-post.com](https://upload-post.com) 创建账户
2. 在控制面板中连接您的 TikTok 和/或 Instagram 账户
3. 从控制面板获取您的 API 密钥
4. 将以下内容添加到您的 `config.toml`：

```toml
upload_post_enabled = true
upload_post_api_key = "your-api-key"
upload_post_username = "your-username"
upload_post_platforms = ["tiktok", "instagram"]
upload_post_auto_upload = true
```

### 配置选项

| 选项 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `upload_post_enabled` | bool | `false` | 启用/禁用 Upload-Post 集成 |
| `upload_post_api_key` | string | `""` | 您的 Upload-Post API 密钥 |
| `upload_post_username` | string | `""` | 您的 Upload-Post 用户名 |
| `upload_post_platforms` | array | `["tiktok", "instagram"]` | 要发布的平台 |
| `upload_post_auto_upload` | bool | `false` | 视频生成后自动发布 |

### 使用方法

当 `upload_post_auto_upload` 设置为 `true` 时，视频在生成后将自动发布到配置的平台。

发布结果将包含在任务响应的 `cross_post_results` 字段中。
