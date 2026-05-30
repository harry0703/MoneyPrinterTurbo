# GPU Docker Deployment Guide

이 문서는 GPU를 사용해 `faster-whisper` 자막 생성을 가속화하여 처리 속도를 크게 높이는 방법을 설명합니다.

## GPU 가속이 필요한 이유

MoneyPrinterTurbo에서 유일한 딥러닝 단계는 **faster-whisper 음성 인식**(오디오를 타임스탬프가 포함된 자막으로 변환)입니다.

- **CPU 모드**(기본): `large-v3` 모델의 자막 생성이 다소 느립니다
- **GPU 모드**: NVIDIA GPU + CUDA 가속을 활용하여 속도가 **5~10배** 향상됩니다

> 참고: 프로젝트의 다른 단계(스크립트 생성, 오디오 합성, 동영상 편집)는 딥러닝과 무관하며, GPU는 자막 생성만 가속화합니다.

## 배포 방식

이 프로젝트는 두 가지 Docker 배포 방식을 제공하며, **기본 CPU 배포는 어떤 영향도 받지 않습니다**:

### CPU 배포(기본, 변경 사항 없음)

```bash
docker compose up -d
```

기존 `Dockerfile`(`python:3.11-slim-bullseye`)을 사용하며, GPU가 필요 없습니다.

### GPU 배포(NVIDIA GPU가 있는 사용자)

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

`Dockerfile.gpu`(`nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04`)를 사용하고 api 서비스에 GPU를 마운트합니다.

## GPU 배포 사전 조건

### 1. 하드웨어 요구사항

- NVIDIA GPU(VRAM 6GB 이상 권장)
- `large-v3` 모델은 GPU에서 `float16` 정밀도로 약 1.5GB의 VRAM을 사용합니다

### 2. 소프트웨어 요구사항

- **NVIDIA 드라이버**: 최신 버전이면 됩니다. `nvidia-smi`를 실행하여 확인하세요
- **Docker Desktop**
- **NVIDIA Container Toolkit**: `docker info`를 실행하여 Runtimes 목록에 `nvidia`가 있는지 확인하세요

### 3. 환경 검증

```bash
# NVIDIA 드라이버가 정상인지 확인
nvidia-smi

# Docker가 GPU를 지원하는지 확인(Runtimes에 nvidia가 포함되어야 함)
docker info | findstr nvidia
```

`nvidia` runtime이 없다면 먼저 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)을 설치해야 합니다.

## Whisper가 GPU를 사용하도록 설정

`config.toml`에 다음을 설정하세요:

```toml
subtitle_provider = "whisper"

[whisper]
model_size = "large-v3"
device = "cuda"           # GPU 사용(CPU 사용자는 "cpu"로 설정)
compute_type = "float16"  # GPU에는 float16 권장(CPU 사용자는 "int8"로 설정)
```

## 파일 설명

| 파일 | 용도 |
|---|---|
| `Dockerfile` | 기본 CPU 이미지(기존, 미수정) |
| `Dockerfile.gpu` | GPU 이미지(신규, NVIDIA CUDA 기반) |
| `docker-compose.yml` | 기본 CPU 배포 설정(기존, 미수정) |
| `docker-compose.gpu.yml` | GPU 배포 오버라이드 설정(신규) |

## GPU 배포 단계

### 1단계: CUDA 베이스 이미지 가져오기

```bash
docker pull nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04
```

> 알리윈 등의 이미지 가속 소스를 사용하면 `nvidia/cuda`에 대해 403을 반환할 수 있습니다. Docker Hub에서 직접 가져올 수 있는지 확인하세요.

### 2단계: config.toml 수정

위 설명에 따라 `subtitle_provider = "whisper"`와 `device = "cuda"`를 설정하세요.

### 3단계: 빌드 및 시작

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

### 4단계: GPU 적용 여부 확인

```bash
docker exec -it moneyprinterturbo-api nvidia-smi
```

GPU 정보가 보이면 GPU 마운트에 성공한 것입니다.

## VRAM 및 동시 처리 권장 사항

| GPU VRAM | 권장 최대 동시 작업 수 |
|---|---|
| 4GB | 1-2 |
| 6GB | 2-3 |
| 8GB | 3-4 |
| 12GB+ | 5 |

`config.toml`의 `max_concurrent_tasks`를 통해 동시 처리 수를 제어할 수 있습니다.

## 문제 해결

### 문제 1: 이미지 가져오기 실패(403 Forbidden)

알리윈 이미지 가속이 `nvidia/cuda`에 대해 403을 반환합니다. 해결 방법:
- 사용 가능한 다른 이미지 가속 소스를 설정하세요
- 또는 직접 `docker pull nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04`을 실행하세요

### 문제 2: pip 설치 시 `Cannot uninstall blinker` 오류

Ubuntu 22.04 시스템에 기본 포함된 `blinker`는 `distutils`로 설치되어 pip로 제거할 수 없습니다. `Dockerfile.gpu`에서 `apt-get remove -y python3-blinker`로 이미 처리되어 있습니다.

### 문제 3: 컨테이너 내에서 `nvidia-smi`가 GPU를 찾지 못함

- 호스트에 NVIDIA Container Toolkit이 설치되어 있는지 확인하세요
- `docker info`의 Runtimes에 `nvidia`가 포함되어 있는지 확인하세요
- GPU 배포 명령을 사용했는지 확인하세요: `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d`

### 문제 4: Whisper에서 CUDA 오류 발생

- `config.toml`에서 `device = "cuda"`인지 확인하세요(대소문자를 구분하며, `"CPU"`가 아닙니다)
- `compute_type = "float16"`인지 확인하세요
- `subtitle_provider = "whisper"`인지 확인하세요
