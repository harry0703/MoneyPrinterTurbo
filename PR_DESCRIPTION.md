## Summary
Adds an option to use each source clip in full instead of always splitting it into `max_clip_duration`-second segments — scoped to local video materials for this iteration.

## Changes
- `app/models/schema.py`: `VideoParams.video_clip_duration` now accepts `int >= 1` or the literal `"full"`, validated via a `field_validator` (case/whitespace-insensitive, rejects `bool`/`0`/negative/other strings).
- `app/services/video.py`: `combine_videos()` treats `max_clip_duration="full"` as "use the whole source clip, skip splitting and the post-hoc duration truncation"; numeric values keep the existing split behavior unchanged.
- `webui/Main.py`: "Full clip / Unlimited" option added to the Clip Duration selectbox, restricted to `video_source == "local"` (cloud generation sources — WaveSpeed/Seedance/OFox/MiniMax — keep the existing numeric-only list, since they generate fixed-duration clips server-side and validate `clip_duration` as a positive integer).
- `app/services/test/test_video.py`: added coverage for `VideoParams` validation (accept/reject cases + preset round-trip) and for `combine_videos()` full-clip behavior vs. the existing split behavior.

## Not in this PR
- `"full"` for Pexels/Pixabay/Coverr and other downloaded-footage sources — planned as a follow-up once verified.
- i18n translation entries for "Full clip / Unlimited" label.

## Testing
- `python -m py_compile` on all changed files.
- `pytest app/services/test/test_video.py` (please re-run in CI/locally — not runnable in the sandbox used to prepare this patch).
