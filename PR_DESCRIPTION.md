## Summary

**1. `app/services/video.py` — `combine_videos()**`

* **Goal:** Allow the use of the entire downloaded footage instead of splitting it into fixed-length segments, controlled by the `"full"` value passed from the UI.
* Added flag: `use_full_clip = isinstance(max_clip_duration, str) and max_clip_duration.strip().lower() == "full"`.
* Loop building `subclipped_items`: if `use_full_clip` → adds the entire clip (`start_time=0`, `end_time=clip_duration`) without splitting. Otherwise, the original logic splitting into segments of `source_clip_duration` seconds applies (restored from the version prior to our first change).
* Second location trimming an individual clip: `if not use_full_clip and clip.duration > max_clip_duration: clip = clip.subclipped(0, max_clip_duration)` — trimming only applies when `"full"` is not selected.

**2. `webui/Main.py**`

* **Goal:** Add a "use full clip" option in the UI alongside existing numerical values.
* Options list (~line 4634): `[2, 3, 4, 5, 6, 7, 8, 9, 10]` → `[2, 3, 4, 5, 6, 7, 8, 9, 10, "full"]` (only for sources other than `metaso_minimax` — MiniMax retains its own time range).
* `format_func` in `stable_selectbox` for `video_clip_duration_select` — displays `"Full clip / Unlimited"` instead of `"full"`, and the rest as `"X sec"`.
* New helper function `_resolve_estimate_clip_duration(video_clip_duration)` — safely converts the value to an integer, with a fallback to `5` when the value is `"full"` or invalid.
* Replaced `clip_duration = max(int(params.video_clip_duration or 1), 1)` with `clip_duration = _resolve_estimate_clip_duration(params.video_clip_duration)` in four locations: `_render_wavespeed_video_settings`, `_render_seedance_video_settings`, `_render_ofox_video_settings`, and `_render_metaso_minimax_video_settings` — without this, selecting `"full"` for these sources would trigger a `ValueError` (as `int("full")` throws an exception).

FIX:

<img width="1920" height="931" alt="Bez tytułu" src="https://github.com/user-attachments/assets/f0c42947-09ef-42ff-8863-ffe92b6c61af" />




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
- `pytest /test/test_video.py` (please re-run in CI/locally — not runnable in the sandbox used to prepare this patch).



##Tests: 

python -m pytest test/services/test_video.py -k "clip_duration or full_option or ClipDurationValidation" -v
================================================= test session starts =================================================
platform win32 -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0 -- C:\Users\abc\AppData\Local\Python\pythoncore-3.14-64\python.exe
cachedir: .pytest_cache
rootdir: D:\mp2\MoneyPrinterTurbo
configfile: pyproject.toml
collected 63 items / 51 deselected / 12 selected

test/services/test_video.py::TestVideoService::test_combine_videos_full_option_is_case_and_whitespace_insensitive SUBPASSED(max_clip_duration='Full') [  8%]
test/services/test_video.py::TestVideoService::test_combine_videos_full_option_is_case_and_whitespace_insensitive SUBPASSED(max_clip_duration='  full  ') [  8%]
test/services/test_video.py::TestVideoService::test_combine_videos_full_option_is_case_and_whitespace_insensitive SUBPASSED(max_clip_duration='FULL') [  8%]
test/services/test_video.py::TestVideoService::test_combine_videos_full_option_is_case_and_whitespace_insensitive PASSED [  8%]
test/services/test_video.py::TestVideoService::test_combine_videos_full_option_uses_entire_source_without_splitting PASSED [ 16%]
test/services/test_video.py::TestVideoClipDurationValidation::test_accepts_full_literal PASSED                   [ 25%]
test/services/test_video.py::TestVideoClipDurationValidation::test_accepts_numeric_string PASSED                 [ 33%]
test/services/test_video.py::TestVideoClipDurationValidation::test_accepts_positive_integer PASSED               [ 41%]
test/services/test_video.py::TestVideoClipDurationValidation::test_normalizes_case_and_whitespace_for_full SUBPASSED(raw_value='Full') [ 50%]
test/services/test_video.py::TestVideoClipDurationValidation::test_normalizes_case_and_whitespace_for_full SUBPASSED(raw_value='  full  ') [ 50%]
test/services/test_video.py::TestVideoClipDurationValidation::test_normalizes_case_and_whitespace_for_full SUBPASSED(raw_value='FULL') [ 50%]
test/services/test_video.py::TestVideoClipDurationValidation::test_normalizes_case_and_whitespace_for_full PASSED [ 50%]
test/services/test_video.py::TestVideoClipDurationValidation::test_preset_round_trip_preserves_full PASSED       [ 58%]
test/services/test_video.py::TestVideoClipDurationValidation::test_preset_round_trip_preserves_numeric_value PASSED [ 66%]
test/services/test_video.py::TestVideoClipDurationValidation::test_rejects_arbitrary_string PASSED               [ 75%]
test/services/test_video.py::TestVideoClipDurationValidation::test_rejects_boolean PASSED                        [ 83%]
test/services/test_video.py::TestVideoClipDurationValidation::test_rejects_negative_integer PASSED               [ 91%]
test/services/test_video.py::TestVideoClipDurationValidation::test_rejects_zero PASSED                           [100%]

================================================== warnings summary ===================================================
test/services/test_video.py::TestVideoClipDurationValidation::test_preset_round_trip_preserves_full
test/services/test_video.py::TestVideoClipDurationValidation::test_preset_round_trip_preserves_numeric_value
  C:\Users\abc\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\pydantic\main.py:475: UserWarning: Pydantic serializer warnings:
    PydanticSerializationUnexpectedValue(Expected `enum` - serialized value may not be as expected [field_name='video_aspect', input_value='9:16', input_type=str])
    PydanticSerializationUnexpectedValue(Expected `enum` - serialized value may not be as expected [field_name='video_concat_mode', input_value='random', input_type=str])
    return self.__pydantic_serializer__.to_python(
