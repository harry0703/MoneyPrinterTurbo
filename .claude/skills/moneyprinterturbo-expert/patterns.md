# Engineering patterns this repo teaches

Reusable techniques worth applying elsewhere, each with its canonical location
in this codebase.

## 1. Thread-safe round-robin API key rotation (`app/services/material.py`)

Accept a string **or** list in config; rotate under a lock so concurrent
download threads spread load across keys without rate-limit coordination:

```python
_api_key_counter = 0
_api_key_lock = threading.Lock()

def get_api_key(cfg_key):
    api_keys = config.app.get(cfg_key)
    if isinstance(api_keys, str):
        return api_keys
    with _api_key_lock:
        global _api_key_counter
        _api_key_counter += 1
        return api_keys[_api_key_counter % len(api_keys)]
```

## 2. Hardware codec with runtime detection + fallback (`app/services/video.py`)

Never assume `h264_nvenc`/`h264_amf`/`h264_qsv` exist. Probe once
(`@lru_cache` over `ffmpeg -hide_banner -encoders`), try the preferred codec,
and on *any* failure mark it disabled for the session
(`_disable_runtime_video_codec`) and rewrite with `libx264`
(`_fallback_write_videofile`). Detection passing does not guarantee encoding
succeeds (driver/VRAM issues), hence the second layer.

## 3. Timeout watchdog for a blocking generator (`app/services/voice.py`)

`edge_tts`'s `stream_sync()` can hang forever on network stalls. Wrap it in a
**daemon thread** producing into a `queue.Queue`, while the caller consumes
with a monotonic deadline:

```python
thread = threading.Thread(target=_produce_chunks, daemon=True)  # daemon: dies with process
deadline = time.monotonic() + timeout_seconds
while True:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError(...)
    item_type, payload = stream_queue.get(timeout=min(0.5, remaining))
```

The short per-`get` timeout keeps the loop responsive to the global deadline.

## 4. Word-level subtitle timing from TTS (`voice.py` + `subtitle.py`)

- Primary: edge-tts `WordBoundary` events → `SubMaker` parallel arrays
  (`subs` words, `offset` in 100-ns units; seconds = `offset / 10**7`).
- Engines without boundaries: synthesize timings by splitting text on a
  multilingual punctuation list (`const.PUNCTUATIONS` — Latin, CJK, Arabic)
  and distributing measured audio duration proportionally to character counts
  (`populate_legacy_submaker_with_full_text`).
- Post-hoc correction: `subtitle.correct()` merges ASR/boundary fragments
  until normalized Levenshtein similarity to each script sentence exceeds 0.8,
  so displayed text equals the script verbatim while keeping the timing.

## 5. Language-aware reading-speed estimation (`voice.py::estimate_no_voice_duration`)

For silent (subtitle-only) videos, estimate duration from text:
CJK chars / 4.2 s + English words / 2.7 s + other chars / 4.0 s
+ 0.35 s per sentence, floor 3 s. Cheap, no model needed.

## 6. Aspect-ratio normalization via letterboxing (`video.py`)

Compare source vs target ratio; scale to fit the constraining dimension,
center over a black `ColorClip`, composite. Avoids distortion when packing
16:9 stock footage into 9:16 shorts:

```python
scale = video_w / clip_w if clip_ratio > video_ratio else video_h / clip_h
bg = ColorClip(size=(video_w, video_h), color=(0, 0, 0)).with_duration(d)
clip = CompositeVideoClip([bg, clip.resized(new_size).with_position("center")])
```

## 7. Anti-repetition clip selection (`video.py::_prioritize_unique_source_clips`)

When looping limited material to fill audio duration: group chunks by source
file, take the longest chunk of each distinct source first, shuffle the rest.
Maximizes visual variety before any source repeats.

## 8. FFmpeg concat demuxer for heterogeneous clips (`video.py::concat_video_clips_with_ffmpeg`)

Write a `file '...'` list (escape quotes in paths), run
`ffmpeg -f concat -safe 0 -i list.txt -c:v <codec> -c:a aac`. Re-encode rather
than `-c copy` because per-clip parameters differ. Far faster and more
memory-stable than concatenating inside MoviePy.

## 9. Rounded subtitle backgrounds via PIL (`video.py::_rounded_subtitle_background_clip`)

MoviePy can't draw rounded rectangles; pre-render with
`PIL.ImageDraw.rounded_rectangle()` into an RGBA image, wrap as `ImageClip`,
layer under the `TextClip` in a `CompositeVideoClip`.

## 10. Resumable pipeline via `stop_at` checkpoints (`task.py::start`)

One linear orchestrator with named early-exit points (`script`, `terms`,
`audio`, `subtitle`, `materials`, `video`) lets multiple API products
(/videos, /audio, /subtitle) share a single code path, and makes each stage
independently testable.

## 11. Container-aware service discovery (`app/config/config.py`)

Detect containerization via `/.dockerenv`, `/run/.containerenv`,
`/proc/1/cgroup`; rewrite `localhost` Ollama URLs to `host.docker.internal`
or the gateway from `/proc/net/route` on native Linux Docker.

## 12. Path-traversal-safe file serving (`app/utils/file_security.py`)

`resolve_path_within_directory(base_dir, unsafe_path)` resolves and verifies
the real path is inside `base_dir` before any read/write — applied to every
upload/stream/download endpoint.
