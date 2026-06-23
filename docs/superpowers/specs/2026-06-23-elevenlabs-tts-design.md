# ElevenLabs TTS Integration

**Date:** 2026-06-23  
**Status:** Approved

## Overview

Add ElevenLabs as a TTS provider in MoneyPrinterTurbo's audio settings. Voices are fetched dynamically from the ElevenLabs API using the user's favorited voices. Integration uses direct HTTP requests (no SDK) to stay consistent with existing providers.

## Voice Name Format

```
elevenlabs:{voice_id}:{name}
```

Example: `elevenlabs:pNInz6obpgDQGcFmaJgB:Adam`

Consistent with the SiliconFlow pattern (`siliconflow:model:voice-Gender`).

## Files Changed

### `app/services/voice.py`

Three new functions + dispatcher update:

**`get_elevenlabs_voices(api_key: str) -> list[str]`**
- Calls `GET https://api.elevenlabs.io/v2/voices?is_favorite=true&page_size=100`
- Header: `xi-api-key: {api_key}`
- Returns list of `"elevenlabs:{voice_id}:{name}"` strings
- Returns empty list if api_key is empty or request fails

**`is_elevenlabs_voice(voice_name: str) -> bool`**
- Returns `voice_name.startswith("elevenlabs:")`

**`elevenlabs_tts(text, voice_id, voice_file, voice_rate, voice_volume) -> SubMaker | None`**
- Calls `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}`
- Request body:
  ```json
  {
    "text": "...",
    "model_id": "eleven_multilingual_v2",
    "voice_settings": {
      "stability": 0.5,
      "similarity_boost": 0.75,
      "style": 0.0,
      "use_speaker_boost": true
    }
  }
  ```
- Header: `xi-api-key: {api_key}`, `Content-Type: application/json`
- Saves response bytes to `voice_file` as MP3
- Returns SubMaker via `populate_legacy_submaker_with_full_text` (ElevenLabs standard endpoint does not return word-level timing)
- Retries 3 times on failure (consistent with SiliconFlow)

**`tts()` dispatcher update**
- Add `elif is_elevenlabs_voice(voice_name):` branch before the final `azure_tts_v1` fallback
- Parse `voice_id` from `voice_name.split(":")[1]`

### `webui/Main.py`

**TTS server list** — append `("elevenlabs", "ElevenLabs TTS")` to `tts_servers`.

**Voice loading branch** — add `elif selected_tts_server == "elevenlabs":` that calls `voice.get_elevenlabs_voices(api_key)`. Uses `st.session_state` to cache the result so the API is not called on every Streamlit re-render.

**API key section** — show a password `text_input` for ElevenLabs API key when `selected_tts_server == "elevenlabs"` or current `voice_name` is an ElevenLabs voice. Persist to `config.elevenlabs["api_key"]`. Include a link to `https://elevenlabs.io/app/settings/api-keys`.

### `app/config/config.py`

- Add module-level: `elevenlabs = _cfg.get("elevenlabs", {})`
- Update `save_config()` to include `_cfg["elevenlabs"] = elevenlabs`

### `config.example.toml`

Add section:

```toml
[elevenlabs]
# ElevenLabs API Key
# Get your API key at https://elevenlabs.io/app/settings/api-keys
# Mark voices as favorites in the ElevenLabs voice library to make them appear here.
api_key = ""
```

## Error Handling

- Empty API key → log error, return empty voice list / None from TTS
- HTTP error from voices endpoint → log warning, return empty list (don't crash UI)
- HTTP error from TTS endpoint → log error, retry up to 3 times, return None on final failure

## Out of Scope

- ElevenLabs voice cloning or voice design
- Streaming TTS (project uses file-based audio throughout)
- Speech rate / volume mapping to ElevenLabs-specific parameters (use defaults)
