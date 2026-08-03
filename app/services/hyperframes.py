"""
Optional HyperFrames (https://github.com/heygen-com/hyperframes) video renderer.

When ``video_renderer = "hyperframes"`` in config.toml, MoneyPrinterTurbo scaffolds
a standalone HyperFrames project per output video under
``storage/tasks/<task_id>/hyperframes-<index>/``, stages media into ``assets/``,
and renders ``final-<index>.mp4`` from that project.

Setup:
  1. Install Node.js 22+ and FFmpeg
  2. ``npx hyperframes browser ensure`` (and ``npx hyperframes doctor``)
  3. Set ``video_renderer = "hyperframes"`` (or choose HyperFrames in the WebUI)
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional
from xml.sax.saxutils import escape as xml_escape

from loguru import logger

from app.config import config
from app.models.schema import VideoAspect, VideoParams
from app.utils import utils

COMPOSITION_ID = "moneyprinter-video"
FPS = 30


class HyperframesNotReadyError(RuntimeError):
    """Raised when HyperFrames was requested but dependencies are missing."""


class HyperframesRenderError(RuntimeError):
    """Raised when the HyperFrames CLI render fails."""


@dataclass(frozen=True)
class HyperframesReadiness:
    requested: bool
    node_available: bool
    ffmpeg_available: bool
    template_available: bool

    @property
    def ready(self) -> bool:
        return (
            self.requested
            and self.node_available
            and self.ffmpeg_available
            and self.template_available
        )

    @property
    def message(self) -> str:
        if not self.requested:
            return "HyperFrames renderer is not selected (video_renderer != hyperframes)."
        missing = []
        if not self.node_available:
            missing.append("Node.js 22+ (node/npx on PATH)")
        if not self.ffmpeg_available:
            missing.append("FFmpeg (ffmpeg/ffprobe on PATH)")
        if not self.template_available:
            missing.append("hyperframes/index.html template in the repository")
        return (
            "HyperFrames renderer is enabled but not ready. Install: "
            + "; ".join(missing)
            + ". Then run `npx hyperframes browser ensure` once."
        )


def template_dir() -> str:
    return os.path.join(utils.root_dir(), "hyperframes")


def is_requested() -> bool:
    value = str(config.app.get("video_renderer", "moviepy") or "moviepy").strip().lower()
    return value == "hyperframes"


def _command_available(command: str) -> bool:
    return shutil.which(command) is not None


def _node_major_version() -> Optional[int]:
    if not _command_available("node"):
        return None
    try:
        completed = subprocess.run(
            ["node", "-v"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.match(r"v?(\d+)", (completed.stdout or "").strip())
    if not match:
        return None
    return int(match.group(1))


def _node_available() -> bool:
    major = _node_major_version()
    return major is not None and major >= 22


def _ffmpeg_available() -> bool:
    return _command_available("ffmpeg") and _command_available("ffprobe")


def _template_available() -> bool:
    return os.path.isfile(os.path.join(template_dir(), "index.html"))


def get_readiness() -> HyperframesReadiness:
    return HyperframesReadiness(
        requested=is_requested(),
        node_available=_node_available(),
        ffmpeg_available=_ffmpeg_available(),
        template_available=_template_available(),
    )


def is_enabled() -> bool:
    readiness = get_readiness()
    return readiness.ready


def ensure_ready() -> None:
    readiness = get_readiness()
    if not readiness.ready:
        raise HyperframesNotReadyError(readiness.message)


def project_path_for(task_id: str, index: int) -> str:
    return os.path.join(utils.task_dir(task_id), f"hyperframes-{index}")


def _link_or_copy(src: str, dst: str) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.lexists(dst):
        os.remove(dst)
    try:
        os.link(src, dst)
    except OSError:
        try:
            os.symlink(os.path.abspath(src), dst)
        except OSError:
            shutil.copy2(src, dst)


def _parse_srt_timestamp(value: str) -> float:
    match = re.match(
        r"(?P<h>\d+):(?P<m>\d+):(?P<s>\d+)[,.](?P<ms>\d+)",
        value.strip(),
    )
    if not match:
        return 0.0
    hours = int(match.group("h"))
    minutes = int(match.group("m"))
    seconds = int(match.group("s"))
    millis = int(match.group("ms").ljust(3, "0")[:3])
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def parse_srt_cues(subtitle_path: str) -> List[dict[str, Any]]:
    if not subtitle_path or not os.path.isfile(subtitle_path):
        return []
    text = open(subtitle_path, "r", encoding="utf-8", errors="replace").read()
    blocks = re.split(r"\n\s*\n", text.strip(), flags=re.MULTILINE)
    cues: List[dict[str, Any]] = []
    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        timing_line = lines[0] if "-->" in lines[0] else (lines[1] if len(lines) > 1 else "")
        if "-->" not in timing_line:
            continue
        start_raw, end_raw = [part.strip() for part in timing_line.split("-->", 1)]
        body_lines = lines[1:] if "-->" in lines[0] else lines[2:]
        body = " ".join(body_lines).strip()
        if not body:
            continue
        start = _parse_srt_timestamp(start_raw)
        end = _parse_srt_timestamp(end_raw.split()[0] if end_raw else start_raw)
        duration = max(0.05, end - start)
        cues.append({"start": start, "duration": duration, "text": body})
    return cues


def _caption_position_css(params: VideoParams) -> str:
    position = (params.subtitle_position or "bottom").lower()
    if position == "top":
        return "top: 8%; bottom: auto;"
    if position == "center":
        return "top: 50%; bottom: auto; transform: translate(-50%, -50%);"
    if position == "custom":
        custom = max(0.0, min(100.0, float(params.custom_position or 70.0)))
        return f"top: {custom}%; bottom: auto; transform: translate(-50%, -50%);"
    return "bottom: 10%; top: auto;"


def _caption_background_css(params: VideoParams) -> str:
    if not params.subtitle_enabled:
        return ""
    bg = params.text_background_color
    if not bg or bg is False:
        return ""
    if bg is True:
        color = "rgba(0, 0, 0, 0.55)"
    else:
        color = str(bg)
    radius = "0.35em" if params.rounded_subtitle_background else "0"
    return f"background: {color}; border-radius: {radius};"


def _font_face_and_family(params: VideoParams, assets_dir: str) -> tuple[str, str]:
    font_name = params.font_name or "STHeitiMedium.ttc"
    font_path = os.path.join(utils.font_dir(), font_name)
    family = os.path.splitext(os.path.basename(font_name))[0] or "MoneyPrinterFont"
    if not os.path.isfile(font_path):
        return "", f'"{family}"'
    staged = os.path.join(assets_dir, os.path.basename(font_path))
    _link_or_copy(font_path, staged)
    face = (
        f"@font-face {{ font-family: '{family}'; "
        f"src: url('assets/{os.path.basename(font_path)}'); }}"
    )
    return face, f'"{family}"'


def _build_caption_elements(cues: List[dict[str, Any]]) -> tuple[str, str]:
    elements: List[str] = []
    animations: List[str] = []
    for index, cue in enumerate(cues, start=1):
        cue_id = f"cap-{index}"
        text = xml_escape(str(cue["text"]))
        start = float(cue["start"])
        duration = float(cue["duration"])
        elements.append(
            "\n".join(
                [
                    f'    <div id="{cue_id}" class="clip caption"',
                    f'         data-start="{start:.3f}"',
                    f'         data-duration="{duration:.3f}"',
                    '         data-track-index="3">',
                    f"      {text}",
                    "    </div>",
                ]
            )
        )
        animations.append(
            f'tl.set("#{cue_id}", {{ opacity: 1 }}, {start:.3f});'
        )
        animations.append(
            f'tl.set("#{cue_id}", {{ opacity: 0 }}, {start + duration:.3f});'
        )
    return "\n\n".join(elements), "\n      ".join(animations)


def _bgm_block(has_bgm: bool, duration: float, bgm_volume: float, bgm_name: str) -> str:
    if not has_bgm:
        return ""
    safe_name = html.escape(bgm_name, quote=True)
    return "\n".join(
        [
            "    <audio",
            '      id="bgm"',
            '      data-start="0"',
            f'      data-duration="{duration:.3f}"',
            '      data-track-index="2"',
            f'      data-volume="{max(0.0, min(1.0, float(bgm_volume))):.3f}"',
            '      data-timeline-role="music"',
            f'      src="assets/{safe_name}"',
            "    ></audio>",
        ]
    )


def _fill_index_html(
    template: str,
    *,
    params: VideoParams,
    duration: float,
    cues: List[dict[str, Any]],
    has_bgm: bool,
    bgm_name: str,
    font_face: str,
    font_family: str,
) -> str:
    width, height = VideoAspect(params.video_aspect).to_resolution()
    caption_elements, caption_animations = _build_caption_elements(
        cues if params.subtitle_enabled else []
    )
    voice_volume = max(0.0, min(1.0, float(params.voice_volume or 1.0)))
    bgm_volume = max(0.0, min(1.0, float(params.bgm_volume or 0.0)))
    replacements = {
        "__COMPOSITION_ID__": COMPOSITION_ID,
        "__WIDTH__": str(width),
        "__HEIGHT__": str(height),
        "__DURATION__": f"{max(0.1, float(duration)):.3f}",
        "__VOICE_VOLUME__": f"{voice_volume:.3f}",
        "__FONT_FACE__": font_face,
        "__FONT_FAMILY__": font_family,
        "__FONT_SIZE__": str(int(params.font_size or 60)),
        "__TEXT_COLOR__": str(params.text_fore_color or "#FFFFFF"),
        "__STROKE_COLOR__": str(params.stroke_color or "#000000"),
        "__STROKE_WIDTH__": f"{float(params.stroke_width or 0):.2f}",
        "__CAPTION_POSITION__": _caption_position_css(params),
        "__CAPTION_BACKGROUND__": _caption_background_css(params),
        "__BGM_BLOCK__": _bgm_block(has_bgm, duration, bgm_volume, bgm_name),
        "__CAPTION_ELEMENTS__": caption_elements,
        "__CAPTION_ANIMATIONS__": caption_animations
        or "/* no captions */",
    }
    filled = template
    for key, value in replacements.items():
        filled = filled.replace(key, value)
    return filled


def _write_project_readme(project_dir: str) -> None:
    content = """# HyperFrames project

Generated by MoneyPrinterTurbo.

```bash
npx hyperframes preview
npx hyperframes render --output out.mp4 --quality standard --fps 30
```

Edit `index.html` and files under `assets/`, then re-render.
"""
    with open(os.path.join(project_dir, "README.md"), "w", encoding="utf-8") as handle:
        handle.write(content)


def scaffold_project(
    *,
    task_id: str,
    index: int,
    params: VideoParams,
    video_path: str,
    audio_path: str,
    subtitle_path: str,
    duration: float,
    bgm_path: str = "",
) -> str:
    """Create ``hyperframes-<index>`` under the task directory and stage assets."""
    ensure_ready()
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"visual video not found: {video_path}")
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"narration audio not found: {audio_path}")

    project_dir = project_path_for(task_id, index)
    if os.path.isdir(project_dir):
        shutil.rmtree(project_dir)
    os.makedirs(project_dir, exist_ok=True)

    source_template = template_dir()
    assets_dir = os.path.join(project_dir, "assets")
    compositions_dir = os.path.join(project_dir, "compositions")
    os.makedirs(assets_dir, exist_ok=True)
    os.makedirs(compositions_dir, exist_ok=True)

    shutil.copy2(
        os.path.join(source_template, "hyperframes.json"),
        os.path.join(project_dir, "hyperframes.json"),
    )
    captions_src = os.path.join(source_template, "compositions", "captions.html")
    if os.path.isfile(captions_src):
        shutil.copy2(captions_src, os.path.join(compositions_dir, "captions.html"))

    meta = {
        "name": f"MoneyPrinterTurbo-{index}",
        "id": f"{COMPOSITION_ID}-{index}",
        "created": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
        "index": index,
    }
    with open(os.path.join(project_dir, "meta.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=2)

    _link_or_copy(video_path, os.path.join(assets_dir, "video.mp4"))
    narration_name = "narration.mp3"
    audio_ext = os.path.splitext(audio_path)[1].lower() or ".mp3"
    if audio_ext != ".mp3":
        narration_name = f"narration{audio_ext}"
    _link_or_copy(audio_path, os.path.join(assets_dir, narration_name))

    has_bgm = bool(bgm_path and os.path.isfile(bgm_path))
    bgm_name = ""
    if has_bgm:
        bgm_name = f"bgm{os.path.splitext(bgm_path)[1].lower() or '.mp3'}"
        _link_or_copy(bgm_path, os.path.join(assets_dir, bgm_name))

    font_face, font_family = _font_face_and_family(params, assets_dir)
    cues = parse_srt_cues(subtitle_path)

    template_path = os.path.join(source_template, "index.html")
    template = open(template_path, "r", encoding="utf-8").read()
    filled = _fill_index_html(
        template,
        params=params,
        duration=duration,
        cues=cues,
        has_bgm=has_bgm,
        bgm_name=bgm_name,
        font_face=font_face,
        font_family=font_family,
    )
    if narration_name != "narration.mp3":
        filled = filled.replace("assets/narration.mp3", f"assets/{narration_name}")

    with open(os.path.join(project_dir, "index.html"), "w", encoding="utf-8") as handle:
        handle.write(filled)

    _write_project_readme(project_dir)
    logger.info(f"hyperframes project scaffolded: {project_dir}")
    return project_dir


def _hyperframes_quality() -> str:
    value = str(config.app.get("hyperframes_quality", "standard") or "standard").strip().lower()
    if value not in {"draft", "standard", "high"}:
        return "standard"
    return value


def render_project(project_dir: str, output_file: str, *, threads: Optional[int] = None) -> str:
    """Render a scaffolded HyperFrames project to ``output_file``."""
    ensure_ready()
    if not os.path.isdir(project_dir):
        raise FileNotFoundError(f"hyperframes project not found: {project_dir}")
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    if os.path.exists(output_file):
        os.remove(output_file)

    command = [
        "npx",
        "--yes",
        "hyperframes",
        "render",
        "--output",
        output_file,
        "--quality",
        _hyperframes_quality(),
        "--fps",
        str(FPS),
    ]
    if threads and int(threads) > 0:
        command.extend(["--workers", str(int(threads))])

    logger.info(f"hyperframes render: project={project_dir}, output={output_file}")
    try:
        completed = subprocess.run(
            command,
            cwd=project_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=60 * 60,
        )
    except subprocess.TimeoutExpired as exc:
        raise HyperframesRenderError(
            f"hyperframes render timed out for project {project_dir}"
        ) from exc
    except OSError as exc:
        raise HyperframesRenderError(f"failed to launch hyperframes: {exc}") from exc

    if completed.returncode != 0 or not os.path.isfile(output_file):
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout or f"exit code {completed.returncode}"
        raise HyperframesRenderError(
            f"hyperframes render failed for {project_dir}: {detail}"
        )

    logger.success(f"hyperframes render finished: {output_file}")
    return output_file
