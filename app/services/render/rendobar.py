"""Optional cloud render backend.

Renders the reel on Rendobar's API instead of locally, so the heavy MoviePy and
ffmpeg work does not run on (or crash) the user's machine. The local backend
stays the default; this runs only when the user selects it and sets an API key.

Stock clips (Pexels, Pixabay) are passed to the cloud by URL, so only true local
files (voiceover, music, custom clips) are uploaded. Those uploads go to a
third-party service and each render spends credits. The cloud output is visually
equivalent to the local render, not a pixel clone. Uses the standard library plus
requests, which the project already depends on.
"""

import os
import random
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional, Tuple

import requests
from loguru import logger

from app.config import config
from app.models.schema import VideoAspect
from app.services.render.base import RenderBackend, RenderContext

BASE_URL = os.environ.get("RENDOBAR_API_BASE", "https://api.rendobar.com")
POLL_INTERVAL_SEC = 5
POLL_TIMEOUT_SEC = 900
UPLOAD_CONCURRENCY = 4
MAX_RETRIES = 4
TRANSIENT_STATUS = {429, 500, 502, 503, 504}  # worth retrying, not a real failure


class RendobarError(RuntimeError):
    pass


def _api_key() -> str:
    return (
        config.app.get("rendobar_api_key")
        or os.environ.get("RENDOBAR_API_KEY")
        or ""
    ).strip()


def rendobar_eligible(params) -> bool:
    """True when the backend can serve the job, i.e. an API key is set."""
    return bool(_api_key())


def _headers() -> dict:
    return {"Authorization": f"Bearer {_api_key()}"}


def _check(resp: requests.Response, ctx: str) -> dict:
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if not resp.ok or (isinstance(body, dict) and "error" in body):
        err = body.get("error", {}) if isinstance(body, dict) else {}
        code = err.get("code", f"HTTP {resp.status_code}")
        # Fall back to the status reason, not resp.text, so an HTML error page
        # (e.g. a 503 from the edge) doesn't end up dumped into the log.
        message = err.get("message") or resp.reason or f"HTTP {resp.status_code}"
        raise RendobarError(f"{ctx} failed [{code}]: {message}")
    return body


def _send(make_request, ctx: str) -> requests.Response:
    """Send a request, retrying transient HTTP and network errors with backoff.

    `make_request` is a callable that performs the request and returns the
    response, so it can reopen a file stream on each retry.
    """
    last = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = make_request()
            if resp.status_code not in TRANSIENT_STATUS:
                return resp
            last = f"HTTP {resp.status_code} {resp.reason}"
        except requests.exceptions.RequestException as e:
            last = str(e)
        wait = min(2 ** attempt, 30)
        logger.warning(f"{ctx}: {last}, retrying in {wait}s")
        time.sleep(wait)
    raise RendobarError(f"{ctx} failed after {MAX_RETRIES} tries: {last}")


_progress_lock = threading.Lock()


def _upload_one(path: str) -> str:
    file_path = Path(path)
    if not file_path.is_file():
        raise RendobarError(f"input not found: {path}")

    def post():
        with file_path.open("rb") as stream:
            return requests.post(
                f"{BASE_URL}/uploads",
                headers=_headers(),
                params={"filename": file_path.name},
                data=stream,
                timeout=300,
            )

    resp = _send(post, f"upload of {file_path.name}")
    url = _check(resp, f"upload of {file_path.name}").get("data", {}).get("downloadUrl")
    if not url:
        raise RendobarError(f"upload of {file_path.name} returned no downloadUrl")
    return url


def _upload_all(paths: List[str]) -> List[str]:
    """Upload many files concurrently (bounded), keeping input order."""
    total = len(paths)
    if total == 0:
        return []
    done = {"n": 0}

    def _job(idx_path):
        idx, p = idx_path
        url = _upload_one(p)
        with _progress_lock:
            done["n"] += 1
            logger.info(f"uploaded {done['n']}/{total}")
        return idx, url

    results = [""] * total
    with ThreadPoolExecutor(max_workers=min(UPLOAD_CONCURRENCY, total)) as ex:
        for idx, url in ex.map(_job, list(enumerate(paths))):
            results[idx] = url
    return results


def _create_job(job_type: str, inputs: dict, params: dict) -> str:
    def post():
        return requests.post(
            f"{BASE_URL}/jobs",
            headers=_headers(),
            json={"type": job_type, "inputs": inputs, "params": params},
            timeout=60,
        )

    job_id = _check(_send(post, f"create {job_type} job"), f"create {job_type} job").get("data", {}).get("id")
    if not job_id:
        raise RendobarError(f"create {job_type} job returned no job id")
    return job_id


def _poll(job_id: str) -> str:
    deadline = time.monotonic() + POLL_TIMEOUT_SEC
    while time.monotonic() < deadline:
        # The job is running server-side, so a transient blip (network, 5xx)
        # should not end it. Keep polling until it reports a terminal status or
        # the overall timeout is reached.
        try:
            resp = requests.get(f"{BASE_URL}/jobs/{job_id}", headers=_headers(), timeout=60)
        except requests.exceptions.RequestException as e:
            logger.warning(f"poll job {job_id}: {e}, retrying")
            time.sleep(POLL_INTERVAL_SEC)
            continue
        if resp.status_code in TRANSIENT_STATUS:
            logger.warning(f"poll job {job_id}: HTTP {resp.status_code}, retrying")
            time.sleep(POLL_INTERVAL_SEC)
            continue
        data = _check(resp, f"poll job {job_id}").get("data", {})
        status = data.get("status")
        if status == "complete":
            url = data.get("outputUrl")
            if not url:
                raise RendobarError(f"job {job_id} completed but returned no outputUrl")
            return url
        if status in ("failed", "cancelled"):
            code = data.get("errorCode") or status
            message = data.get("errorMessage") or f"job {status}"
            raise RendobarError(f"job {job_id} {status} [{code}]: {message}")
        time.sleep(POLL_INTERVAL_SEC)
    raise RendobarError(f"job {job_id} did not finish within {POLL_TIMEOUT_SEC}s")


def _download(url: str, output: str) -> None:
    out = Path(output)
    if out.parent and not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for attempt in range(MAX_RETRIES):
        try:
            with requests.get(url, stream=True, timeout=300) as resp:
                if resp.status_code in TRANSIENT_STATUS:
                    last = f"HTTP {resp.status_code} {resp.reason}"
                elif not resp.ok:
                    raise RendobarError(f"download failed: HTTP {resp.status_code}")
                else:
                    with out.open("wb") as handle:
                        for chunk in resp.iter_content(chunk_size=1 << 16):
                            if chunk:
                                handle.write(chunk)
                    return
        except requests.exceptions.RequestException as e:
            last = str(e)
        wait = min(2 ** attempt, 30)
        logger.warning(f"download: {last}, retrying in {wait}s")
        time.sleep(wait)
    raise RendobarError(f"download failed after {MAX_RETRIES} tries: {last}")


def _slide_offset(mode: str, side: str, w: int, h: int, t: float, s: float):
    # Linear position over t seconds, matching video_effects.py's slide. Returns
    # the ffmpeg overlay (x, y) expressions, where t is the frame time.
    if mode == "SlideIn":
        table = {
            "left": (f"if(lt(t,{t}),-{w}+{w}*t/{t},0)", "0"),
            "right": (f"if(lt(t,{t}),{w}-{w}*t/{t},0)", "0"),
            "top": ("0", f"if(lt(t,{t}),-{h}+{h}*t/{t},0)"),
            "bottom": ("0", f"if(lt(t,{t}),{h}-{h}*t/{t},0)"),
        }
    else:  # SlideOut
        table = {
            "left": (f"if(gt(t,{s}),-{w}*(t-{s})/{t},0)", "0"),
            "right": (f"if(gt(t,{s}),{w}*(t-{s})/{t},0)", "0"),
            "top": ("0", f"if(gt(t,{s}),-{h}*(t-{s})/{t},0)"),
            "bottom": ("0", f"if(gt(t,{s}),{h}*(t-{s})/{t},0)"),
        }
    return table[side]


def _clip_chain(idx, cover, mode, clip_duration, width, height, rng):
    # Filter statements for one clip, ending at label [v{idx}], reproducing
    # MoviePy's per-clip transition: a 1s fade or slide, then plain concat.
    label = f"v{idx}"
    if mode == "Shuffle":
        mode = rng.choice(["FadeIn", "FadeOut", "SlideIn", "SlideOut"])
    t = min(1.0, clip_duration)
    s = clip_duration - t
    if mode == "FadeIn":
        return [f"[{idx}:v]{cover},fade=t=in:st=0:d={t}[{label}]"]
    if mode == "FadeOut":
        return [f"[{idx}:v]{cover},fade=t=out:st={s}:d={t}[{label}]"]
    if mode in ("SlideIn", "SlideOut"):
        side = rng.choice(["left", "right", "top", "bottom"])
        x, y = _slide_offset(mode, side, width, height, t, s)
        return [
            f"[{idx}:v]{cover}[c{idx}]",
            f"color=black:s={width}x{height}:d={clip_duration}[bg{idx}]",
            f"[bg{idx}][c{idx}]overlay=x='{x}':y='{y}'[{label}]",
        ]
    return [f"[{idx}:v]{cover}[{label}]"]  # None or unknown


def _build_command(clip_urls, voiceover_url, music_url, width, height,
                   clip_duration, voice_volume, bgm_volume, transition=None) -> str:
    """Build the raw.ffmpeg command. Each clip is trimmed to clip_duration, its
    timestamps reset, then scaled and center-cropped to fill the frame, with the
    transition applied per clip, before all clips are concatenated. The voiceover
    drives length; music is ducked under it.
    """
    inputs = [f'-i "{u}"' for u in clip_urls]
    inputs.append(f'-i "{voiceover_url}"')
    voice_idx = len(clip_urls)
    if music_url:
        inputs.append(f'-i "{music_url}"')
        music_idx = voice_idx + 1

    cover = (
        f"trim=duration={clip_duration},setpts=PTS-STARTPTS,"
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1"
    )
    mode = getattr(transition, "value", transition)
    rng = random.Random()
    parts = []
    for i in range(len(clip_urls)):
        parts.extend(_clip_chain(i, cover, mode, clip_duration, width, height, rng))
    concat_in = "".join(f"[v{i}]" for i in range(len(clip_urls)))
    parts.append(f"{concat_in}concat=n={len(clip_urls)}:v=1:a=0[vout]")

    if music_url:
        parts.append(f"[{voice_idx}:a]volume={voice_volume}[vo]")
        parts.append(f"[{music_idx}:a]volume={bgm_volume}[bg]")
        parts.append("[vo][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]")
    else:
        parts.append(f"[{voice_idx}:a]volume={voice_volume}[aout]")

    filtergraph = ";".join(parts)
    return (
        "ffmpeg " + " ".join(inputs)
        + f' -filter_complex "{filtergraph}"'
        + ' -map "[vout]" -map "[aout]"'
        + " -c:v libx264 -preset veryfast -pix_fmt yuv420p"
        + " -c:a aac -b:a 192k -shortest output.mp4"
    )


def _is_remote(path) -> bool:
    url = getattr(path, "source_url", "")
    return isinstance(url, str) and url.startswith(("http://", "https://"))


def _local_font_path(font_name: str) -> Optional[str]:
    # Path to the bundled font file, uploaded so the cloud renders the exact face.
    # Returns None for a blank or missing font.
    if not font_name:
        return None
    try:
        from app.utils import utils
        path = os.path.join(utils.font_dir(), font_name)
    except Exception:
        return None
    return path if os.path.isfile(path) else None


def _map_subtitle_settings(params, height: int) -> dict:
    """Translate the Subtitle Settings into caption.burn params.

    Used only on the fallback path when no font file is available; the font, size,
    color, outline, position and box carry over. Rounded corners aren't represented
    here, the box is square.
    """
    pos_raw = getattr(params, "subtitle_position", "bottom")
    if pos_raw == "top":
        position, margin_v = "top", round(height * 0.05)
    elif pos_raw == "center":
        position, margin_v = "center", 0
    elif pos_raw == "custom":
        # custom_position is a top-down percentage; convert to a bottom margin.
        cp = float(getattr(params, "custom_position", 70.0) or 70.0)
        position, margin_v = "bottom", max(10, round((1.0 - cp / 100.0) * height))
    else:
        position, margin_v = "bottom", round(height * 0.05)

    box_enabled = bool(getattr(params, "text_background_color", False))
    burn = {
        "fontSize": int(getattr(params, "font_size", 48) or 48),
        "fontColor": getattr(params, "text_fore_color", "#FFFFFF") or "#FFFFFF",
        "outlineColor": getattr(params, "stroke_color", "#000000") or "#000000",
        "outlineWidth": float(getattr(params, "stroke_width", 2) or 2),
        "position": position,
        "alignment": "center",
        "marginV": margin_v,
        "boxEnabled": box_enabled,
        "shadow": 0,  # MoviePy draws no drop shadow
    }
    # Family name (extension stripped); ignored when a font file is uploaded.
    font = getattr(params, "font_name", "") or ""
    if font:
        burn["fontFamily"] = font.rsplit(".", 1)[0]
    if box_enabled:
        bg = getattr(params, "text_background_color", True)
        burn["boxColor"] = bg if isinstance(bg, str) and bg.startswith("#") else "#000000"
        rounded = bool(getattr(params, "rounded_subtitle_background", False))
        burn["boxOpacity"] = 0.55 if rounded else 1.0
    return burn


class RendobarRenderBackend(RenderBackend):
    name = "rendobar"

    def render(self, ctx: RenderContext) -> None:
        params = ctx.params
        width, height = VideoAspect(params.video_aspect).to_resolution()
        clip_duration = int(getattr(params, "video_clip_duration", 5) or 5)

        # Stock clips go by URL; only true local files are uploaded.
        clip_refs: List[Optional[str]] = []
        local_clips: List[Tuple[int, str]] = []
        for i, clip in enumerate(ctx.video_paths):
            if _is_remote(clip):
                clip_refs.append(clip.source_url)
            else:
                clip_refs.append(None)
                local_clips.append((i, str(clip)))

        music_path = None
        if getattr(params, "bgm_volume", 0):
            try:
                from app.services.video import get_bgm_file
                music_path = get_bgm_file(bgm_type=params.bgm_type, bgm_file=params.bgm_file)
            except Exception as e:
                logger.warning(f"skipping background music: {e}")
                music_path = None

        to_upload = [p for _, p in local_clips] + [ctx.audio_file]
        if music_path:
            to_upload.append(music_path)
        logger.info(
            f"{len(clip_refs) - len(local_clips)} clips by url, "
            f"uploading {len(to_upload)} local files"
        )
        uploaded = _upload_all(to_upload)
        for (i, _), url in zip(local_clips, uploaded[: len(local_clips)]):
            clip_refs[i] = url
        voiceover_url = uploaded[len(local_clips)]
        music_url = uploaded[len(local_clips) + 1] if music_path else None

        # random concat = shuffle the clip order (and subset, when there are more
        # than needed); sequential keeps the download order.
        concat_mode = getattr(params, "video_concat_mode", "random")
        if getattr(concat_mode, "value", concat_mode) == "random":
            random.shuffle(clip_refs)

        command = _build_command(
            clip_refs, voiceover_url, music_url, width, height, clip_duration,
            getattr(params, "voice_volume", 1.0),
            getattr(params, "bgm_volume", 0.2),
            getattr(params, "video_transition_mode", None),
        )
        logger.info("rendering reel on cloud ffmpeg")
        reel_url = _poll(_create_job("raw.ffmpeg", {}, {"command": command, "timeout": 900}))

        if getattr(params, "subtitle_enabled", False):
            reel_url = self._add_captions(ctx, reel_url)

        _download(reel_url, ctx.final_video_path)
        try:
            shutil.copyfile(ctx.final_video_path, ctx.combined_video_path)
        except OSError:
            pass
        logger.success(f"cloud render wrote {ctx.final_video_path}")

    def _add_captions(self, ctx: RenderContext, reel_url: str) -> str:
        """Burn the subtitles onto the reel with caption.burn, honoring the
        Subtitle Settings. The user's font is uploaded so the exact face is used.
        """
        if not (ctx.subtitle_path and os.path.isfile(ctx.subtitle_path)):
            return reel_url
        params = ctx.params
        logger.info("burning subtitles via caption.burn")
        width, height = VideoAspect(params.video_aspect).to_resolution()
        font_path = _local_font_path(getattr(params, "font_name", "") or "")

        # With the font available, build an ASS that reproduces the local MoviePy
        # layout and burn it as-is, so the cloud output matches the local render.
        if font_path:
            try:
                from app.services.render.caption_ass import build_caption_ass
                ass_text = build_caption_ass(ctx.subtitle_path, params, width, height, font_path)
                ass_path = os.path.join(os.path.dirname(ctx.subtitle_path), "caption.ass")
                with open(ass_path, "w", encoding="utf-8") as handle:
                    handle.write(ass_text)
                sub_url = _upload_one(ass_path)
                font_url = _upload_one(font_path)
                return _poll(_create_job(
                    "caption.burn",
                    {"source": reel_url, "subtitles": sub_url, "font": font_url},
                    {},
                ))
            except Exception as e:
                logger.warning(f"caption ass build failed, using srt: {e}")

        # Fallback: send the SRT and let caption.burn style it from the params.
        srt_url = _upload_one(ctx.subtitle_path)
        return _poll(_create_job(
            "caption.burn",
            {"source": reel_url, "subtitles": srt_url},
            _map_subtitle_settings(params, height),
        ))
