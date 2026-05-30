# 2026-04-02 PR 병합 및 검증 기록

## 이번에 병합하고 푸시한 PR

- `#837` `fix: update google-generativeai version for response_modalities support`
- `#835` `fix: add missing pydub dependency to requirements.txt`
- `#850` `feat: support reading subtitle position from config file`
- `#838` `feat: add MiniMax as LLM provider`
- `#811` `refactor: optimize codebase for better performance and reliability`
- `#848` `feat: support GPU acceleration for faster-whisper in Docker`
- `#843` `feat: Add Upload-Post integration for cross-posting to TikTok/Instagram`

## 병합 후 메인라인 커밋

- TTS 및 자막 수정 기준 커밋: `953a6c0` `fix: restore edge tts synthesis and readable subtitles`
- 현재 메인라인 커밋: `1f8a746`

## 병합 시 검증 결론

### 통과됨

- `#837`
  - 의존성 업그레이드 후 정상적으로 임포트됨
  - `google-generativeai==0.8.6`이 적용됨
- `#835`
  - `pydub==0.25.1`이 적용됨
- `#850`
  - `subtitle_position`와 `custom_position`를 설정 파일에서 읽을 수 있음
- `#838`
  - MiniMax provider 연동이 정상임
  - mock 호출을 사용해 `_generate_response` 통과를 검증함
- `#811`
  - 메인라인 임포트가 정상임
  - 표본 단위 테스트 통과
- `#848`
  - `docker compose -f docker-compose.yml -f docker-compose.gpu.yml config`가 정상적으로 파싱됨
- `#843`
  - Upload-Post 서비스 임포트 및 mock 업로드 호출 통과
  - 앞선 PR과 겹칠 때 `config.example.toml`에서만 설정 단락 충돌이 있었으며, 양쪽 내용을 수동으로 보존함

### 거부 및 종료됨

- `#852`
  - 오디오는 복구할 수 있지만 자막 파이프라인을 망가뜨리고, 여전히 WebUI에서 호출하는 Gemini 로직을 삭제함
- `#787`
  - 현재 `403` 상황을 해결하지 못함
- `#841`
  - 현재 메인라인의 TTS/자막 수정과 충돌하며, 그 이점은 더 작은 PR로 이미 커버됨
- `#824`
  - ModelsLab 경로로 오디오는 나오지만 자막 파이프라인이 실패하여 사용 가능한 SRT를 산출하지 못함
- `#840`
  - 백엔드에 `video_source="ai"`를 추가했지만 WebUI는 여전히 이 값을 지원하지 않아 엔드투엔드로 사용 불가
- `#826`
  - 현재 메인라인의 `voice.py` 및 의존성 변경과 충돌하여 병합 검증을 통과하지 못함
- `#751`
- `#749`
- `#742`
- `#705`
  - 위 4개 PR은 현재 메인라인에서 모두 `DIRTY` 상태이며, 병합 검증을 통과하지 못함

## 스모크 테스트 기록

### 서비스 재시작

- API：`http://127.0.0.1:8080/docs`
- WebUI：`http://127.0.0.1:8501`

### 첫 번째 전체 동영상 작업

- 작업 번호: `ced0b190-dd72-489c-b978-2761740933db`
- 결과: 실패
- 결론:
  - API 기본값이 `video_transition_mode=null`
  - 동영상 결합 단계에서 `app/services/video.py`가 `video_transition_mode.value`에 직접 접근함
  - 이로 인해 작업 스레드가 비정상 종료되고, 작업 상태가 `state=4, progress=75`에 멈춤

### 두 번째 전체 동영상 작업

- 작업 번호: `8b2a0e6e-b3e6-44ab-a1b4-1865a0b4788d`
- 제출 방식:
  - `POST /api/v1/videos`
  - 로컬 소재 `/Users/harry/Projects/Python/MoneyPrinterTurbo/test/resources/1.png` 사용
  - `video_transition_mode="FadeIn"`을 명시적으로 지정
- 결과: 성공
- 작업 상태: `state=1, progress=100`

### 두 번째 작업 산출물

- 오디오: `/Users/harry/Projects/Python/MoneyPrinterTurbo/storage/tasks/8b2a0e6e-b3e6-44ab-a1b4-1865a0b4788d/audio.mp3`
  - 길이: `8.952s`
  - 크기: `53712 bytes`
- 결합 동영상: `/Users/harry/Projects/Python/MoneyPrinterTurbo/storage/tasks/8b2a0e6e-b3e6-44ab-a1b4-1865a0b4788d/combined-1.mp4`
  - 길이: `9.000s`
  - 크기: `177666 bytes`
- 완성본: `/Users/harry/Projects/Python/MoneyPrinterTurbo/storage/tasks/8b2a0e6e-b3e6-44ab-a1b4-1865a0b4788d/final-1.mp4`
  - 길이: `9.000s`
  - 크기: `352810 bytes`
- 자막: `/Users/harry/Projects/Python/MoneyPrinterTurbo/storage/tasks/8b2a0e6e-b3e6-44ab-a1b4-1865a0b4788d/subtitle.srt`

### 두 번째 작업 자막 샘플

```srt
1
00:00:00,100 --> 00:00:03,300
이것은 메인라인 병합 후의 전체 스모크 테스트입니다

2
00:00:03,875 --> 00:00:05,350
우리는 음성을 확인하고자 합니다

3
00:00:05,575 --> 00:00:08,375
자막과 동영상 완성본이 모두 정상적으로 생성되는지
```

## 현재 여전히 주의가 필요한 리스크

- `#843`은 mock 검증만 했으며, 실제 Upload-Post 키로 연동 테스트를 아직 하지 않음
- `#848`은 Docker GPU 설정 파싱만 검증했으며, 실제 GPU 환경에서 아직 실행하지 않음
- 현재 API 기본값이 `video_transition_mode=null`일 때 전체 동영상 작업에는 여전히 회귀 리스크가 존재함
