"""2D cartoon studio: storyboard, cartoon stills and a narrated episode.

Opt-in and local. Cartoon frames come from the configured OpenAI-compatible
``openai_image`` endpoint, narration from the existing voice service, and the
final assembly/revision handling from :mod:`app.services.video_project`.

Run ``python -m app.services.cartoon_studio --help``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from app.models.schema import ImageMotion, VideoAspect
from app.services import material, video, video_project, voice

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_MANIFEST_FIELDS = {
    "project_id",
    "title",
    "style",
    "aspect",
    "characters",
    "scenes",
}
_SCENE_FIELDS = {"id", "visual", "narration", "duration", "characters"}
_MAX_SCENES = 100

# Each preset blends a concrete rendering language with the failure modes that
# break the "2D" look. Negative phrases are appended to the prompt because the
# OpenAI-compatible image protocol has no separate negative-prompt field.
STYLE_PRESETS: dict[str, dict[str, str]] = {
    "flat-2d": {
        "prompt": (
            "flat 2D vector cartoon illustration, bold simple shapes, crisp "
            "closed outlines, flat shading, limited pastel palette, subtle "
            "paper grain"
        ),
        "negative": (
            "3D render, CGI, photorealism, photograph, realistic skin, glossy "
            "plastic, gradients, lens flare, heavy shadows"
        ),
    },
    "anime": {
        "prompt": (
            "2D anime illustration, clean cel shading, expressive line art, "
            "vivid but limited palette, painted background in the same style"
        ),
        "negative": (
            "3D render, CGI, photorealism, photograph, sketchy lines, "
            "inconsistent character design, text, watermark"
        ),
    },
    "comic": {
        "prompt": (
            "2D comic book panel illustration, inked outlines, halftone "
            "shading, bold flat colors, simplified anatomy"
        ),
        "negative": (
            "3D render, CGI, photorealism, photograph, speech bubbles, "
            "captions, lettering, text, watermark"
        ),
    },
    "storybook": {
        "prompt": (
            "2D children's storybook illustration, soft gouache textures, "
            "gentle warm palette, hand-drawn outlines, simple readable shapes"
        ),
        "negative": (
            "3D render, CGI, photorealism, photograph, scary imagery, text, "
            "watermark, muddy colors"
        ),
    },
}


class CartoonStudioError(ValueError):
    pass


@dataclass(frozen=True)
class Scene:
    id: str
    visual: str
    narration: str
    duration: float
    characters: tuple[str, ...]


@dataclass(frozen=True)
class Storyboard:
    project_id: str
    title: str
    style_name: str
    style_prompt: str
    style_negative: str
    aspect: VideoAspect
    characters: dict[str, str]
    scenes: tuple[Scene, ...]


def _text(value: Any, field: str, limit: int, *, required: bool = False) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise CartoonStudioError(f"{field} must be text")
    result = value.strip()
    if required and not result:
        raise CartoonStudioError(f"{field} must not be empty")
    if len(result) > limit:
        raise CartoonStudioError(f"{field} must be under {limit} characters")
    return result


def _style(value: Any) -> tuple[str, str, str]:
    if isinstance(value, str):
        name = value.strip()
        preset = STYLE_PRESETS.get(name)
        if preset is None:
            choices = ", ".join(sorted(STYLE_PRESETS))
            raise CartoonStudioError(f"style must be one of {choices} or a custom style")
        return name, preset["prompt"], preset["negative"]
    if isinstance(value, dict):
        unknown = set(value) - {"name", "prompt", "negative"}
        if unknown or not value.get("prompt"):
            raise CartoonStudioError(
                "custom style accepts name, prompt and negative, and needs a prompt"
            )
        name = _text(value.get("name"), "style.name", 60) or "custom"
        prompt = _text(value.get("prompt"), "style.prompt", 2000, required=True)
        negative = _text(value.get("negative"), "style.negative", 2000)
        return name, prompt, negative
    raise CartoonStudioError("style must be a preset name or a custom style object")


def _characters(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, list):
        raise CartoonStudioError("characters must be a list")
    result: dict[str, str] = {}
    for index, raw in enumerate(value):
        if not isinstance(raw, dict) or set(raw) - {"name", "description"}:
            raise CartoonStudioError(
                f"characters[{index}] accepts name and description"
            )
        name = _text(raw.get("name"), f"characters[{index}].name", 60, required=True)
        if name in result:
            raise CartoonStudioError(f"character names must be unique: {name}")
        result[name] = _text(
            raw.get("description"),
            f"characters[{index}].description",
            1000,
            required=True,
        )
    if len(result) > 20:
        raise CartoonStudioError("provide at most 20 characters")
    return result


def parse_storyboard(data: Any) -> Storyboard:
    """Validate a cartoon manifest without touching the network or the disk."""
    if not isinstance(data, dict):
        raise CartoonStudioError("the cartoon manifest must be a JSON object")
    unknown = set(data) - _MANIFEST_FIELDS
    if unknown:
        raise CartoonStudioError(f"unknown manifest fields: {', '.join(sorted(unknown))}")
    project_id = _text(data.get("project_id"), "project_id", 64, required=True)
    if not _ID.fullmatch(project_id):
        raise CartoonStudioError(
            "project_id must be 1-64 letters, digits, underscores or hyphens"
        )
    title = _text(data.get("title"), "title", 200) or project_id
    style_name, style_prompt, style_negative = _style(data.get("style", "flat-2d"))
    try:
        aspect = VideoAspect(data.get("aspect", VideoAspect.portrait.value))
    except ValueError as exc:
        raise CartoonStudioError("aspect must be 16:9, 9:16 or 1:1") from exc
    characters = _characters(data.get("characters"))

    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list) or not 1 <= len(raw_scenes) <= _MAX_SCENES:
        raise CartoonStudioError(f"provide between 1 and {_MAX_SCENES} scenes")
    scenes: list[Scene] = []
    for index, raw in enumerate(raw_scenes):
        if not isinstance(raw, dict):
            raise CartoonStudioError(f"scenes[{index}] must be an object")
        unknown = set(raw) - _SCENE_FIELDS
        if unknown:
            raise CartoonStudioError(
                f"unknown fields in scenes[{index}]: {', '.join(sorted(unknown))}"
            )
        scene_id = _text(raw.get("id"), f"scenes[{index}].id", 64, required=True)
        if not _ID.fullmatch(scene_id):
            raise CartoonStudioError(
                f"scenes[{index}].id must be 1-64 letters, digits, underscores or hyphens"
            )
        visual = _text(
            raw.get("visual"), f"scenes[{index}].visual", 2000, required=True
        )
        narration = _text(raw.get("narration"), f"scenes[{index}].narration", 10000)
        duration = raw.get("duration", 5)
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or not 1 <= duration <= 60
        ):
            raise CartoonStudioError(
                f"scenes[{index}].duration must be between 1 and 60 seconds"
            )
        cast = raw.get("characters", [])
        if not isinstance(cast, list):
            raise CartoonStudioError(f"scenes[{index}].characters must be a list")
        for name in cast:
            if not isinstance(name, str) or name not in characters:
                raise CartoonStudioError(
                    f"scenes[{index}] references an unknown character: {name!r}"
                )
        if len(set(cast)) != len(cast):
            raise CartoonStudioError(f"scenes[{index}] repeats a character")
        scenes.append(
            Scene(
                id=scene_id,
                visual=visual,
                narration=narration,
                duration=float(duration),
                characters=tuple(cast),
            )
        )
    if len({scene.id for scene in scenes}) != len(scenes):
        raise CartoonStudioError("scene IDs must be unique")
    return Storyboard(
        project_id=project_id,
        title=title,
        style_name=style_name,
        style_prompt=style_prompt,
        style_negative=style_negative,
        aspect=aspect,
        characters=characters,
        scenes=tuple(scenes),
    )


def load_storyboard(path: str | Path) -> Storyboard:
    try:
        with Path(path).open(encoding="utf-8") as source:
            data = json.load(source)
    except OSError as exc:
        raise CartoonStudioError(f"cannot read manifest: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CartoonStudioError(f"manifest is not valid JSON: {exc}") from exc
    return parse_storyboard(data)


def scene_prompt(storyboard: Storyboard, scene: Scene) -> str:
    """Compose the frame prompt: style, character sheet, action, exclusions."""
    parts = [f"2D cartoon frame in this style: {storyboard.style_prompt}."]
    if scene.characters:
        sheet = "; ".join(
            f"{name}: {storyboard.characters[name]}" for name in scene.characters
        )
        parts.append(
            "Characters in this scene, kept identical to their character sheet: "
            f"{sheet}."
        )
    parts.append(f"Scene: {scene.visual}")
    parts.append(
        "Single frame, consistent character design, no text, no captions, "
        "no speech bubbles, no watermark."
    )
    if storyboard.style_negative:
        parts.append(f"Avoid: {storyboard.style_negative}.")
    return " ".join(parts)


def storyboard_document(storyboard: Storyboard) -> dict:
    return {
        "project_id": storyboard.project_id,
        "title": storyboard.title,
        "style": storyboard.style_name,
        "aspect": storyboard.aspect.value,
        "characters": [
            {"name": name, "description": description}
            for name, description in storyboard.characters.items()
        ],
        "scenes": [
            {
                "id": scene.id,
                "visual": scene.visual,
                "narration": scene.narration,
                "duration": scene.duration,
                "characters": list(scene.characters),
                "prompt": scene_prompt(storyboard, scene),
            }
            for scene in storyboard.scenes
        ],
    }


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump(value, target, indent=2, ensure_ascii=False)
            target.flush()
            os.fsync(target.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_storyboard(project_dir: str | Path, storyboard: Storyboard) -> Path:
    path = Path(project_dir) / "storyboard.json"
    _atomic_json(path, storyboard_document(storyboard))
    return path


def _request_image(prompt: str, aspect: VideoAspect, save_dir: Path) -> tuple[str, int, int]:
    """Generate one frame through the configured OpenAI-compatible endpoint."""
    endpoint, model = material._openai_image_endpoint()
    save_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": material._openai_image_size(aspect),
    }
    image_bytes, failure = material._request_openai_image(endpoint, payload)
    if image_bytes is None:
        raise CartoonStudioError(f"image generation failed: {failure}")
    try:
        return material._save_openai_image_file(image_bytes, str(save_dir))
    except material._OpenAIImageDecodeError as exc:
        raise CartoonStudioError(f"image endpoint returned no usable image: {exc}") from exc


def _frame_identity(storyboard: Storyboard, scene: Scene, prompt: str) -> str:
    """Identify a frame by prompt and the effective generation canvas.

    The same prompt rendered at 9:16 and 16:9 produces different pixels, so the
    aspect (and any configured override size) must take part in the cache key.
    """
    size = material._openai_image_size(storyboard.aspect)
    identity = f"{prompt}|{storyboard.aspect.value}|{size}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]


def generate_scene_images(
    project_dir: str | Path,
    storyboard: Storyboard,
    *,
    request_image=_request_image,
) -> list[dict]:
    """Generate one PNG per scene, reusing frames whose identity did not change."""
    images_dir = Path(project_dir) / "images"
    records = []
    for scene in storyboard.scenes:
        prompt = scene_prompt(storyboard, scene)
        digest = _frame_identity(storyboard, scene, prompt)
        target = images_dir / f"{scene.id}-{digest}.png"
        if target.is_file():
            records.append(
                {"id": scene.id, "path": str(target), "status": "reused"}
            )
            continue
        logger.info(f"cartoon frame: scene={scene.id}, style={storyboard.style_name}")
        saved, width, height = request_image(prompt, storyboard.aspect, images_dir)
        saved_path = Path(saved)
        if saved_path != target:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(saved_path, target)
        records.append(
            {
                "id": scene.id,
                "path": str(target),
                "width": width,
                "height": height,
                "status": "generated",
            }
        )
    return records


def _narration_path(project_dir: Path, scene: Scene, voice_name: str, voice_rate: float) -> Path:
    identity = f"{scene.narration}|{voice_name}|{voice_rate}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return project_dir / "audio" / f"{scene.id}-{digest}.mp3"


def narrate_scenes(
    project_dir: str | Path,
    storyboard: Storyboard,
    *,
    voice_name: str,
    voice_rate: float = 1.0,
) -> dict[str, tuple[str, float]]:
    """Synthesize one narration file per scene that has text."""
    if not voice_name:
        return {}
    directory = Path(project_dir) / "audio"
    directory.mkdir(parents=True, exist_ok=True)
    result: dict[str, tuple[str, float]] = {}
    for scene in storyboard.scenes:
        if not scene.narration:
            continue
        target = _narration_path(Path(project_dir), scene, voice_name, voice_rate)
        if not target.is_file():
            logger.info(f"cartoon narration: scene={scene.id}, voice={voice_name}")
            voice.tts(scene.narration, voice_name, voice_rate, str(target))
            if not target.is_file():
                raise CartoonStudioError(f"narration was not written for scene {scene.id}")
        duration = voice.get_audio_duration(str(target))
        if duration <= 0:
            raise CartoonStudioError(f"narration for scene {scene.id} has no duration")
        # Return absolute paths: callers may resolve them again against a
        # relative project directory (VideoProject._asset joins ``relative_to``),
        # which would otherwise duplicate the project prefix.
        result[scene.id] = (str(target.resolve()), duration)
    return result


def episode_request(
    storyboard: Storyboard,
    footage: dict[str, str],
    narration: dict[str, tuple[str, float]],
    *,
    bgm: str = "",
    bgm_volume: float = 0.15,
    subtitles: bool = False,
    subtitle_font_size: int = 56,
) -> dict:
    """Build the video-project manifest from rendered clips and narration."""
    width, height = storyboard.aspect.to_resolution()
    scenes = []
    for scene in storyboard.scenes:
        clip = footage.get(scene.id)
        if not clip:
            raise CartoonStudioError(f"missing rendered clip for scene {scene.id}")
        audio = narration.get(scene.id)
        scenes.append(
            {
                "id": scene.id,
                "footage": clip,
                "duration": audio[1] if audio else scene.duration,
                **({"audio": audio[0], "narration": scene.narration} if audio else {}),
            }
        )
    settings: dict[str, Any] = {
        "width": width,
        "height": height,
        "fps": 30,
        "subtitles": subtitles,
        "subtitle_font_size": subtitle_font_size,
    }
    request: dict[str, Any] = {
        "project_id": storyboard.project_id,
        "settings": settings,
        "scenes": scenes,
    }
    if bgm:
        settings["bgm_volume"] = bgm_volume
        request["bgm"] = bgm
    return request


def build(
    project_dir: str | Path,
    storyboard: Storyboard,
    *,
    voice_name: str = "",
    voice_rate: float = 1.0,
    bgm: str = "",
    bgm_volume: float = 0.15,
    subtitles: bool = False,
    subtitle_font_size: int = 56,
    image_motion: ImageMotion = ImageMotion.zoom,
    retry: bool = False,
    stage_timeout: float = 600,
    request_image=_request_image,
    render_clip=video.render_image_zoom_video,
) -> dict:
    """Turn a storyboard into images, clips and a rendered episode."""
    # Resolve once so a relative project directory cannot be joined twice by
    # VideoProject._asset, and so music keeps its cwd-relative meaning.
    project_dir = Path(project_dir).resolve()
    if bgm:
        bgm = str(Path(bgm).resolve())
        if not Path(bgm).is_file():
            raise CartoonStudioError(f"background music not found: {bgm}")
    if not math.isfinite(bgm_volume) or not 0 <= bgm_volume <= 4:
        raise CartoonStudioError("bgm volume must be finite and between 0 and 4")
    storyboard_path = write_storyboard(project_dir, storyboard)
    images = generate_scene_images(project_dir, storyboard, request_image=request_image)
    images_by_id = {
        record["id"]: str(Path(record["path"]).resolve()) for record in images
    }
    narration = narrate_scenes(
        project_dir, storyboard, voice_name=voice_name, voice_rate=voice_rate
    )

    footage: dict[str, str] = {}
    for scene in storyboard.scenes:
        audio = narration.get(scene.id)
        seconds = max(1, math.ceil(audio[1] if audio else scene.duration))
        clip = render_clip(images_by_id[scene.id], seconds, image_motion=image_motion)
        if not clip or not Path(clip).is_file():
            raise CartoonStudioError(f"failed to render a clip for scene {scene.id}")
        footage[scene.id] = str(Path(clip).resolve())

    request = episode_request(
        storyboard,
        footage,
        narration,
        bgm=bgm,
        bgm_volume=bgm_volume,
        subtitles=subtitles,
        subtitle_font_size=subtitle_font_size,
    )
    project = video_project.VideoProject(str(project_dir))
    spec = project.create_revision(request, relative_to=project_dir)
    status = project.render(spec["revision_id"], retry=retry, stage_timeout=stage_timeout)
    return {
        "storyboard": str(storyboard_path),
        "images": images,
        "revision": spec["revision_id"],
        "status": status,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="2D cartoon studio: storyboard, cartoon frames and a rendered episode"
    )
    parser.add_argument(
        "--project", required=True, help="Project directory for frames, audio and renders"
    )
    parser.add_argument(
        "--manifest",
        help="Cartoon manifest; defaults to <project>/cartoon.json",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("storyboard", help="Write prompts without calling any API")
    commands.add_parser("images", help="Generate one cartoon frame per scene")
    build_parser = commands.add_parser("build", help="Frames, narration, clips and the episode")
    build_parser.add_argument(
        "--voice", default="", help="Voice name; omit for a silent storyboard video"
    )
    build_parser.add_argument("--voice-rate", type=float, default=1.0)
    build_parser.add_argument(
        "--subtitles", action="store_true", help="Burn the narration into the episode"
    )
    build_parser.add_argument("--subtitle-size", type=int, default=56)
    build_parser.add_argument("--bgm", default="", help="Local music file to loop under the episode")
    build_parser.add_argument("--bgm-volume", type=float, default=0.15)
    build_parser.add_argument("--retry", action="store_true")
    build_parser.add_argument("--stage-timeout", type=float, default=600)
    args = parser.parse_args(argv)

    project_dir = Path(args.project)
    manifest = Path(args.manifest) if args.manifest else project_dir / "cartoon.json"
    try:
        storyboard = load_storyboard(manifest)
        if args.command == "storyboard":
            result = {
                "storyboard": str(write_storyboard(project_dir, storyboard)),
                **storyboard_document(storyboard),
            }
        elif args.command == "images":
            write_storyboard(project_dir, storyboard)
            result = {
                "project_id": storyboard.project_id,
                "images": generate_scene_images(project_dir, storyboard),
            }
        else:
            result = build(
                project_dir,
                storyboard,
                voice_name=args.voice,
                voice_rate=args.voice_rate,
                bgm=args.bgm,
                bgm_volume=args.bgm_volume,
                subtitles=args.subtitles,
                subtitle_font_size=args.subtitle_size,
                retry=args.retry,
                stage_timeout=args.stage_timeout,
            )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (CartoonStudioError, video_project.ProjectError, OSError, ValueError) as exc:
        parser.exit(1, f"cartoon studio: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
