<div align="center">

# shipcast

### 새로 나온 개발 도구를 카드뉴스 영상으로

Hacker News 같은 곳에서 오늘 올라온 것을 모아, 한국어 카드뉴스 세로 영상으로 만듭니다.
스톡 영상으로 숏폼을 만드는 기존 경로도 그대로 동작합니다.

한국어 | [English](README-en.md)

</div>

## 목차

- [카드뉴스 만들기](#카드뉴스-만들기)
- [밖에서 만들기 (텔레그램)](#밖에서-만들기-텔레그램)
- [숏폼 영상 만들기](#숏폼-영상-만들기)
- [시스템 요구사항](#시스템-요구사항)
- [설치](#설치)
- [설정](#설정)
- [사용법](#사용법)
  - [WebUI](#1-webui-가장-쉬움)
  - [CLI](#2-cli-브라우저-없이)
  - [REST API](#3-rest-api)
- [한국어로 영상 만들기](#한국어로-영상-만들기)
- [보안 주의사항](#보안-주의사항)
- [자주 묻는 질문](#자주-묻는-질문)
- [만든 것에 대해](#만든-것에-대해)

## 카드뉴스 만들기

```
Hacker News  →  카드 대본  →  카드별 나레이션  →  세로 영상
   (무료 API)      (LLM)         (TTS)          (mp4)
```

한 편은 카드 대여섯 장입니다. 첫 장이 왜 볼 만한지 말하고, 가운데 장들이 한 장에 하나씩 다루고, 마지막 장이 써 볼지 말지를 말합니다.

**화면에 나오는 것이 곧 내용입니다.** 스톡 영상을 찾아 붙이지 않으므로 소재가 내용과 어긋날 일이 없습니다.

### 두 가지 원칙

**도구에 대한 모든 서술은 소재에서 나옵니다.** 없는 기능, 벤치마크, 가격, 만든 사람을 지어내지 않습니다. 소재가 말하지 않는 것은 말하지 않습니다. 실제 존재하는 도구고, 만든 사람이 이 영상을 보기 때문입니다.

**출처를 밝힙니다.** 첫 장과 마지막 장에 어디서 왔고 반응이 어땠는지 남깁니다. 남의 작업을 소개하는 채널이라 이건 예의가 아니라 최소 조건입니다.

### 세 단계

```python
from app.models.schema import VideoParams
from app.services.cardscript import build_card_script
from app.services.cardvideo import render_card_news
from app.services.sources import hackernews

items = hackernews.fetch_items(min_points=100, within_hours=48, tags="show_hn")
script = build_card_script(items[0])

params = VideoParams(video_subject=items[0].title)
params.voice_name = "ko-KR-HyunsuMultilingualNeural-Male"
params.voice_rate = 1.15

result = render_card_news("my-task", script, params)
print(result.video_path, result.duration)
```

`tags` 는 Algolia 문법을 그대로 씁니다. `show_hn` 이 새 도구 소개에 적중률이 높습니다.

카드마다 나레이션을 따로 합성해, 그 카드 오디오의 실제 길이가 화면에 머무는 시간이 됩니다. 통째로 읽고 글자 수로 나누면 문장마다 속도가 달라 뒤로 갈수록 화면과 소리가 벌어집니다.

### 소재를 어디서 가져오나

| 출처 | 상태 |
| --- | --- |
| Hacker News | 키 불필요, 요금 없음, 레이트리밋 없음 |
| Product Hunt | 무료 개발자 토큰 (예정) |
| GitHub 트렌딩 | Search API 로 근사 (예정) |
| X | 2026년 2월부터 무료 티어 없음. 종량제 $0.005/read |

## 밖에서 만들기 (텔레그램)

주제를 보내면 대본을 만들어 보여 주고, 승인하면 렌더링해서 영상을 보냅니다. 봇이 텔레그램 서버로 나가서 물어보는 방식이라 **공인 IP 도 포트 개방도 필요 없습니다.**

```toml
[telegram]
bot_token = ""   # @BotFather 에서 /newbot
chat_id = ""     # 비워 두고 켠 뒤 아무 메시지나 보내면 터미널에 찍힙니다
```

```shell
python telegram_bot.py
```

1:1 대화에서, 설정에 적힌 `chat_id` 로 온 것만 처리합니다. 그룹 대화는 받지 않습니다.

렌더링은 십 분대라 대본을 먼저 보고 멈출 수 있어야 합니다. 그냥 글을 보내면 그 내용으로 대본을 바꿉니다.

## 숏폼 영상 만들기

주제 하나로 대본·나레이션·자막을 만들고 스톡 영상을 붙여 세로 영상을 뽑는 경로입니다.
카드뉴스와 달리 화면은 실제 촬영 영상이고, 아래 설정·사용법은 두 경로가 함께 씁니다.

### 동작 방식

한 번의 생성 요청은 아래 6단계 파이프라인을 순서대로 통과합니다. CLI의 `--stop-at` 옵션으로 원하는 단계에서 멈출 수 있습니다.

| 단계 | 하는 일 | 필요한 것 |
| --- | --- | --- |
| `script` | LLM이 영상 대본 작성 | LLM API 키 |
| `terms` | 대본에서 소재 검색 키워드(영문) 추출 | LLM API 키 |
| `audio` | TTS로 나레이션 음성 생성 | TTS 제공자 (Edge TTS는 무료·키 불필요) |
| `subtitle` | 자막 생성 (edge 타임스탬프 또는 whisper) | - |
| `materials` | Pexels/Pixabay/Coverr에서 영상 소재 다운로드 | 소재 제공자 API 키 |
| `video` | 최종 합성 및 인코딩, 설정 시 SNS 업로드 | FFmpeg |

결과물은 `storage/tasks/<task-id>/` 아래에 저장됩니다.

**주요 기능**

- LLM 제공자 20여 종 지원: Kimi/Moonshot, OpenAI, Gemini, DeepSeek, Qwen, Azure OpenAI, VolcEngine, Grok, MiniMax, MiMo + 게이트웨이/로컬 런타임(Cloudflare AI Gateway, ModelScope, AIHubMix, AIML API, EvoLink, Ollama, OneAPI, LiteLLM, Groq, Pollinations)
- TTS: Edge TTS(무료), Azure Speech, SiliconFlow, Google Gemini, Xiaomi MiMo, ElevenLabs, 자체 호스팅 Chatterbox, 음성 없음 모드
- 화면 비율: 세로 9:16 (`1080x1920`), 가로 16:9 (`1920x1080`)
- 배치 생성, 클립 길이·속도 조절, 전환 효과, 자막 스타일링
- 배경음악: 내장 음원 / 직접 업로드 / Sonilo·ElevenLabs AI 자동 작곡
- 생성 후 TikTok, Instagram, YouTube Shorts 자동 업로드 (Upload-Post 연동)

## 시스템 요구사항

- Windows 10+, macOS 11+, 또는 주요 Linux 배포판
- Python 3.11 이상 (3.11 권장)
- FFmpeg (보통 자동으로 설치·탐지됨)
- GPU는 필수가 아님

| 항목 | 최소 | 권장 | 최적 |
| --- | --- | --- | --- |
| CPU | 4코어 | 6~8코어 | 8코어 이상 |
| RAM | 4GB | 8GB | 16GB 이상 |
| GPU | 불필요 | VRAM 4GB+ | VRAM 8GB+ |

클라우드 LLM·TTS와 온라인 소재를 주로 쓴다면 GPU보다 CPU·RAM이 중요합니다. `faster-whisper` 자막이나 배치 생성을 자주 쓴다면 GPU가 체감 차이를 냅니다.

## 설치

### uv 사용 (권장)

```shell
git clone https://github.com/raidostar/MoneyPrinterTurbo.git shipcast
cd shipcast
uv python install 3.11
uv sync --frozen
```

### venv + pip

```shell
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> `pyproject.toml`이 주 의존성 명세이고 `uv.lock`이 버전을 고정합니다. `requirements.txt`는 pip 호환용으로만 유지됩니다.

### Docker

```shell
cp config.example.toml config.toml
docker compose up          # 로컬 빌드
# 또는 사전 빌드 이미지 사용
docker compose -f docker-compose.release.yml up
```

WebUI는 http://127.0.0.1:8501, API 문서는 http://127.0.0.1:8080/docs 에서 열립니다. 두 포트 모두 `127.0.0.1`에만 바인딩됩니다.

> ⚠️ `Dockerfile`은 기본적으로 Aliyun/Tsinghua 미러에서 apt·pip 패키지를 받습니다. 공식 저장소를 쓰려면 `--build-arg DOCKER_BUILD_MIRROR=default --build-arg PIP_USE_OFFICIAL=1` 를 넘기세요. 자세한 내용은 [보안 주의사항](#보안-주의사항) 참고.

## 설정

최초 실행 시 `config.example.toml`이 `config.toml`로 복사됩니다. 대부분의 값은 WebUI 기본 설정 패널에서 바로 편집할 수 있습니다.

**최소 설정** — 전체 영상 하나를 만들려면 두 가지가 필요합니다.

```toml
[app]
# 1. LLM (대본 + 검색 키워드 생성)
llm_provider = "moonshot"
moonshot_api_key = "sk-..."

# 2. 영상 소재 제공자
video_source = "pexels"
pexels_api_keys = ["your-pexels-key"]
```

API 키 발급처는 `config.example.toml`의 각 항목 주석에 링크로 적혀 있습니다. 나레이션은 기본값인 Edge TTS를 쓰면 별도 키가 필요 없습니다.

로컬 파일만 쓰고 싶다면 소재 API 키 없이도 됩니다.

```toml
video_source = "local"
```

## 사용법

### 1. WebUI (가장 쉬움)

```shell
# macOS / Linux
sh webui.sh

# Windows
.\webui.bat
```

브라우저가 자동으로 열립니다 (기본 http://127.0.0.1:8501). 스크립트가 8501~8599 범위에서 비어 있는 포트를 알아서 고릅니다.

같은 네트워크의 다른 기기에서 접속하려면:

```shell
MPT_WEBUI_HOST=0.0.0.0 sh webui.sh     # Windows: set MPT_WEBUI_HOST=0.0.0.0
```

> ⚠️ WebUI에는 로그인 기능이 없습니다. `0.0.0.0`으로 열면 같은 네트워크의 누구나 설정 화면에서 **API 키 전체를 볼 수 있고** 영상 생성을 실행할 수 있습니다.

화면 순서대로 진행하면 됩니다.

1. **기본 설정** 패널에서 LLM 제공자 + API 키 입력 → 연결 테스트
2. **영상 주제** 입력 → *AI로 대본 및 키워드 생성*
3. 영상 / 오디오 / 자막 옵션 조정 (대부분 기본값으로 충분)
4. **영상 생성** 클릭 → 상단 **작업 관리자**에서 진행 상황 확인

### 2. CLI (브라우저 없이)

```shell
# 가장 단순한 형태
uv run python cli.py --video-subject "AI가 일상을 어떻게 바꾸고 있는가"

# 로컬 소재로 생성
uv run python cli.py --video-subject "제주도 여행" \
  --video-source local --video-materials "./1.mp4,./2.mp4"

# 이미 쓴 대본을 쓰고 나레이션은 생략
uv run python cli.py --video-script "완성된 대본 전문" \
  --voice-name no-voice --stop-at video

# 대본만 생성하고 중단
uv run python cli.py --video-subject "AI 트렌드" --stop-at script
```

전체 옵션은 `uv run python cli.py --help` 로 확인하세요. 옵션은 대본/콘텐츠, 소재/파이프라인, 영상 출력, 나레이션/배경음악, 자막, 실행 그룹으로 나뉘어 있습니다.

성공하면 stdout에 JSON 한 덩어리를 출력하고 종료 코드 0을 반환합니다. 작업 실패는 1, 인자 오류는 2이며 로그는 stderr로 나갑니다.

### 3. REST API

```shell
uv run python main.py
```

Swagger 문서: http://127.0.0.1:8080/docs

**모든 `/api/v1` 엔드포인트는 인증이 필요합니다.** 먼저 `config.toml`에 키를 설정하세요.

```toml
[app]
api_key = "임의의-긴-무작위-문자열"
```

키가 비어 있으면 모든 요청이 401로 거부됩니다. WebUI와 CLI는 API를 거치지 않으므로 영향을 받지 않습니다.

```shell
curl -X POST http://127.0.0.1:8080/api/v1/videos \
  -H "Content-Type: application/json" \
  -H "x-api-key: 임의의-긴-무작위-문자열" \
  -d '{"video_subject": "AI가 일상을 어떻게 바꾸고 있는가", "video_language": "ko-KR"}'
# → {"data": {"task_id": "..."}}

curl -H "x-api-key: 임의의-긴-무작위-문자열" \
  http://127.0.0.1:8080/api/v1/tasks/<task_id>
```

주요 엔드포인트:

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| POST | `/api/v1/videos` | 영상 생성 작업 시작 |
| POST | `/api/v1/subtitle` | 자막만 생성 |
| POST | `/api/v1/audio` | 나레이션만 생성 |
| GET | `/api/v1/tasks` | 작업 목록 (페이지네이션) |
| GET | `/api/v1/tasks/{task_id}` | 작업 상태 조회 |
| DELETE | `/api/v1/tasks/{task_id}` | 작업 및 산출물 삭제 |
| GET | `/api/v1/stream/{file_path}` | 영상 스트리밍 (Range 지원) |
| GET | `/api/v1/download/{file_path}` | 영상 다운로드 |
| GET/POST | `/api/v1/musics` | 배경음악 목록 / 업로드 |
| GET/POST | `/api/v1/video_materials` | 로컬 소재 목록 / 업로드 |

> 이 포크는 원본과 달리 **API 인증이 기본 활성화**되어 있고 `listen_host`가 `127.0.0.1`입니다. 자세한 내용은 아래 [보안 주의사항](#보안-주의사항) 참고.

## 한국어로 영상 만들기

1. **UI 언어** — 브라우저 언어가 한국어면 자동으로 한국어 UI가 뜹니다. 아니면 상단 언어 선택기에서 `한국어`를 고르세요.
2. **대본 언어** — *대본 언어* 드롭다운에서 `ko-KR` 선택. `자동 감지`로 두면 입력한 주제의 언어를 따라갑니다.
3. **나레이션 음성** — 음성 목록에서 `ko-KR` 로 시작하는 항목을 고르세요. Edge TTS(무료) 기준으로 사용 가능한 음성입니다.

   | 음성 | 성별 |
   | --- | --- |
   | `ko-KR-SunHiNeural` | 여성 |
   | `ko-KR-InJoonNeural` | 남성 |
   | `ko-KR-HyunsuMultilingualNeural` | 남성 (다국어) |

4. **자막 글꼴** — 신경 쓰지 않으셔도 됩니다. 선택한 글꼴이 대본을 그릴 수 없으면 **생성 시점에 그릴 수 있는 글꼴로 자동 교체**되고 로그에 남습니다.

   원본 프로젝트가 번들한 글꼴은 중국어·일본어용이라 한글 글리프가 없고, 반대로 한글 글꼴에는 한자·가나가 없습니다. 어느 하나를 기본값으로 고정할 수 없어서 대본을 보고 고르는 방식을 씁니다.

   | 글꼴 | 한글 | 일본어 | 중국어 |
   | --- | :---: | :---: | :---: |
   | `Pretendard-Bold.ttf` (기본값) | O | X | X |
   | `MicrosoftYaHeiBold.ttc` | X | O | O |
   | `STHeitiMedium.ttc` | X | O | O |

   직접 고르시려면 한국어는 `Pretendard`, 일본어·중국어는 `MicrosoftYaHei` 나 `STHeiti` 중 아무거나 쓰시면 됩니다. 새 글꼴을 넣으실 때는 `.ttf` 또는 `.ttc` 여야 목록에 나타납니다.

5. **영상 검색 키워드** — 소재 제공자(Pexels/Pixabay/Coverr)가 영어 검색만 지원하므로 키워드는 영어로 생성됩니다. 정상 동작이며 대본과 자막은 한국어 그대로입니다.

## 보안 주의사항

이 프로젝트는 **신뢰할 수 있는 로컬 환경에서 단일 사용자가 쓰는 도구**로 설계되어 있습니다. 공개 네트워크에 그대로 노출하면 안 됩니다.

| 항목 | 현재 상태 | 대응 |
| --- | --- | --- |
| API 인증 | ✅ 활성화 — 모든 `/api/v1` 엔드포인트가 `x-api-key` 요구. `api_key` 미설정 시 전부 401 (fail-closed) | `config.toml`에 `api_key` 설정 |
| API 바인딩 주소 | ✅ `listen_host = "127.0.0.1"` (로컬 전용) | 외부 접속이 필요하면 리버스 프록시 뒤에 두세요 |
| CORS | `allow_origins=["*"]`, `allow_credentials=True` (`app/asgi.py`) | `CORS_ALLOWED_ORIGINS` 환경변수로 출처 제한. API 인증이 켜져 있어 CSRF 위험은 크게 줄었음 |
| WebUI 인증 | 없음 | `MPT_WEBUI_HOST`를 `127.0.0.1`(기본값)로 유지 |
| 생성물 정적 경로 | ✅ `/tasks/<task-id>/...` 도 `x-api-key` 요구. 이 경로는 `StaticFiles` 마운트라 라우터 의존성이 걸리지 않아 별도 미들웨어로 보호 | `config.toml`에 `api_key` 설정 |
| 심볼릭 링크 | `/tasks` 정적 마운트가 `follow_symlink=True` (`app/asgi.py`) | `storage/tasks/` 안에 외부를 가리키는 심볼릭 링크를 만들지 말 것 |
| Docker 빌드 미러 | apt·pip 패키지를 기본적으로 Aliyun/Tsinghua 미러에서 받음. pip은 `--trusted-host`로 해당 호스트의 인증서 검증을 건너뜀 | `--build-arg DOCKER_BUILD_MIRROR=default --build-arg PIP_USE_OFFICIAL=1` 로 공식 저장소 사용 |
| 컨테이너 권한 | root로 실행, `chmod 777 /shipcast`, `docker-compose.yml`이 저장소 전체를 마운트 | 필요 시 `docker-compose.release.yml`처럼 `config.toml`·`storage`만 마운트 |
| TLS 검증 | `tls_verify = true` (기본 켜짐) | 그대로 유지 |
| Redis 상태 저장소 | 값을 `ast.literal_eval`로 복원 — Redis를 애플리케이션 신뢰 경계 안으로 가정 | Redis를 외부에 노출하지 말 것 |

`config.toml`에는 모든 API 키가 평문으로 저장되며 `.gitignore`에 등록되어 있습니다. 커밋하지 마세요.

## 자주 묻는 질문

<details>
<summary>TikTok / Instagram / YouTube Shorts 자동 업로드 설정</summary>

[Upload-Post](https://upload-post.com/) 계정과 API 키를 만든 뒤 `config.toml`의 `[app]` 아래에 추가합니다.

```toml
[app]
upload_post_enabled = true
upload_post_api_key = "your-api-key"
upload_post_username = "your-username"
upload_post_platforms = ["tiktok", "instagram", "youtube"]
upload_post_auto_upload = true
upload_post_youtube_privacy_status = "public"   # public | unlisted | private
```

저장 후 앱을 재시작하면 생성된 영상이 자동으로 업로드됩니다.

</details>

<details>
<summary>RuntimeError: No ffmpeg exe could be found</summary>

보통 FFmpeg는 자동으로 다운로드·탐지됩니다. 자동 다운로드가 실패하면 https://www.gyan.dev/ffmpeg/builds/ 에서 받아 압축을 푼 뒤 실제 경로를 지정하세요.

```toml
[app]
# Windows 경로 구분자는 \\ 입니다
ffmpeg_path = "C:\\Users\\me\\Downloads\\ffmpeg.exe"
```

</details>

<details>
<summary>더 정확한 자막이 필요할 때 (Whisper)</summary>

```toml
[app]
subtitle_provider = "whisper"

[whisper]
model_size = "large-v3-turbo"   # 약 1.6GB. large-v3는 약 3GB
device = "cpu"                  # 또는 "cuda"
compute_type = "int8"           # CUDA는 "float16" 또는 "int8_float16"
```

최초 사용 시 Hugging Face에서 모델을 자동으로 내려받습니다. 실패하면 [Hugging Face](https://huggingface.co/Systran/faster-whisper-large-v3)에서 직접 받아 `models/whisper-large-v3/` 에 넣으세요.

```
shipcast
  └─models
      └─whisper-large-v3
             config.json
             model.bin
             preprocessor_config.json
             tokenizer.json
             vocabulary.json
```

`webui.sh` / `webui.bat` 안에 `HF_ENDPOINT=https://hf-mirror.com` 줄이 주석 처리된 채로 들어 있습니다. 기본값은 공식 Hugging Face이며, 미러를 쓰려면 직접 주석을 해제해야 합니다.

</details>

<details>
<summary>OSError: [Errno 24] Too many open files</summary>

시스템의 파일 열기 제한 때문입니다.

```shell
ulimit -n          # 현재 값 확인
ulimit -n 10240    # 상향
```

</details>

<details>
<summary>디스크 용량이 계속 늘어날 때</summary>

자동으로 내려받은 영상 소재는 `storage/cache_videos/` 에 쌓입니다. WebUI의 **설정 → 캐시 관리** 탭에서 기간별로 정리할 수 있습니다. 업로드한 소재와 생성된 영상은 삭제되지 않습니다. 영상 생성 중에는 캐시를 정리하지 마세요.

</details>

## 만든 것에 대해

[MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) 에서 갈라져 나왔습니다.
영상 파이프라인, TTS, 자막, 합성은 그쪽 코드가 바탕입니다.

이 저장소에서 달라진 것: 한국어화, API 인증, 한글 자막 글꼴, 쇼츠 카드 레이아웃,
대본 문체 규칙, 소재 수집기, 카드뉴스 렌더러, 텔레그램 봇.

## 라이선스

[`LICENSE`](LICENSE) 파일 참고 (MIT).

원본 프로젝트: [harry0703/MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo)
