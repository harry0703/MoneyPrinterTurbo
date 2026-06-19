# Coiner Docker 镜像规范

本文档详细描述 Coiner 项目的 Docker 镜像构建方案、容器启动模式以及 GPU 支持实现。

## 目录

- [1. 镜像构建方案](#1-镜像构建方案)
  - [1.1 基础镜像选择](#11-基础镜像选择)
  - [1.2 构建过程](#12-构建过程)
  - [1.3 构建脚本](#13-构建脚本)

- [2. 容器启动模式](#2-容器启动模式)
  - [2.1 GPU 模式](#21-gpu-模式)
  - [2.2 CPU 模式](#22-cpu-模式)
  - [2.3 启动脚本](#23-启动脚本)

- [3. GPU 支持实现](#3-gpu-支持实现)
  - [3.1 前提条件](#31-前提条件)
  - [3.2 配置方法](#32-配置方法)
  - [3.3 故障排除](#33-故障排除)

- [4. 配置文件说明](#4-配置文件说明)
  - [4.1 docker-compose.yml](#41-docker-composeyml)
  - [4.2 docker-compose.cpu.yml](#42-docker-composecpuyml)
  - [4.3 环境变量](#43-环境变量)

- [5. 使用方法](#5-使用方法)
  - [5.1 构建镜像](#51-构建镜像)
  - [5.2 启动容器](#52-启动容器)
  - [5.3 访问应用](#53-访问应用)

- [6. 注意事项](#6-注意事项)

- [7. 常见问题](#7-常见问题)

## 1. 镜像构建方案

### 1.1 基础镜像选择

| 镜像名称 | 版本 | 特点 | 用途 |
|---------|------|------|------|
| `nvidia/cuda` | `11.8.0-runtime-ubuntu22.04` | 包含 CUDA 11.8 运行时，基于 Ubuntu 22.04 | 支持 GPU 加速 |

**选择理由**：
- 提供 CUDA 11.8 运行时，支持 PyTorch 等深度学习库
- 基于 Ubuntu 22.04，稳定性好
- 包含必要的 NVIDIA 运行时组件

### 1.2 构建过程

采用多阶段构建策略：

1. **构建阶段**：安装依赖和编译代码
2. **运行阶段**：仅包含运行时需要的文件

**关键步骤**：
- 安装系统依赖（git、imagemagick、ffmpeg 等）
- 安装 Python 依赖（从 requirements.txt）
- 复制应用代码到容器
- 配置环境变量和权限

### 1.3 构建脚本

**构建脚本**：`build-docker.bat`

**设计原理**：
- **单命令检测**：使用 `docker version` 命令同时检查 Docker 安装和 daemon 状态
  - `docker version` 需要与 daemon 通信，因此可以同时检测安装和运行状态
  - 如果 Docker 未安装或 daemon 未运行，命令都会失败
  - 避免了使用多个命令的冗余（如 `docker --version` + `docker version`）
- **简洁高效**：只执行一个检测命令，减少不必要的命令执行
- **清晰反馈**：提供详细的错误提示和故障排除步骤

**功能**：
- 检查 Docker 安装和 daemon 状态（使用 `docker version`）
- 预下载基础镜像（提高构建速度）
- 执行 Docker 构建命令
- 显示构建结果和使用说明

**使用方法**：
```bash
# 运行构建脚本
build-docker.bat
```

## 2. 容器启动模式

### 2.1 GPU 模式

**适用场景**：
- 有 NVIDIA GPU 硬件
- 已安装 NVIDIA 驱动
- 已安装 NVIDIA Container Toolkit

**配置文件**：`docker-compose.yml`

**特点**：
- 启用 GPU 设备访问
- 设置 CUDA 环境变量
- 应用自动使用 GPU 加速

### 2.2 CPU 模式

**适用场景**：
- 无 GPU 硬件
- 不想使用 GPU
- GPU 驱动或 Container Toolkit 未安装

**配置文件**：`docker-compose.cpu.yml`

**特点**：
- 禁用 CUDA 访问
- 应用自动降级到 CPU 模式
- 确保在无 GPU 环境下正常运行

### 2.3 启动脚本

**启动脚本**：`start-docker.bat`（CMD）和 `start-docker.ps1`（PowerShell）

**设计原理**：
- **单命令检测**：使用 `docker version` 命令同时检查 Docker 安装和 daemon 状态
  - 与构建脚本保持一致的设计理念
  - 避免使用多个命令的冗余检测
- **参数化配置**：通过命令行参数控制 GPU/CPU 模式
  - 默认启用 GPU 模式
  - 支持显式指定 `--gpu` 或 `--cpu` 参数
  - 提供清晰的错误提示和用法说明

**功能**：
- 解析命令行参数（--cpu/--gpu）
- 检查 Docker 安装和 daemon 状态（使用 `docker version`）
- 检查模型目录
- 启动容器
- 显示访问信息

**参数支持**：

| 参数 | 模式 | 说明 |
|------|------|------|
| 无参数 | GPU 模式 | 默认启用 GPU 加速 |
| `--gpu` | GPU 模式 | 显式启用 GPU 加速 |
| `--cpu` | CPU 模式 | 强制使用 CPU 模式 |

**使用方法**：
```bash
# 默认 GPU 模式
start-docker.bat

# 显式 GPU 模式
start-docker.bat --gpu

# CPU 模式
start-docker.bat --cpu
```

## 3. GPU 支持实现

### 3.1 前提条件

**硬件要求**：
- NVIDIA GPU（支持 CUDA 11.8 或更高版本）

**软件要求**：
1. **NVIDIA GPU 驱动**：与 GPU 型号匹配的驱动
   - 下载地址：https://www.nvidia.com/drivers

2. **NVIDIA Container Toolkit**：
   - 安装指南：https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html

### 3.2 配置方法

**Docker Compose 配置**：
```yaml
environment:
  - NVIDIA_VISIBLE_DEVICES=all
  - NVIDIA_DRIVER_CAPABILITIES=compute,utility
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all
          capabilities: [gpu]
```

**验证安装**：
```bash
# 检查 NVIDIA 驱动
nvidia-smi

# 检查 NVIDIA Container Toolkit
docker info --format '{{.Driver}}' | findstr nvidia
```

### 3.3 故障排除

| 错误信息 | 可能原因 | 解决方案 |
|---------|---------|---------|
| `CUDA driver version is insufficient` | 驱动版本低于 CUDA 要求 | 更新 NVIDIA 驱动 |
| `nvidia-container-runtime` 未找到 | Container Toolkit 未安装 | 安装 NVIDIA Container Toolkit |
| `no NVIDIA GPU detected` | 无 GPU 或驱动未加载 | 检查 GPU 硬件和驱动 |

## 4. 配置文件说明

### 4.1 docker-compose.yml

**用途**：GPU 模式配置

**主要配置**：
- 容器名称：`coiner-api`
- 端口映射：`8080:8080`（API + WebUI）
- 卷挂载：项目目录、模型目录、配置文件、存储目录
- GPU 设备配置
- 环境变量设置

### 4.2 docker-compose.cpu.yml

**用途**：CPU 模式配置

**主要配置**：
- 与 GPU 模式相同，但移除了 GPU 设备配置
- 添加 `CUDA_VISIBLE_DEVICES=""` 环境变量

### 4.3 环境变量

| 环境变量 | 作用 | 默认值 |
|---------|------|-------|
| `PYTHONUNBUFFERED` | 确保 Python 输出实时显示 | `1` |
| `NVIDIA_VISIBLE_DEVICES` | 控制 GPU 可见性 | `all` |
| `NVIDIA_DRIVER_CAPABILITIES` | 控制 GPU 功能 | `compute,utility` |
| `CUDA_VISIBLE_DEVICES` | 控制 CUDA 设备访问 | `""`（CPU 模式） |

## 5. 使用方法

### 5.1 构建镜像

**步骤**：
1. 确保 Docker Desktop 已启动
2. 运行构建脚本：`build-docker.bat`
3. 等待构建完成（首次构建可能需要较长时间）

**构建成功**：
- 显示镜像详细信息
- 提示如何启动容器

### 5.2 启动容器

**GPU 模式**（默认）：
```bash
start-docker.bat
```

**CPU 模式**：
```bash
start-docker.bat --cpu
```

**启动成功**：
- 显示容器状态
- 显示访问地址
- 显示 GPU/CPU 模式信息

### 5.3 访问应用

**WebUI / API**：
- 地址：http://localhost:8080
- 功能：Vue 图形化界面 + FastAPI REST API，用于创建和管理任务

**API**：
- 地址：http://localhost:8080
- API 文档：http://localhost:8080/docs
- 功能：编程接口，用于自动化操作

## 6. 注意事项

1. **镜像体积**：CUDA 镜像体积较大（约 2-3GB），首次下载需要较长时间

2. **网络要求**：
   - 构建过程需要下载依赖和基础镜像
   - 建议配置 Docker 镜像加速（阿里云、清华大学等）

3. **磁盘空间**：
   - 确保有足够的磁盘空间用于镜像和容器
   - 定期清理未使用的镜像和容器

4. **端口占用**：
   - 确保端口 8080（API + WebUI）未被占用
   - 如有冲突，修改 docker-compose.yml 中的端口映射

5. **模型存储**：
   - Whisper 模型存储在 `models` 目录
   - 首次使用会自动下载模型（需要网络连接）

## 7. 常见问题

### Q: 构建过程卡住或失败
**A**: 检查网络连接，配置 Docker 镜像加速，确保 Docker 守护进程正常运行

### Q: 启动容器失败
**A**: 检查端口是否被占用，检查 Docker Desktop 状态，查看容器日志

### Q: GPU 模式下应用仍使用 CPU
**A**: 检查 NVIDIA 驱动和 Container Toolkit 是否正确安装，运行 `nvidia-smi` 验证

### Q: 无 GPU 时容器无法启动
**A**: 使用 `--cpu` 参数启动容器，强制使用 CPU 模式

### Q: 模型下载失败
**A**: 检查网络连接，手动下载模型并放入 `models` 目录

### Q: 应用运行缓慢
**A**: 对于 CPU 模式，Whisper 模型运行会较慢，建议在有 GPU 的环境中运行

---

**最后更新**：2026-03-29
**版本**：v1.0.0
