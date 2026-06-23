# ElevenLabs TTS Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ElevenLabs as a TTS provider in MoneyPrinterTurbo, fetching favorite voices dynamically from the ElevenLabs API via HTTP requests.

**Architecture:** Follow the existing provider pattern (SiliconFlow/MiMo) — three new functions in `voice.py` (`get_elevenlabs_voices`, `is_elevenlabs_voice`, `elevenlabs_tts`), a dispatcher branch in `tts()`, a config section, and a WebUI panel. Voice names use the prefix format `elevenlabs:{voice_id}:{name}`.

**Tech Stack:** Python `requests` (already imported in `voice.py`), ElevenLabs REST API v1/v2, MoviePy (already used for audio duration), Streamlit (WebUI).

## Global Constraints

- Voice name format: `elevenlabs:{voice_id}:{name}` (e.g. `elevenlabs:pNInz6obpgDQGcFmaJgB:Adam`)
- HTTP only — no ElevenLabs SDK
- Retry TTS calls 3 times on failure (consistent with SiliconFlow)
- Use `populate_legacy_submaker_with_full_text` for SubMaker (ElevenLabs returns no word-level timing)
- Config key stored at `config.elevenlabs["api_key"]`
- Tests live in `test/services/test_voice.py` using `unittest`

---

### Task 1: Config Setup

**Files:**
- Modify: `app/config/config.py:150-164`
- Modify: `config.example.toml` (end of file, after `[siliconflow]` section)

**Interfaces:**
- Produces: `config.elevenlabs` dict accessible as `config.elevenlabs.get("api_key", "")`

- [ ] **Step 1: Add elevenlabs to `save_config()` in `app/config/config.py`**

Current `save_config()` at line 150:
```python
def save_config():
    with open(config_file, "w", encoding="utf-8") as f:
        _cfg["app"] = app
        _cfg["azure"] = azure
        _cfg["siliconflow"] = siliconflow
        _cfg["ui"] = ui
        f.write(toml.dumps(_cfg))
```

Change to:
```python
def save_config():
    with open(config_file, "w", encoding="utf-8") as f:
        _cfg["app"] = app
        _cfg["azure"] = azure
        _cfg["siliconflow"] = siliconflow
        _cfg["elevenlabs"] = elevenlabs
        _cfg["ui"] = ui
        f.write(toml.dumps(_cfg))
```

- [ ] **Step 2: Add module-level `elevenlabs` variable in `app/config/config.py`**

Current lines 163-164:
```python
azure = _cfg.get("azure", {})
siliconflow = _cfg.get("siliconflow", {})
```

Change to:
```python
azure = _cfg.get("azure", {})
siliconflow = _cfg.get("siliconflow", {})
elevenlabs = _cfg.get("elevenlabs", {})
```

- [ ] **Step 3: Add `[elevenlabs]` section to `config.example.toml`**

After the `[siliconflow]` section (after line `api_key = ""`), add:

```toml
[elevenlabs]
# ElevenLabs API Key
# Get your API key at https://elevenlabs.io/app/settings/api-keys
# Mark voices as favorites in the ElevenLabs voice library to make them appear here.
api_key = ""
```

- [ ] **Step 4: Verify config loads correctly**

```bash
cd /Users/mantang/Desktop/Project/MoneyPrinterTurbo
python -c "from app.config import config; print(config.elevenlabs)"
```

Expected output: `{}`

- [ ] **Step 5: Commit**

```bash
git add app/config/config.py config.example.toml
git commit -m "feat: add ElevenLabs config section"
```

---

### Task 2: Voice Service Functions

**Files:**
- Modify: `app/services/voice.py`
  - Add `get_elevenlabs_voices()` after `get_mimo_voices()` (around line 139)
  - Add `is_elevenlabs_voice()` after `is_mimo_voice()` (around line 200)
  - Add `elevenlabs_tts()` after `mimo_tts()` (around line 1143)
  - Update `tts()` dispatcher (around line 351-363)

**Interfaces:**
- Consumes: `config.elevenlabs.get("api_key", "")` from Task 1
- Consumes: `ensure_legacy_submaker_fields(SubMaker())`, `populate_legacy_submaker_with_full_text()`, `ensure_file_path_exists()` — all already in `voice.py`
- Produces:
  - `get_elevenlabs_voices(api_key: str) -> list[str]`
  - `is_elevenlabs_voice(voice_name: str) -> bool`
  - `elevenlabs_tts(text: str, voice_id: str, voice_file: str) -> Union[SubMaker, None]`

- [ ] **Step 1: Add `get_elevenlabs_voices()` after `get_mimo_voices()` (after line ~139)**

Insert this function after the closing `return [f"mimo:{voice}-{gender}" for voice, gender in voices_with_gender]` line:

```python
def get_elevenlabs_voices(api_key: str) -> list[str]:
    if not api_key:
        return []
    try:
        url = "https://api.elevenlabs.io/v2/voices"
        params = {"is_favorite": "true", "page_size": 100}
        headers = {"xi-api-key": api_key}
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.status_code != 200:
            logger.warning(
                f"ElevenLabs voices fetch failed with status {response.status_code}: {response.text}"
            )
            return []
        data = response.json()
        voices = data.get("voices", [])
        return [
            f"elevenlabs:{v['voice_id']}:{v['name']}"
            for v in voices
            if v.get("voice_id") and v.get("name")
        ]
    except Exception as e:
        logger.warning(f"ElevenLabs voices fetch failed: {str(e)}")
        return []
```

- [ ] **Step 2: Add `is_elevenlabs_voice()` after `is_mimo_voice()` (after line ~200)**

Insert after `def is_mimo_voice(voice_name: str):` block:

```python
def is_elevenlabs_voice(voice_name: str) -> bool:
    return (voice_name or "").startswith("elevenlabs:")
```

- [ ] **Step 3: Add `elevenlabs_tts()` after `mimo_tts()` (after line ~1142)**

Insert after the closing `return None` of `mimo_tts`:

```python
def elevenlabs_tts(
    text: str,
    voice_id: str,
    voice_file: str,
) -> Union[SubMaker, None]:
    text = (text or "").strip()
    if not text:
        logger.error("ElevenLabs TTS text is empty")
        return None

    api_key = config.elevenlabs.get("api_key", "")
    if not api_key:
        logger.error("ElevenLabs API key is not set")
        return None

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }

    for i in range(3):
        try:
            logger.info(f"start elevenlabs tts, voice_id: {voice_id}, try: {i + 1}")
            ensure_file_path_exists(voice_file)

            response = requests.post(url, json=payload, headers=headers, timeout=60)
            if response.status_code != 200:
                logger.error(
                    f"elevenlabs tts failed with status {response.status_code}: {response.text}"
                )
                continue

            with open(voice_file, "wb") as f:
                f.write(response.content)

            audio_clip = AudioFileClip(voice_file)
            audio_duration = audio_clip.duration
            audio_clip.close()

            sub_maker = ensure_legacy_submaker_fields(SubMaker())
            logger.success(f"elevenlabs tts succeeded: {voice_file}")
            return populate_legacy_submaker_with_full_text(
                sub_maker=sub_maker,
                text=text,
                audio_duration_seconds=audio_duration,
            )
        except Exception as e:
            logger.error(f"elevenlabs tts failed: {str(e)}")

    return None
```

- [ ] **Step 4: Update `tts()` dispatcher (around line 351)**

Current code before the final fallback:
```python
    elif is_mimo_voice(voice_name):
        # 从voice_name中提取声音名称
        # 格式: mimo:voice-Gender；如果调用方已执行 parse_voice_name，
        # 则可能是 mimo:voice。两种格式都兼容。
        parts = voice_name.split(":")
        if len(parts) >= 2:
            voice_with_gender = parts[1]
            voice = voice_with_gender.split("-")[0]
            return mimo_tts(text, voice, voice_rate, voice_file, voice_volume)
        else:
            logger.error(f"Invalid mimo voice name format: {voice_name}")
            return None
    return azure_tts_v1(text, voice_name, voice_rate, voice_file)
```

Change to:
```python
    elif is_mimo_voice(voice_name):
        # 从voice_name中提取声音名称
        # 格式: mimo:voice-Gender；如果调用方已执行 parse_voice_name，
        # 则可能是 mimo:voice。两种格式都兼容。
        parts = voice_name.split(":")
        if len(parts) >= 2:
            voice_with_gender = parts[1]
            voice = voice_with_gender.split("-")[0]
            return mimo_tts(text, voice, voice_rate, voice_file, voice_volume)
        else:
            logger.error(f"Invalid mimo voice name format: {voice_name}")
            return None
    elif is_elevenlabs_voice(voice_name):
        # 格式: elevenlabs:{voice_id}:{name}
        parts = voice_name.split(":")
        if len(parts) >= 2:
            voice_id = parts[1]
            return elevenlabs_tts(text, voice_id, voice_file)
        else:
            logger.error(f"Invalid elevenlabs voice name format: {voice_name}")
            return None
    return azure_tts_v1(text, voice_name, voice_rate, voice_file)
```

- [ ] **Step 5: Verify syntax**

```bash
cd /Users/mantang/Desktop/Project/MoneyPrinterTurbo
python -c "from app.services import voice; print('ok')"
```

Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add app/services/voice.py
git commit -m "feat: add ElevenLabs TTS functions to voice service"
```

---

### Task 3: Unit Tests

**Files:**
- Modify: `test/services/test_voice.py`

**Interfaces:**
- Consumes: `get_elevenlabs_voices(api_key)`, `is_elevenlabs_voice(voice_name)`, `elevenlabs_tts(text, voice_id, voice_file)` from Task 2

- [ ] **Step 1: Add unit tests for `is_elevenlabs_voice` and `get_elevenlabs_voices`**

Add a new test class at the end of `test/services/test_voice.py`:

```python
class TestElevenLabsVoice(unittest.TestCase):

    def test_is_elevenlabs_voice_true(self):
        self.assertTrue(vs.is_elevenlabs_voice("elevenlabs:pNInz6obpgDQGcFmaJgB:Adam"))

    def test_is_elevenlabs_voice_false_azure(self):
        self.assertFalse(vs.is_elevenlabs_voice("zh-CN-XiaoxiaoNeural-Female"))

    def test_is_elevenlabs_voice_false_siliconflow(self):
        self.assertFalse(vs.is_elevenlabs_voice("siliconflow:model:voice-Male"))

    def test_is_elevenlabs_voice_empty(self):
        self.assertFalse(vs.is_elevenlabs_voice(""))

    def test_is_elevenlabs_voice_none(self):
        self.assertFalse(vs.is_elevenlabs_voice(None))

    def test_get_elevenlabs_voices_empty_api_key(self):
        result = vs.get_elevenlabs_voices("")
        self.assertEqual(result, [])

    @patch("app.services.voice.requests.get")
    def test_get_elevenlabs_voices_success(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "voices": [
                {"voice_id": "abc123", "name": "Adam"},
                {"voice_id": "def456", "name": "Rachel"},
            ]
        }
        result = vs.get_elevenlabs_voices("fake-api-key")
        self.assertEqual(result, [
            "elevenlabs:abc123:Adam",
            "elevenlabs:def456:Rachel",
        ])
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args
        self.assertIn("xi-api-key", call_kwargs.kwargs.get("headers", {}))

    @patch("app.services.voice.requests.get")
    def test_get_elevenlabs_voices_http_error(self, mock_get):
        mock_get.return_value.status_code = 401
        mock_get.return_value.text = "Unauthorized"
        result = vs.get_elevenlabs_voices("bad-key")
        self.assertEqual(result, [])

    @patch("app.services.voice.requests.get")
    def test_get_elevenlabs_voices_network_error(self, mock_get):
        import requests as req_lib
        mock_get.side_effect = req_lib.exceptions.ConnectionError("timeout")
        result = vs.get_elevenlabs_voices("fake-key")
        self.assertEqual(result, [])

    @patch("app.services.voice.requests.post")
    @patch("app.services.voice.AudioFileClip")
    @patch("app.services.voice.config")
    def test_elevenlabs_tts_success(self, mock_config, mock_clip_cls, mock_post):
        mock_config.elevenlabs.get.return_value = "fake-api-key"
        mock_post.return_value.status_code = 200
        mock_post.return_value.content = b"fake-mp3-bytes"
        mock_clip = mock_clip_cls.return_value.__enter__.return_value
        mock_clip_cls.return_value.duration = 3.0
        mock_clip_cls.return_value.close = lambda: None

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            out_path = f.name

        try:
            result = vs.elevenlabs_tts("Hello world", "abc123", out_path)
            self.assertIsNotNone(result)
            self.assertTrue(hasattr(result, "subs"))
            self.assertTrue(hasattr(result, "offset"))
        finally:
            if os.path.exists(out_path):
                os.remove(out_path)

    @patch("app.services.voice.config")
    def test_elevenlabs_tts_no_api_key(self, mock_config):
        mock_config.elevenlabs.get.return_value = ""
        result = vs.elevenlabs_tts("Hello", "abc123", "/tmp/test.mp3")
        self.assertIsNone(result)

    @patch("app.services.voice.config")
    def test_elevenlabs_tts_empty_text(self, mock_config):
        mock_config.elevenlabs.get.return_value = "fake-key"
        result = vs.elevenlabs_tts("  ", "abc123", "/tmp/test.mp3")
        self.assertIsNone(result)
```

- [ ] **Step 2: Run the new tests to verify they pass**

```bash
cd /Users/mantang/Desktop/Project/MoneyPrinterTurbo
python -m pytest test/services/test_voice.py::TestElevenLabsVoice -v
```

Expected: All tests PASS. If a test fails, fix the implementation in Task 2 before proceeding.

- [ ] **Step 3: Run the full voice test suite to check no regressions**

```bash
cd /Users/mantang/Desktop/Project/MoneyPrinterTurbo
python -m pytest test/services/test_voice.py -v
```

Expected: All existing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add test/services/test_voice.py
git commit -m "test: add unit tests for ElevenLabs TTS provider"
```

---

### Task 4: WebUI Integration

**Files:**
- Modify: `webui/Main.py`
  - Line ~949: `tts_servers` list — add ElevenLabs entry
  - Line ~983: voice loading branch — add ElevenLabs branch
  - Line ~1160: API key sections — add ElevenLabs section

**Interfaces:**
- Consumes: `voice.get_elevenlabs_voices(api_key)`, `voice.is_elevenlabs_voice(voice_name)` from Task 2
- Consumes: `config.elevenlabs` from Task 1

- [ ] **Step 1: Add ElevenLabs to `tts_servers` list (around line 949)**

Current:
```python
        tts_servers = [
            (voice.NO_VOICE_NAME, tr("No Voice")),
            ("azure-tts-v1", "Azure TTS V1"),
            ("azure-tts-v2", "Azure TTS V2"),
            ("siliconflow", "SiliconFlow TTS"),
            ("gemini-tts", "Google Gemini TTS"),
            ("mimo-tts", "Xiaomi MiMo TTS"),
        ]
```

Change to:
```python
        tts_servers = [
            (voice.NO_VOICE_NAME, tr("No Voice")),
            ("azure-tts-v1", "Azure TTS V1"),
            ("azure-tts-v2", "Azure TTS V2"),
            ("siliconflow", "SiliconFlow TTS"),
            ("gemini-tts", "Google Gemini TTS"),
            ("mimo-tts", "Xiaomi MiMo TTS"),
            ("elevenlabs", "ElevenLabs TTS"),
        ]
```

- [ ] **Step 2: Add ElevenLabs voice loading branch (around line 983)**

Current:
```python
        elif selected_tts_server == "mimo-tts":
            # 获取 Xiaomi MiMo TTS 的预置音色列表
            filtered_voices = voice.get_mimo_voices()
        else:
```

Change to:
```python
        elif selected_tts_server == "mimo-tts":
            # 获取 Xiaomi MiMo TTS 的预置音色列表
            filtered_voices = voice.get_mimo_voices()
        elif selected_tts_server == "elevenlabs":
            saved_elevenlabs_api_key = config.elevenlabs.get("api_key", "")
            cache_key = f"elevenlabs_voices_{saved_elevenlabs_api_key}"
            if cache_key not in st.session_state:
                st.session_state[cache_key] = voice.get_elevenlabs_voices(
                    saved_elevenlabs_api_key
                )
            filtered_voices = st.session_state[cache_key]
        else:
```

- [ ] **Step 3: Add ElevenLabs API key section (after the MiMo section, around line 1160)**

Current code ending the MiMo block:
```python
            config.app["mimo_api_key"] = mimo_api_key

        params.voice_volume = st.selectbox(
```

Add the ElevenLabs block between them:
```python
            config.app["mimo_api_key"] = mimo_api_key

        # ElevenLabs API key section
        if selected_tts_server == "elevenlabs" or (
            voice_name and voice.is_elevenlabs_voice(voice_name)
        ):
            saved_elevenlabs_api_key = config.elevenlabs.get("api_key", "")

            elevenlabs_api_key = st.text_input(
                tr("ElevenLabs API Key"),
                value=saved_elevenlabs_api_key,
                type="password",
                key="elevenlabs_api_key_input",
            )

            st.info(
                "ElevenLabs TTS Settings:\n"
                "- Get your API key at https://elevenlabs.io/app/settings/api-keys\n"
                "- Mark voices as ★ Favorite in the ElevenLabs voice library to make them appear here"
            )

            if elevenlabs_api_key != saved_elevenlabs_api_key:
                # Clear voice cache so new key fetches fresh voices
                for k in list(st.session_state.keys()):
                    if k.startswith("elevenlabs_voices_"):
                        del st.session_state[k]

            config.elevenlabs["api_key"] = elevenlabs_api_key

        params.voice_volume = st.selectbox(
```

- [ ] **Step 4: Verify import of `config.elevenlabs` is available in `Main.py`**

Check that `Main.py` already imports config:
```bash
grep -n "from app.config import config\|import config" /Users/mantang/Desktop/Project/MoneyPrinterTurbo/webui/Main.py | head -5
```

Expected: a line like `from app.config import config` — no change needed.

- [ ] **Step 5: Syntax check**

```bash
cd /Users/mantang/Desktop/Project/MoneyPrinterTurbo
python -c "import ast; ast.parse(open('webui/Main.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 6: Commit**

```bash
git add webui/Main.py
git commit -m "feat: add ElevenLabs TTS to WebUI audio settings"
```

---

## Verification

After all tasks are complete, do a final smoke test:

```bash
# 1. Run all voice tests
cd /Users/mantang/Desktop/Project/MoneyPrinterTurbo
python -m pytest test/services/test_voice.py -v

# 2. Start the WebUI and confirm ElevenLabs appears in TTS Servers dropdown
streamlit run webui/Main.py
```

In the WebUI:
1. Open the Audio Settings panel
2. Confirm "ElevenLabs TTS" appears in the TTS Servers dropdown
3. Select it — confirm API key input and info box appear
4. Enter a valid ElevenLabs API key — confirm favorite voices load in the voice dropdown
