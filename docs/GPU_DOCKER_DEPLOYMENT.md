# GPU Docker Deployment Guide

本文档介绍如何将 MoneyPrinterTurbo 的 Docker 部署改造为 GPU 加速模式，使 `faster-whisper` 在 GPU 上运行，大幅提升字幕生成速度。

## 为什么要 GPU 加速

MoneyPrinterTurbo 中唯一的深度学习环节是 **faster-whisper 语音识别**（将生成的音频转为带时间戳的字幕）。

- **CPU 模式**（默认）：`large-v3` 模型生成字幕较慢，受限于 CPU 算力
- **GPU 模式**：利用 NVIDIA GPU + CUDA 加速，字幕生成速度提升 **5-10 倍**

> 注意：项目的其他环节（脚本生成、音频合成、视频剪辑）不涉及深度学习，GPU 只加速字幕生成。

## 前提条件

### 1. 硬件要求

- NVIDIA GPU（建议 6GB 以上显存）
- `large-v3` 模型在 GPU 上 `float16` 精度约占用 1.5GB 显存

### 2. 软件要求

- **NVIDIA 驱动**：最新版即可（可在 PowerShell 中运行 `nvidia-smi` 确认）
- **Docker Desktop**：确保已安装
- **NVIDIA Container Toolkit**：Docker 中需要 `nvidia` runtime（运行 `docker info` 查看 Runtimes 列表中是否有 `nvidia`）

### 3. 环境验证

```bash
# 确认 NVIDIA 驱动正常
nvidia-smi

# 确认 Docker 支持 GPU
docker info | findstr nvidia
```

如果 `docker info` 中没有看到 `nvidia` runtime，需要先安装 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)。

## 修改内容

本次改造涉及 **3 个文件**：

### 1. Dockerfile

将基础镜像从纯 CPU 的 Python 镜像替换为带 CUDA 运行时的 NVIDIA 镜像，并安装 Python 3.11。

**核心变更：**

```dockerfile
# 原来：纯 CPU 镜像
FROM python:3.11-slim-bullseye

# 改为：带 CUDA 12.1 + cuDNN 8 的运行时镜像
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04
```

主要改动点：
- 基础镜像切换为 `nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04`
- 新增安装 Python 3.11（CUDA 镜像基于 Ubuntu 22.04，自带 Python 3.10 但项目需要 3.11）
- 通过 `add-apt-repository ppa:deadsnakes/ppa` 安装 Python 3.11
- 移除系统自带的 `python3-blinker` 包（避免 pip 安装冲突）
- 使用 `python3 -m pip` 代替 `pip` 命令

### 2. docker-compose.yml

为 `api` 服务挂载 GPU 设备。

**核心变更：**

```yaml
services:
  api:
    # ... 其他配置不变 ...
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

> `webui` 服务是纯前端（Streamlit），不需要 GPU，保持不变。

### 3. config.toml

配置 Whisper 使用 GPU 模式。

**核心变更：**

```toml
subtitle_provider = "whisper"   # 启用 whisper（原来可能是 edge）

[whisper]
model_size = "large-v3"
device = "cuda"                 # 原来是 "cpu"
compute_type = "float16"        # 原来是 "int8"，GPU 上 float16 更快更准
```

## 部署步骤

### 第 1 步：拉取 CUDA 基础镜像

```bash
docker pull nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04
```

> 如果使用了阿里云等镜像加速源，可能对 `nvidia/cuda` 系列镜像返回 403。请确保能从 Docker Hub 直接拉取，或配置支持 NVIDIA 镜像的加速源。

### 第 2 步：修改配置文件

按上文说明修改 `Dockerfile`、`docker-compose.yml` 和 `config.toml` 三个文件。

### 第 3 步：构建镜像

```bash
docker compose build --no-cache
```

### 第 4 步：启动服务

```bash
docker compose up -d
```

### 第 5 步：验证 GPU 是否生效

进入 api 容器，确认 GPU 可见：

```bash
docker exec -it moneyprinterturbo-api nvidia-smi
```

如果能看到 GPU 信息，说明 GPU 挂载成功。

## 显存与并发建议

| GPU 显存 | 建议最大并发任务数 |
|---|---|
| 4GB | 1-2 |
| 6GB | 2-3 |
| 8GB | 3-4 |
| 12GB+ | 5 |

可通过 `config.toml` 中的 `max_concurrent_tasks` 控制并发数。

## 故障排查

### 问题 1：镜像拉取失败（403 Forbidden）

阿里云镜像加速对 `nvidia/cuda` 返回 403。解决方法：
- 配置其他可用的镜像加速源
- 或直接 `docker pull nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04` 从 Docker Hub 拉取

### 问题 2：pip 安装报 `no such option: --break-system-packages`

旧版 pip 不支持此参数。解决方法：
- 使用 `python3 -m pip install` 代替 `pip install`
- 或在安装 Python 后先升级 pip：`python3.11 -m pip install --upgrade pip`

### 问题 3：pip 安装报 `Cannot uninstall blinker`

Ubuntu 22.04 系统自带的 `blinker` 包通过 `distutils` 安装，pip 无法卸载。解决方法：
- 在安装 Python 依赖前先 `apt-get remove -y python3-blinker`

### 问题 4：容器内 `nvidia-smi` 找不到 GPU

- 确认宿主机已安装 NVIDIA Container Toolkit
- 确认 `docker info` 中 Runtimes 包含 `nvidia`
- 确认 `docker-compose.yml` 中已添加 `deploy.resources.reservations.devices` 配置

### 问题 5：Whisper 报 CUDA 错误

- 确认 `config.toml` 中 `device = "cuda"`（注意不是 `"CPU"`，大小写敏感）
- 确认 `compute_type = "float16"`（GPU 推荐值）
- 确认 `subtitle_provider = "whisper"`（不是 `"edge"`）
