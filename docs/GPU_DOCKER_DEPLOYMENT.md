# GPU Docker Deployment Guide

本文档介绍如何使用 GPU 加速 `faster-whisper` 字幕生成，大幅提升处理速度。

## 为什么要 GPU 加速

MoneyPrinterTurbo 中唯一的深度学习环节是 **faster-whisper 语音识别**（将音频转为带时间戳的字幕）。

- **CPU 模式**（默认）：`large-v3` 模型生成字幕较慢
- **GPU 模式**：利用 NVIDIA GPU + CUDA 加速，速度提升 **5-10 倍**

> 注意：项目的其他环节（脚本生成、音频合成、视频剪辑）不涉及深度学习，GPU 只加速字幕生成。

## 部署方式

本项目提供两种 Docker 部署方式，**默认 CPU 部署不受任何影响**：

### CPU 部署（默认，零变化）

```bash
docker compose up -d
```

使用原有的 `Dockerfile`（`python:3.11-slim-bullseye`），无需 GPU。

### GPU 部署（有 NVIDIA GPU 的用户）

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

使用 `Dockerfile.gpu`（`nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04`）并为 api 服务挂载 GPU。

## GPU 部署前提条件

### 1. 硬件要求

- NVIDIA GPU（建议 6GB 以上显存）
- `large-v3` 模型在 GPU 上 `float16` 精度约占用 1.5GB 显存

### 2. 软件要求

- **NVIDIA 驱动**：最新版即可，运行 `nvidia-smi` 确认
- **Docker Desktop**
- **NVIDIA Container Toolkit**：运行 `docker info` 查看 Runtimes 列表中是否有 `nvidia`

### 3. 环境验证

```bash
# 确认 NVIDIA 驱动正常
nvidia-smi

# 确认 Docker 支持 GPU（Runtimes 中应包含 nvidia）
docker info | findstr nvidia
```

如果没有 `nvidia` runtime，需要先安装 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)。

## 配置 Whisper 使用 GPU

在 `config.toml` 中设置：

```toml
subtitle_provider = "whisper"

[whisper]
model_size = "large-v3"
device = "cuda"           # 使用 GPU（CPU 用户设为 "cpu"）
compute_type = "float16"  # GPU 推荐 float16（CPU 用户设为 "int8"）
```

## 文件说明

| 文件 | 用途 |
|---|---|
| `Dockerfile` | 默认 CPU 镜像（原有，未修改） |
| `Dockerfile.gpu` | GPU 镜像（新增，基于 NVIDIA CUDA） |
| `docker-compose.yml` | 默认 CPU 部署配置（原有，未修改） |
| `docker-compose.gpu.yml` | GPU 部署覆盖配置（新增） |

## GPU 部署步骤

### 第 1 步：拉取 CUDA 基础镜像

```bash
docker pull nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04
```

> 如果使用了阿里云等镜像加速源，可能对 `nvidia/cuda` 返回 403。请确保能从 Docker Hub 直接拉取。

### 第 2 步：修改 config.toml

按上文说明设置 `subtitle_provider = "whisper"` 和 `device = "cuda"`。

### 第 3 步：构建并启动

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

### 第 4 步：验证 GPU 是否生效

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
- 或直接 `docker pull nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04`

### 问题 2：pip 安装报 `Cannot uninstall blinker`

Ubuntu 22.04 系统自带的 `blinker` 通过 `distutils` 安装，pip 无法卸载。`Dockerfile.gpu` 已通过 `apt-get remove -y python3-blinker` 处理。

### 问题 3：容器内 `nvidia-smi` 找不到 GPU

- 确认宿主机已安装 NVIDIA Container Toolkit
- 确认 `docker info` 中 Runtimes 包含 `nvidia`
- 确认使用了 GPU 部署命令：`docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d`

### 问题 4：Whisper 报 CUDA 错误

- 确认 `config.toml` 中 `device = "cuda"`（大小写敏感，不是 `"CPU"`）
- 确认 `compute_type = "float16"`
- 确认 `subtitle_provider = "whisper"`
