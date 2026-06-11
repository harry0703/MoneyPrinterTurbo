# Pipeline deep dive

Orchestrated by `app/services/task.py::start(task_id, params: VideoParams, stop_at="video")`.
Stage helpers in the same file: `generate_script`, `generate_terms`,
`generate_audio`, `generate_subtitle`, `get_video_materials`,
`generate_final_videos`. Progress is written via
`app.services.state` after each stage (5 → 10 → 20 → 30 → 50 → 100).
A failed stage sets `TASK_STATE_FAILED` and aborts; later stages assume
earlier outputs exist.

## 1. Script generation — `app/services/llm.py`

`generate_script(video_subject, language, paragraph_number, video_script_prompt, custom_system_prompt) -> str`

- Default system prompt enforces: plain text only (no markdown/titles), respond
  in the language of the subject, no "narrator says" stage directions, return a
  string not JSON. These constraints exist because the output goes straight to
  TTS and subtitle splitting.
- `custom_system_prompt` (≤8000 chars) replaces the system role entirely;
  `video_script_prompt` (≤2000 chars) appends user-level instructions. Both are
  surfaced in WebUI and `VideoParams`.
- Post-processing strips `<think>...</think>` blocks (reasoning models like
  DeepSeek-R1) and markdown artifacts (`*`, `#`, brackets).
- `_generate_response()` is the provider router: a conditional chain over
  `config.app.llm_provider`. OpenAI-compatible providers share the OpenAI SDK
  with a custom `base_url`; Gemini, Qwen/DashScope, Ernie, g4f, Ollama and
  Pollinations have dedicated branches. Retries up to 5 times.

## 2. Search terms — `llm.py::generate_terms(video_subject, video_script, amount=5) -> List[str]`

Prompts the LLM for a JSON array of 1–3-word **English** terms (stock APIs
search in English regardless of script language). Parses/validates JSON,
retries up to 5 times on malformed output.

## 3. TTS audio — `app/services/voice.py` (~1500 lines)

`tts(text, voice_name, voice_rate, voice_file, voice_volume) -> SubMaker | None`
routes on the voice-name prefix:

| Prefix / form | Engine | Function |
|---|---|---|
| `zh-CN-XiaoxiaoNeural-Female` etc. | edge-tts (free, 400+ voices) | `azure_tts_v1()` |
| `azure-tts-v2:` style (V2 names) | Azure Speech SDK (paid, needs `[azure]` keys) | `azure_tts_v2()` |
| `gemini:Zephyr-Female` | Gemini TTS | `gemini_tts()` |
| `siliconflow:FunAudioLLM/CosyVoice2-0.5B:alex` | SiliconFlow CosyVoice2 | `siliconflow_tts()` |
| `mimo:Mia-Female` | Xiaomi MiMo (optional style prompt `mimo_tts_style_prompt`) | `mimo_tts()` |
| no-voice sentinel | silent track | `is_no_voice()` + `estimate_no_voice_duration()` |

Key details:

- `voice_rate` is a multiplier converted to edge-tts percentage (1.2 → "+20%").
- edge-tts streaming is wrapped in a daemon thread + `queue.Queue` with a
  deadline (`edge_tts_timeout`, default 30 s) because `stream_sync()` can hang
  on network issues (see patterns.md).
- **SubMaker** captures `WordBoundary` events: parallel arrays `subs` (words)
  and `offset` (timestamps in 100-nanosecond units). This is the timing source
  for subtitles.
- Non-edge engines don't emit word boundaries, so
  `populate_legacy_submaker_with_full_text()` synthesizes timings: split text
  on `const.PUNCTUATIONS` (Latin + CJK + Arabic marks) and distribute the real
  audio duration proportionally to character counts.
- No-voice duration estimate: CJK chars / 4.2 s + English words / 2.7 s +
  other chars / 4.0 s + 0.35 s per sentence, min 3 s.
- `get_audio_duration(target: str | SubMaker) -> float`.

## 4. Subtitles — `voice.py::create_subtitle()` and `app/services/subtitle.py`

Two providers, chosen by `subtitle_provider` in config:

- **`edge`** (default): `create_subtitle(sub_maker, text, subtitle_file)`
  converts SubMaker word timings to SRT. Timestamp conversion:
  `time_unit / 10**7` seconds → `HH:MM:SS,mmm`.
- **`whisper`** (fallback / for custom audio): `subtitle.create(audio_file, subtitle_file)`
  uses `faster_whisper` (model size / device / compute_type from `[whisper]`
  config) with word-level timestamps, splitting lines on punctuation.

`subtitle.correct(subtitle_file, video_script)` re-aligns generated lines to
the original script sentences: normalized Levenshtein similarity, merging
subtitle fragments until similarity > 0.8 against each script sentence. This
fixes ASR/boundary drift so on-screen text matches the script verbatim.

## 5. Material sourcing — `app/services/material.py`

`download_videos(task_id, search_terms, source, video_aspect, audio_duration, max_clip_duration) -> List[str]`

- Sources: `search_videos_pexels()`, `search_videos_pixabay()`,
  `search_videos_coverr()`, or `local` (files from `material_directory`,
  preprocessed by `video.preprocess_video()` — images get a duration and become
  clips too).
- Queries filter by orientation matching `video_aspect` and by minimum
  duration; downloads run multi-threaded into the shared cache
  (`storage/cache_videos/`, keyed by URL hash) so repeated tasks reuse files.
- Multiple API keys per provider (`pexels_api_keys = [...]`) are rotated
  round-robin under a `threading.Lock` (see patterns.md).
- Downloads stop once accumulated material duration covers `audio_duration`.

## 6. Combine — `app/services/video.py::combine_videos()`

`combine_videos(combined_video_path, video_paths, audio_file, video_aspect, video_concat_mode, video_transition_mode, max_clip_duration=5, threads=2)`

1. **Segmentation**: each source video is cut into ≤`max_clip_duration` chunks.
   `sequential` mode keeps only the first chunk per source; `random` keeps all.
2. **Anti-repetition**: `_prioritize_unique_source_clips()` picks the longest
   chunk from each distinct source first, then shuffles the remainder — so a
   video built from few sources still varies visually.
3. **Duration matching**: clips are cycled (`itertools.cycle`) until total
   video duration ≥ audio duration.
4. **Per-clip processing**: aspect-ratio correction (direct resize when ratios
   match; otherwise scale-to-fit + center on a black `ColorClip` letterbox),
   then optional 1-second transition from
   `app/services/utils/video_effects.py` (`fadein/fadeout/slidein/slideout`,
   `Shuffle` = random pick). Each processed clip is written to
   `temp-clip-{i}.mp4`.
5. **Concat**: `concat_video_clips_with_ffmpeg()` writes an FFmpeg concat
   demuxer list (`file '...'` lines, paths escaped by
   `_escape_ffmpeg_concat_path`) and runs
   `ffmpeg -f concat -safe 0 -i list.txt -c:v {codec} -c:a aac ...`.
   Re-encoding (not stream copy) is required because clips have heterogeneous
   encodings. Hardware codec failures fall back to libx264.

## 7. Final compositing — `video.py::generate_video(video_path, audio_path, subtitle_path, output_file, params)`

- Loads combined video + narration (`afx.MultiplyVolume(voice_volume)`).
- **Subtitles**: `file_to_subtitles()` parses SRT into
  `(idx, "start --> end", text)`; each entry becomes a `TextClip` via
  `create_text_clip()`:
  - `wrap_text()` wraps to ≤90% of video width given font/size.
  - Styling from `VideoParams`: `font_name` (file in `resource/fonts/`),
    `font_size`, `text_fore_color`, `stroke_color`/`stroke_width`,
    `text_background_color` (bool or hex), optional
    `rounded_subtitle_background` (PIL-rendered rounded rect, see patterns.md).
  - Position: `bottom` → y = 95% of height minus clip height; `top` → 5%;
    `custom` → `custom_position` percent from top, clamped to margins;
    otherwise centered.
- **BGM**: `get_bgm_file()` resolves `bgm_type="random"` to a random file in
  `resource/songs/`; volume via `bgm_volume` (default 0.2), stretched/trimmed
  to video duration.
- Composite: `CompositeVideoClip([video, *subtitle_clips])` +
  `CompositeAudioClip([narration, bgm])`, written at 30 fps, AAC 192k, with
  codec fallback. Output `final-{n}.mp4`; `video_count` > 1 produces multiple
  variants (different clip ordering).

## 8. Optional cross-posting — `app/services/upload_post.py`

Integration with upload-post.com to auto-publish finished videos to
TikTok/Instagram when configured.
