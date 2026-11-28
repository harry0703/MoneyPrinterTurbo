"""Animación 2.5D del avatar, caricatura 2D y presentación de diapositivas.

Todo es determinista y local: Pillow dibuja los fotogramas y el codificador
existente de ``cartoon_animation`` los envía a FFmpeg. La sincronización labial
usa la envolvente de amplitud del audio (no reconocimiento fonético), tal como
se declara en el panel.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Iterable, Iterator

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageStat

from app.services.cartoon_animation import (
    Pose,
    RenderSettings,
    get_character,
    render_character,
)
from app.services.cartoon_animation import assets as cartoon_assets
from app.services.cartoon_animation import lip_sync
from app.services.cartoon_animation.renderer import encode_frames
from app.services.personal_studio.avatars import _backdrop
from app.services.personal_studio.presets import SCENES
from app.services.personal_studio.security import StudioError


def work_size(size: tuple[int, int], max_width: int = 720) -> tuple[int, int]:
    width, height = size
    if width <= max_width:
        return width, height
    scale = max_width / float(width)
    return max_width, max(2, int(round(height * scale / 2.0)) * 2)


def _cover_rect(container: tuple[int, int], source: tuple[int, int]) -> tuple[int, int, int, int]:
    """Cubre el contenedor recortando el exceso, sin dejar bordes vacíos."""
    cw, ch = container
    sw, sh = source
    scale = max(cw / sw, ch / sh)
    width, height = max(1, int(round(sw * scale))), max(1, int(round(sh * scale)))
    return (cw - width) // 2, (ch - height) // 2, width, height


def _vertical_mask(size: tuple[int, int], fade: float = 0.22) -> Image.Image:
    width, height = size
    mask = Image.new("L", size, 0)
    pixels = mask.load()
    band = max(1, int(height * fade))
    for y in range(height):
        if y < band:
            value = int(255 * y / band)
        elif y > height - band:
            value = int(255 * (height - y) / band)
        else:
            value = 255
        for x in range(width):
            pixels[x, y] = value
    return mask.filter(ImageFilter.GaussianBlur(2))


class PresenterFrames:
    """Genera fotogramas de un avatar fotorrealista con animación ligera."""

    def __init__(
        self,
        portrait_path: Path,
        *,
        size: tuple[int, int],
        fps: int,
        scene: str,
        face_normalized: list[float] | None,
        side_slides: list[Path] | None = None,
        side_width_ratio: float = 0.52,
    ):
        self.size = size
        self.fps = fps
        self.portrait = Image.open(portrait_path).convert("RGB")
        self.face = face_normalized or [0.2, 0.2, 0.6, 0.5]
        self.slides = [Image.open(path).convert("RGB") for path in (side_slides or [])]
        self.side_ratio = side_width_ratio if self.slides else 0.0
        self.backdrop = self._backdrop(scene)
        self.origin_x = int(round(size[0] * self.side_ratio)) if self.slides else 0
        main_width = size[0] - self.origin_x
        main_height = size[1]
        left, top, width, height = _cover_rect((main_width, main_height), self.portrait.size)
        self.rect = (self.origin_x + left, top, width, height)
        self.base = self.portrait.resize((width, height), Image.LANCZOS)
        face_x, face_y, face_w, face_h = self.face
        self.face_box = (
            face_x * width,
            face_y * height,
            face_w * width,
            face_h * height,
        )
        band = (
            int(self.face_box[0] + self.face_box[2] * 0.22),
            int(self.face_box[1] + self.face_box[3] * 0.58),
            max(4, int(self.face_box[2] * 0.56)),
            max(4, int(self.face_box[3] * 0.26)),
        )
        self.mouth_band = band
        self.mouth_mask = _vertical_mask((band[2], band[3]))
        eye = (
            int(self.face_box[0] + self.face_box[2] * 0.12),
            int(self.face_box[1] + self.face_box[3] * 0.28),
            max(4, int(self.face_box[2] * 0.76)),
            max(3, int(self.face_box[3] * 0.16)),
        )
        self.eye_band = eye
        try:
            box = (
                max(0, eye[0]),
                max(0, eye[1] - 8),
                min(width, eye[0] + eye[2]),
                max(1, min(height, eye[1])),
            )
            patch = self.base.crop(box)
            mean = ImageStat.Stat(patch).mean if patch.size[0] and patch.size[1] else (140, 110, 90)
            self.skin = tuple(int(value) for value in mean[:3])
        except (ValueError, ZeroDivisionError):
            self.skin = (140, 110, 90)
        self.slide_images = self.slides

    def _backdrop(self, scene: str) -> Image.Image:
        spec = SCENES.get(scene)
        if spec and spec.get("kind") == "cartoon":
            try:
                return cartoon_assets.background(spec["asset"], self.size).convert("RGB")
            except Exception:  # noqa: BLE001 - fondo opcional
                pass
        # Fondo tipo "videollamada": la propia foto desenfocada y oscurecida.
        # Evita el borde cuadrado del retrato sin necesitar segmentación.
        blurred = ImageOps.fit(self.portrait, self.size, method=Image.LANCZOS)
        blurred = blurred.filter(ImageFilter.GaussianBlur(max(6, self.size[0] // 24)))
        blurred = ImageEnhance.Brightness(blurred).enhance(0.42)
        tint = _backdrop(scene, self.size)
        return Image.blend(blurred, tint, 0.35)

    def frame(self, time_seconds: float, openness: float) -> Image.Image:
        canvas = self.backdrop.copy()
        if self.slide_images:
            self._draw_slide(canvas, time_seconds)
        bob = math.sin(2 * math.pi * time_seconds / 4.2) * self.size[1] * 0.004
        sway = math.sin(2 * math.pi * time_seconds / 6.3) * self.size[0] * 0.0022
        x = int(self.rect[0] + sway)
        y = int(self.rect[1] + bob)
        canvas.paste(self.base, (x, y))
        self._animate_mouth(canvas, time_seconds, openness, x, y)
        if self._blinking(time_seconds):
            self._draw_blink(canvas, x, y)
        return canvas

    def _blinking(self, time_seconds: float) -> bool:
        phase = time_seconds % 4.1
        return phase < 0.14 or 2.05 < phase < 2.16

    def _draw_blink(self, canvas: Image.Image, dx: int, dy: int) -> None:
        draw = ImageDraw.Draw(canvas)
        x, y, w, h = self.eye_band
        draw.rounded_rectangle(
            (x + dx, y + dy, x + w + dx, y + dy + max(2, h)), radius=2, fill=self.skin
        )
        line_y = y + dy + h * 0.55
        draw.line([(x + dx, line_y), (x + w + dx, line_y)], fill=(70, 48, 40), width=2)

    def _animate_mouth(
        self, canvas: Image.Image, time_seconds: float, openness: float, dx: int, dy: int
    ) -> None:
        if openness <= 0.02:
            return
        x, y, w, h = self.mouth_band
        left = x + dx
        top = y + dy
        if left < 0 or top < 0 or left + w > canvas.width or top + h > canvas.height:
            return
        band = canvas.crop((left, top, left + w, top + h))
        stretch = 1.0 + 0.42 * min(1.0, openness)
        target_h = max(2, int(h * stretch))
        stretched = band.resize((w, target_h), Image.BILINEAR)
        mask = self.mouth_mask.resize((w, target_h), Image.BILINEAR)
        paste_y = top - (target_h - h) // 2
        canvas.paste(stretched, (left, paste_y), mask)

    def _draw_slide(self, canvas: Image.Image, time_seconds: float) -> None:
        if not self.slide_images:
            return
        per_slide = max(2.0, getattr(self, "duration", 10.0) / max(1, len(self.slide_images)))
        index = min(
            len(self.slide_images) - 1, int(time_seconds / per_slide)
        )
        local = (time_seconds - index * per_slide) / per_slide
        slide = self.slide_images[index]
        pane_w = int(self.size[0] * self.side_ratio)
        pane = (pane_w, self.size[1])
        zoom = 1.0 + 0.06 * min(1.0, max(0.0, local))
        tw, th = slide.size
        crop_w, crop_h = int(tw / zoom), int(th / zoom)
        left = (tw - crop_w) // 2
        top = (th - crop_h) // 2
        image = slide.crop((left, top, left + crop_w, top + crop_h)).resize(
            pane, Image.LANCZOS
        )
        canvas.paste(image, (0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((pane_w - 6, 0, pane_w, self.size[1]), fill=(12, 16, 24))


class CartoonFrames:
    """Caricatura 2D con el motor existente y la paleta de la foto."""

    def __init__(
        self,
        *,
        size: tuple[int, int],
        palette: dict[str, str],
        scene: str,
    ):
        self.size = size
        self.character = get_character("tiko", palette or None)
        spec = SCENES.get(scene) or SCENES["estudio_cartoon"]
        self.background = cartoon_assets.background(
            spec.get("asset", "studio"), size
        ).convert("RGB")
        self.cache: dict[float, Image.Image] = {}

    def frame(self, time_seconds: float, openness: float) -> Image.Image:
        blink = time_seconds % 4.1 < 0.14
        key = round(openness, 2)
        character = self.cache.get(key)
        if character is None:
            pose = Pose(
                {
                    "mouth_open": min(1.0, openness),
                    "mouth_width": 0.42 + 0.22 * min(1.0, openness),
                    "eye_open": 0.0 if blink else 1.0,
                }
            )
            character = render_character(self.character, pose)
            if len(self.cache) < 24:
                self.cache[key] = character
        canvas = self.background.copy()
        char_w = int(self.size[0] * 0.82)
        char_h = max(1, int(character.height * char_w / character.width))
        scaled = character.resize((char_w, char_h), Image.LANCZOS)
        x = (self.size[0] - char_w) // 2
        y = self.size[1] - char_h - int(self.size[1] * 0.04)
        bob = int(math.sin(time_seconds * 1.6) * self.size[1] * 0.003)
        canvas.paste(scaled, (x, y + bob), scaled)
        return canvas


def _openness_track(audio_path: Path, fps: int, duration: float) -> list[float]:
    try:
        return list(lip_sync.analyze_audio(audio_path, fps, duration))
    except Exception:  # noqa: BLE001 - sin lip sync es mejor que fallar
        return [0.0] * max(1, int(round(duration * fps)))


def _frames(
    renderer,
    audio_path: Path,
    *,
    fps: int,
    duration: float,
    cancel: Callable[[], bool] | None,
    progress: Callable[[float], None] | None,
) -> Iterator[tuple[float, Image.Image]]:
    track = _openness_track(audio_path, fps, duration)
    for index, openness in enumerate(track):
        if cancel is not None and cancel():
            raise StudioError("Render cancelado")
        time_seconds = index / float(fps)
        yield time_seconds, renderer.frame(time_seconds, openness)
        if progress is not None and index % max(1, fps) == 0:
            progress(index / float(fps))


def encode_visual(
    frames: Iterable[tuple[float, Image.Image]],
    destination: Path,
    *,
    size: tuple[int, int],
    output_size: tuple[int, int],
    fps: int,
    crf: int,
    preset: str,
    cancel: Callable[[], bool] | None = None,
    progress: Callable[[float], None] | None = None,
) -> Path:
    settings = RenderSettings(
        width=size[0],
        height=size[1],
        fps=fps,
        output_width=output_size[0],
        output_height=output_size[1],
        crf=crf,
        preset=preset,
    )
    return Path(
        encode_frames(
            frames, str(destination), settings, progress=progress, cancel=cancel
        )
    )


def render_presenter(
    *,
    portrait_path: Path,
    audio_path: Path,
    destination: Path,
    size: tuple[int, int],
    output_size: tuple[int, int],
    fps: int,
    scene: str,
    face_normalized: list[float] | None,
    crf: int = 22,
    preset: str = "veryfast",
    slides: list[Path] | None = None,
    cancel: Callable[[], bool] | None = None,
    progress: Callable[[float], None] | None = None,
) -> Path:
    duration = _duration(audio_path)
    renderer = PresenterFrames(
        portrait_path,
        size=size,
        fps=fps,
        scene=scene,
        face_normalized=face_normalized,
        side_slides=slides,
    )
    renderer.duration = duration
    return encode_visual(
        _frames(renderer, audio_path, fps=fps, duration=duration, cancel=cancel, progress=progress),
        destination,
        size=size,
        output_size=output_size,
        fps=fps,
        crf=crf,
        preset=preset,
        cancel=cancel,
        progress=progress,
    )


def render_cartoon(
    *,
    audio_path: Path,
    destination: Path,
    size: tuple[int, int],
    output_size: tuple[int, int],
    fps: int,
    palette: dict[str, str],
    scene: str,
    crf: int = 22,
    preset: str = "veryfast",
    cancel: Callable[[], bool] | None = None,
    progress: Callable[[float], None] | None = None,
) -> Path:
    duration = _duration(audio_path)
    renderer = CartoonFrames(size=size, palette=palette, scene=scene)
    return encode_visual(
        _frames(renderer, audio_path, fps=fps, duration=duration, cancel=cancel, progress=progress),
        destination,
        size=size,
        output_size=output_size,
        fps=fps,
        crf=crf,
        preset=preset,
        cancel=cancel,
        progress=progress,
    )


def render_slideshow(
    *,
    images: list[Path],
    audio_path: Path,
    destination: Path,
    size: tuple[int, int],
    output_size: tuple[int, int],
    fps: int,
    scene: str,
    crf: int = 22,
    preset: str = "veryfast",
    cancel: Callable[[], bool] | None = None,
    progress: Callable[[float], None] | None = None,
) -> Path:
    if not images:
        raise StudioError("El modo tradicional necesita al menos una imagen")
    duration = _duration(audio_path)
    prepared = [Image.open(path).convert("RGB") for path in images]
    per_slide = duration / len(prepared)
    backdrop = _backdrop(scene, size)

    def generator() -> Iterator[tuple[float, Image.Image]]:
        frames = max(1, int(round(duration * fps)))
        for index in range(frames):
            if cancel is not None and cancel():
                raise StudioError("Render cancelado")
            time_seconds = index / float(fps)
            position = min(len(prepared) - 1, int(time_seconds / per_slide))
            local = (time_seconds - position * per_slide) / per_slide
            slide = prepared[position]
            zoom = 1.0 + 0.08 * min(1.0, max(0.0, local))
            crop_w = max(2, int(slide.width / zoom))
            crop_h = max(2, int(slide.height / zoom))
            left = (slide.width - crop_w) // 2
            top = (slide.height - crop_h) // 2
            canvas = backdrop.copy()
            frame = slide.crop((left, top, left + crop_w, top + crop_h))
            fitted = ImageOps.fit(frame, size, method=Image.LANCZOS)
            canvas.paste(fitted, (0, 0))
            yield time_seconds, canvas
            if progress is not None and index % max(1, fps) == 0:
                progress(time_seconds)

    return encode_visual(
        generator(),
        destination,
        size=size,
        output_size=output_size,
        fps=fps,
        crf=crf,
        preset=preset,
        cancel=cancel,
        progress=progress,
    )


def render_still_video(
    *,
    image_path: Path,
    audio_path: Path,
    destination: Path,
    size: tuple[int, int],
    fps: int,
    crf: int = 22,
    preset: str = "veryfast",
) -> Path:
    """Portada fija para el modo podcast."""
    duration = _duration(audio_path)
    source = Image.open(image_path).convert("RGB")
    fitted = ImageOps.fit(source, size, method=Image.LANCZOS)
    return encode_visual(
        ((index / float(fps), fitted.copy()) for index in range(max(1, int(duration * fps)))),
        destination,
        size=size,
        output_size=size,
        fps=fps,
        crf=crf,
        preset=preset,
    )


def _duration(audio_path: Path) -> float:
    from app.services.personal_studio import audio

    duration = audio.ffprobe_duration(Path(audio_path))
    if duration <= 0:
        raise StudioError("La narración no tiene duración medible")
    return duration
