<div align="center">
<h1 align="center">MoneyPrinterTurbo 💸</h1>

<p align="center">
  <a href="https://github.com/harry0703/MoneyPrinterTurbo/stargazers"><img src="https://img.shields.io/github/stars/harry0703/MoneyPrinterTurbo.svg?style=for-the-badge" alt="Stargazers"></a>
  <a href="https://github.com/harry0703/MoneyPrinterTurbo/issues"><img src="https://img.shields.io/github/issues/harry0703/MoneyPrinterTurbo.svg?style=for-the-badge" alt="Issues"></a>
  <a href="https://github.com/harry0703/MoneyPrinterTurbo/network/members"><img src="https://img.shields.io/github/forks/harry0703/MoneyPrinterTurbo.svg?style=for-the-badge" alt="Forks"></a>
  <a href="https://github.com/harry0703/MoneyPrinterTurbo/blob/main/LICENSE"><img src="https://img.shields.io/github/license/harry0703/MoneyPrinterTurbo.svg?style=for-the-badge" alt="License"></a>
</p>

<h3>한국어 | <a href="README-en.md">English</a> | <a href="README.md">简体中文</a> | <a href="README-ar.md">العربية</a></h3>

<div align="center">
  <a href="https://trendshift.io/repositories/8731" target="_blank"><img src="https://trendshift.io/api/badge/repositories/8731" alt="harry0703%2FMoneyPrinterTurbo | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
</div>

영상 <b>주제</b>나 <b>키워드</b>만 입력하면 영상 스크립트, 영상 소재, 자막, 배경 음악을 자동으로 생성하고 고화질 숏폼 영상으로 합성합니다.

### WebUI

![](docs/webui-en.jpg)

### API 인터페이스

![](docs/api.jpg)

</div>

## 주요 기능 🎯

- [x] `API`와 `WebUI`를 모두 지원하는 명확한 MVC 구조
- [x] AI 기반 영상 스크립트 생성 및 사용자 지정 스크립트 지원
- [x] 세로형 9:16 `1080x1920`, 가로형 16:9 `1920x1080` 영상 지원
- [x] 여러 개의 영상을 한 번에 생성한 뒤 원하는 결과를 선택 가능
- [x] 영상 클립 길이와 소재 전환 빈도 조정 가능
- [x] 중국어, 영어 등 다양한 언어의 영상 스크립트 지원
- [x] 다양한 음성 합성 옵션과 실시간 미리듣기 지원
- [x] 자막 글꼴, 위치, 색상, 크기, 외곽선, 배경 설정 지원
- [x] 무작위 또는 사용자 지정 배경 음악 지원
- [x] Pexels, Pixabay, Coverr 등 무료 고화질 영상 소재 소스 지원
- [x] OpenAI, AIHubMix, AIML API, Moonshot, Azure, Qwen, Gemini, Ollama, DeepSeek, MiniMax, Pollinations, ModelScope 등 다양한 LLM 제공자 지원

## 시스템 요구사항 📦

- 권장 플랫폼: Windows 10 이상, macOS 11 이상, 주요 Linux 배포판
- GPU는 필수는 아니지만 로컬 자막/영상 처리나 배치 생성 속도 향상에 도움이 됩니다.

| 항목 | 최소 | 권장 | 최적 |
| ---- | ---- | ---- | ---- |
| CPU | 4코어 | 6~8코어 | 8코어 이상 |
| RAM | 4GB | 8GB | 16GB 이상 |
| GPU | 필수 아님 | VRAM 4GB 이상 | VRAM 8GB 이상 |

클라우드 LLM, 클라우드 TTS, 온라인 소재 소스를 주로 사용한다면 GPU보다 CPU와 RAM이 더 중요합니다.

## 빠른 시작 🚀

### Windows

가장 빠른 로컬 테스트는 GitHub Releases에서 Windows 원클릭 패키지를 다운로드하는 것입니다.

- 최신 릴리스: https://github.com/harry0703/MoneyPrinterTurbo/releases/latest

압축을 해제한 뒤 먼저 `update.bat`을 실행하여 최신 코드로 업데이트하고, `start.bat`을 실행해 시작합니다. 실행 후 브라우저가 자동으로 열립니다. 빈 화면이 보이면 Chrome 또는 Edge 사용을 권장합니다.

### macOS / Linux

Python 3.11과 `uv` 사용을 권장합니다.

```shell
git clone https://github.com/harry0703/MoneyPrinterTurbo.git
cd MoneyPrinterTurbo
uv python install 3.11
uv sync --frozen
```

## 설정 파일 📄

프로젝트 루트에서 예시 설정 파일을 복사합니다.

```shell
cp config.example.toml config.toml
```

`config.toml`에서 다음 항목을 설정합니다.

- `llm_provider`: 사용할 LLM 제공자 (`openai`, `aihubmix`, `pollinations`, `ollama` 등)
- 각 제공자의 API 키와 모델 이름
- `pexels_api_keys`, `pixabay_api_keys`, `coverr_api_keys`: 온라인 영상 소재를 사용할 때 필요한 API 키
- `subtitle_provider`: `edge` 또는 `whisper`

### OpenAI 설정

OpenAI를 사용할 때는 `config.toml`에서 다음 값을 설정합니다.

```toml
llm_provider = "openai"
openai_api_key = "your-openai-api-key"
openai_base_url = ""
openai_model_name = "gpt-4o-mini"
```

- OpenAI 공식 API를 사용하면 `openai_base_url`은 비워둘 수 있습니다.
- OpenAI 호환 제공자(OpenRouter 등)를 사용하면 해당 제공자의 Base URL과 모델 ID를 입력하세요.
- API 키는 https://platform.openai.com/api-keys 에서 발급할 수 있습니다.

## WebUI 실행 🌐

프로젝트 루트에서 실행합니다.

```shell
uv run streamlit run ./webui/Main.py --browser.gatherUsageStats=False --server.showEmailPrompt=False
```

실행 후 브라우저에서 다음 주소로 접속합니다.

```text
http://127.0.0.1:8501
```

## API 서비스 실행 🚀

```shell
uv run python main.py
```

API 문서는 다음 주소에서 확인할 수 있습니다.

```text
http://127.0.0.1:8080/docs
http://127.0.0.1:8080/redoc
```

## CLI 모드 ⌨️

브라우저 없이 명령줄에서 바로 영상을 생성할 수도 있습니다.

```shell
uv run python cli.py --video-subject "돈의 역할"
```

로컬 영상 소재를 사용하려면 다음처럼 실행합니다.

```shell
uv run python cli.py \
  --video-subject "돈의 역할" \
  --video-source local \
  --video-materials "1.mp4,2.mp4" \
  --stop-at video
```

## Docker 배포 🐳

`config.toml`을 준비한 뒤 prebuilt 이미지를 사용할 수 있습니다.

```shell
docker compose -f docker-compose.release.yml up
```

- WebUI: http://127.0.0.1:8501
- API 문서: http://127.0.0.1:8080/docs

## 음성 합성 🗣

기본 TTS 제공자는 무료 Edge TTS입니다. WebUI에서는 `Azure TTS V1`로 표시됩니다. Azure Speech API 키가 필요한 `Azure TTS V2`와는 다릅니다.

Azure TTS V2를 사용하려면 다음 값을 설정합니다.

```toml
[azure]
speech_key = "your-azure-speech-key"
speech_region = "eastus"
```

## 자막 생성 📜

자막 생성 방식은 두 가지입니다.

- `edge`: Edge TTS 타임스탬프를 사용합니다. 빠르고 별도 GPU가 필요 없습니다.
- `whisper`: `faster-whisper`를 로컬에서 실행합니다. 더 정확할 수 있지만 모델 다운로드와 더 많은 처리 시간이 필요합니다.

`config.toml`에서 선택합니다.

```toml
subtitle_provider = "edge"
```

## 배경 음악 🎵

기본 배경 음악은 `resource/songs` 디렉터리에 있습니다. 저작권 문제가 있는 경우 해당 파일을 삭제하세요.

## 자막 글꼴 🅰

자막 렌더링에 사용할 글꼴은 `resource/fonts` 디렉터리에 있습니다. 필요한 경우 사용자 지정 글꼴을 추가할 수 있습니다.

## 자주 묻는 질문 🤔

### RuntimeError: No ffmpeg exe could be found

일반적으로 ffmpeg는 자동으로 다운로드 및 감지됩니다. 문제가 발생하면 시스템에 ffmpeg를 설치하거나 `config.toml`에서 경로를 지정하세요.

```toml
[app]
ffmpeg_path = "C:\\path\\to\\ffmpeg.exe"
```

### ImageMagick이 필요한가요?

현재 버전은 MoviePy 2.x를 사용하며 자막 렌더링은 Pillow 기반입니다. ImageMagick 설치가 필요하지 않습니다.

## 피드백 및 제안 📢

Issue 또는 Pull Request를 통해 피드백을 남길 수 있습니다.

- Issues: https://github.com/harry0703/MoneyPrinterTurbo/issues
- Pull Requests: https://github.com/harry0703/MoneyPrinterTurbo/pulls

## 라이선스 📝

자세한 내용은 [`LICENSE`](LICENSE)를 참고하세요.
