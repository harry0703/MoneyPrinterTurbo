from __future__ import annotations

from collections import OrderedDict
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
from moviepy import VideoClip
from PIL import Image

from loguru import logger

from app.models.schema import VideoParams
from app.services.character_image import CharacterImageService
from app.services.character_lipsync import CharacterLipSyncService, LipSyncFrame

try:
    import cv2

    CV2_AVAILABLE = True
except Exception:
    cv2 = None
    CV2_AVAILABLE = False


@dataclass(frozen=True)
class CharacterOverlayLayout:
    x: int
    y: int
    width: int
    height: int
    avoid_subtitles: bool


@dataclass
class CharacterOverlayResult:
    clip: VideoClip
    layout: CharacterOverlayLayout


class CharacterOverlayService:
    MOUTH_WIDTH_RATIO_FACE = 0.44
    MOUTH_HEIGHT_RATIO_FACE = 0.20
    MOUTH_Y_OFFSET_RATIO_FACE = 0.68
    MOUTH_WIDTH_RATIO_FALLBACK = 0.24
    MOUTH_HEIGHT_RATIO_FALLBACK = 0.12
    MOUTH_Y_OFFSET_RATIO_FALLBACK = 0.64

    def __init__(
        self,
        image_service: CharacterImageService | None = None,
        lipsync_service: CharacterLipSyncService | None = None,
    ) -> None:
        self.image_service = image_service or CharacterImageService()
        self.lipsync_service = lipsync_service or CharacterLipSyncService()

    def create_overlay(
        self,
        params: VideoParams,
        canvas_size: tuple[int, int],
        duration: float,
        audio_path: str | None,
    ) -> CharacterOverlayResult | None:
        if not params.character_overlay_enabled:
            return None
        if not params.character_image_file:
            raise ValueError("character_image_file is required when character overlay is enabled")

        prepared_image = self.image_service.prepare(
            params.character_image_file,
            remove_background=bool(params.character_remove_background),
            crop_transparent_edges=not bool(getattr(params, "character_manual_mapping_enabled", False)),
        )
        scaled_image = self.image_service.scale_for_canvas(
            prepared_image,
            canvas_size,
            float(params.character_scale or 0.28),
            float(params.character_max_width_ratio or 0.35),
            float(params.character_max_height_ratio or 0.45),
        )

        x_pos, y_pos = self.calculate_position(
            canvas_size=canvas_size,
            overlay_size=(scaled_image.width, scaled_image.height),
            position=str(params.character_position or "bottom_right"),
            margin_x=int(params.character_margin_x or 0),
            margin_y=int(params.character_margin_y or 0),
            custom_x=float(params.character_custom_x or 0.0),
            custom_y=float(params.character_custom_y or 0.0),
        )
        lipsync_mode = str(getattr(params, "avatar_lipsync_mode", "auto") or "auto").strip().lower()
        mode_window_ms = 120
        mode_intensity_multiplier = 1.0
        if lipsync_mode == "musetalk":
            mode_window_ms = 90
            mode_intensity_multiplier = 1.05
            logger.info("avatar_lipsync_mode=musetalk uses internal RMS lipsync")
        elif lipsync_mode == "wav2lip":
            mode_window_ms = 140
            mode_intensity_multiplier = 0.95
            logger.info("avatar_lipsync_mode=wav2lip uses internal RMS lipsync")
        elif lipsync_mode != "auto":
            logger.warning(f"unknown avatar_lipsync_mode={lipsync_mode}, falling back to auto")
            lipsync_mode = "auto"

        timeline = (
            self.lipsync_service.analyze(
                audio_path=audio_path,
                duration=duration,
                window_ms=mode_window_ms,
            )
            if params.character_lipsync_enabled
            else []
        )
        lipsync_intensity = float(np.clip(float(params.character_lipsync_intensity or 1.0), 0.4, 2.0))
        lipsync_intensity = float(np.clip(lipsync_intensity * mode_intensity_multiplier, 0.4, 2.0))
        base_frame = np.array(scaled_image.image, dtype=np.uint8)
        mouth_region = self._resolve_mouth_region(base_frame, params)
        frame_cache: OrderedDict[tuple[int, int], np.ndarray] = OrderedDict()
        max_cache_entries = 24

        def idle_scale_at(timestamp: float) -> float:
            if not params.character_idle_motion_enabled:
                return 1.0
            return 1.0 + (0.02 * ((math.sin(timestamp * math.pi * 2 / 4.0) + 1.0) / 2.0))

        def cached_rgba_frame(timestamp: float) -> np.ndarray:
            openness = self.lipsync_service.openness_at(timeline, timestamp) if timeline else 0.0
            openness = float(np.clip(openness * lipsync_intensity, 0.0, 1.0))
            zoom = idle_scale_at(timestamp)
            cache_key = (int(round(openness * 30)), int(round((zoom - 1.0) * 100)))
            if cache_key not in frame_cache:
                if len(frame_cache) >= max_cache_entries:
                    frame_cache.popitem(last=False)
                frame_cache[cache_key] = self._render_character_frame(
                    base_frame=base_frame,
                    openness=cache_key[0] / 30.0,
                    idle_scale=1.0 + (cache_key[1] / 100.0),
                    mouth_region=mouth_region,
                )
            else:
                frame_cache.move_to_end(cache_key)
            return frame_cache[cache_key]

        clip = VideoClip(
            frame_function=lambda timestamp: cached_rgba_frame(timestamp)[:, :, :3],
            duration=duration,
        )
        clip.mask = VideoClip(
            frame_function=lambda timestamp: cached_rgba_frame(timestamp)[:, :, 3].astype(np.float32) / 255.0,
            is_mask=True,
            duration=duration,
        )
        clip = clip.with_position(
            lambda timestamp: (
                x_pos,
                y_pos + self._idle_bob_offset(timestamp, scaled_image.height, bool(params.character_idle_motion_enabled)),
            )
        ).with_duration(duration)

        position_key = str(params.character_position or "bottom_right").lower()
        avoid_subtitles = position_key in {"bottom_left", "bottom_right", "bottom_center"} or (
            position_key == "custom" and y_pos >= int(canvas_size[1] * 0.45)
        )
        layout = CharacterOverlayLayout(
            x=x_pos,
            y=y_pos,
            width=scaled_image.width,
            height=scaled_image.height,
            avoid_subtitles=avoid_subtitles,
        )
        return CharacterOverlayResult(clip=clip, layout=layout)

    def calculate_position(
        self,
        canvas_size: tuple[int, int],
        overlay_size: tuple[int, int],
        position: str,
        margin_x: int,
        margin_y: int,
        custom_x: float,
        custom_y: float,
    ) -> tuple[int, int]:
        canvas_width, canvas_height = canvas_size
        overlay_width, overlay_height = overlay_size
        max_x = max(margin_x, canvas_width - overlay_width - margin_x)
        max_y = max(margin_y, canvas_height - overlay_height - margin_y)
        position_key = (position or "bottom_right").lower()

        preset_positions = {
            "top_left": (margin_x, margin_y),
            "top_right": (canvas_width - overlay_width - margin_x, margin_y),
            "bottom_left": (margin_x, canvas_height - overlay_height - margin_y),
            "bottom_right": (canvas_width - overlay_width - margin_x, canvas_height - overlay_height - margin_y),
            "top_center": ((canvas_width - overlay_width) / 2, margin_y),
            "bottom_center": ((canvas_width - overlay_width) / 2, canvas_height - overlay_height - margin_y),
            "center": ((canvas_width - overlay_width) / 2, (canvas_height - overlay_height) / 2),
        }
        if position_key == "custom":
            custom_resolved_x = (canvas_width - overlay_width) * (custom_x / 100.0)
            custom_resolved_y = (canvas_height - overlay_height) * (custom_y / 100.0)
            x_pos = custom_resolved_x
            y_pos = custom_resolved_y
        else:
            x_pos, y_pos = preset_positions.get(position_key, preset_positions["bottom_right"])

        return int(min(max(margin_x, x_pos), max_x)), int(min(max(margin_y, y_pos), max_y))

    def _idle_bob_offset(self, timestamp: float, height: int, enabled: bool) -> int:
        if not enabled:
            return 0
        amplitude = max(2, int(height * 0.01))
        return int(round(math.sin(timestamp * math.pi * 2 / 3.0) * amplitude))

    def _render_character_frame(
        self,
        base_frame: np.ndarray,
        openness: float,
        idle_scale: float,
        mouth_region: Optional[tuple[int, int, int, int]] = None,
    ) -> np.ndarray:
        frame_image = Image.fromarray(base_frame, mode="RGBA")
        if openness > 0.03:
            frame_image = self._apply_mouth_deformation(frame_image, openness, mouth_region)
        frame_image = self._apply_idle_scale(frame_image, idle_scale)
        return np.array(frame_image, dtype=np.uint8)

    def _apply_idle_scale(self, image: Image.Image, idle_scale: float) -> Image.Image:
        if abs(idle_scale - 1.0) < 0.001:
            return image
        width, height = image.size
        target_width = max(1, int(round(width * idle_scale)))
        target_height = max(1, int(round(height * idle_scale)))
        scaled_image = image.resize((target_width, target_height), Image.LANCZOS)
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        paste_x = int(round((width - target_width) / 2))
        paste_y = int(round((height - target_height) / 2))
        canvas.paste(scaled_image, (paste_x, paste_y), scaled_image)
        return canvas

    def _apply_mouth_deformation(
        self,
        image: Image.Image,
        openness: float,
        mouth_region: Optional[tuple[int, int, int, int]] = None,
    ) -> Image.Image:
        rgba = np.array(image, dtype=np.uint8)
        resolved_mouth_region = mouth_region or self._resolve_mouth_region(rgba)
        if not resolved_mouth_region:
            return image

        mouth_x, mouth_y, mouth_x2, mouth_y2 = resolved_mouth_region
        if mouth_x2 <= mouth_x or mouth_y2 <= mouth_y:
            return image

        mouth_region = rgba[mouth_y:mouth_y2, mouth_x:mouth_x2, :].copy()
        source_image = Image.fromarray(mouth_region, mode="RGBA")
        openness = float(np.clip(openness, 0.0, 1.0))

        # Apply a subtle horizontal squeeze + stronger vertical opening for a more natural jaw motion.
        width_factor = 1.0 - (openness * 0.10)
        stretch_factor = 1.0 + (openness * 0.72)
        stretched_width = max(1, int(round(source_image.width * width_factor)))
        stretched_height = max(1, int(round(source_image.height * stretch_factor)))
        stretched = source_image.resize((stretched_width, stretched_height), Image.BICUBIC)
        stretched_np = np.array(stretched, dtype=np.uint8)

        target_width = mouth_region.shape[1]
        if stretched_np.shape[1] <= target_width:
            pad_left = (target_width - stretched_np.shape[1]) // 2
            padded_w = np.zeros((stretched_np.shape[0], target_width, 4), dtype=np.uint8)
            padded_w[:, pad_left : pad_left + stretched_np.shape[1], :] = stretched_np
            stretched_np = padded_w
        else:
            crop_left = max(0, (stretched_np.shape[1] - target_width) // 2)
            stretched_np = stretched_np[:, crop_left : crop_left + target_width, :]

        target_height = mouth_region.shape[0]
        if stretched_np.shape[0] <= target_height:
            pad_top = (target_height - stretched_np.shape[0]) // 2
            padded = np.zeros((target_height, stretched_np.shape[1], 4), dtype=np.uint8)
            padded[pad_top : pad_top + stretched_np.shape[0], :, :] = stretched_np
            stretched_np = padded
        else:
            crop_top = max(0, (stretched_np.shape[0] - target_height) // 2)
            stretched_np = stretched_np[crop_top : crop_top + target_height, :, :]

        if (
            stretched_np.shape[0] != mouth_region.shape[0]
            or stretched_np.shape[1] != mouth_region.shape[1]
        ):
            return image

        # Blend only inside opaque mouth pixels so the portrait silhouette is preserved.
        source_alpha = mouth_region[:, :, 3].astype(np.float32) / 255.0
        blend_strength = openness * 0.96
        blend_mask = (source_alpha * blend_strength)[:, :, None]

        blended = mouth_region.astype(np.float32)
        blended[:, :, :3] = (
            blended[:, :, :3] * (1.0 - blend_mask)
            + stretched_np[:, :, :3].astype(np.float32) * blend_mask
        )
        blended[:, :, 3] = mouth_region[:, :, 3]
        rgba[mouth_y:mouth_y2, mouth_x:mouth_x2, :] = np.clip(blended, 0, 255).astype(np.uint8)
        return Image.fromarray(rgba, mode="RGBA")

    def _resolve_mouth_region(
        self,
        rgba: np.ndarray,
        params: VideoParams | None = None,
    ) -> Optional[tuple[int, int, int, int]]:
        manual_mouth_region = self._resolve_manual_mouth_region(rgba, params)
        if manual_mouth_region:
            return manual_mouth_region

        subject_bbox = self._resolve_subject_bbox(rgba)
        if not subject_bbox:
            return None

        left, top, right, bottom = subject_bbox
        face_bbox = self._resolve_face_bbox(rgba, subject_bbox)
        if face_bbox:
            f_left, f_top, f_right, f_bottom = face_bbox
            f_width = max(1, f_right - f_left)
            f_height = max(1, f_bottom - f_top)
            mouth_width = max(8, int(round(f_width * self.MOUTH_WIDTH_RATIO_FACE)))
            mouth_height = max(6, int(round(f_height * self.MOUTH_HEIGHT_RATIO_FACE)))
            mouth_x = int(round(f_left + ((f_width - mouth_width) / 2.0)))
            mouth_y = int(round(f_top + (f_height * self.MOUTH_Y_OFFSET_RATIO_FACE)))
        else:
            content_width = max(1, int(right - left))
            content_height = max(1, int(bottom - top))
            # Assume the head occupies the top ~30 % of the character (works for
            # both head-crop and full/half-body avatars).  Applying face ratios to
            # that estimated head region gives a much better mouth position than
            # using the old MOUTH_Y_OFFSET_RATIO_FALLBACK against the entire body.
            estimated_head_height = max(1, int(content_height * 0.30))
            mouth_width = max(8, int(content_width * self.MOUTH_WIDTH_RATIO_FACE))
            mouth_height = max(6, int(estimated_head_height * self.MOUTH_HEIGHT_RATIO_FACE))
            mouth_x = max(0, int(left + ((content_width - mouth_width) / 2)))
            mouth_y = max(0, int(top + (estimated_head_height * self.MOUTH_Y_OFFSET_RATIO_FACE)))

        frame_h, frame_w = rgba.shape[0], rgba.shape[1]
        mouth_x = int(np.clip(mouth_x, 0, frame_w - 1))
        mouth_y = int(np.clip(mouth_y, 0, frame_h - 1))
        mouth_x2 = int(np.clip(mouth_x + mouth_width, mouth_x + 1, frame_w))
        mouth_y2 = int(np.clip(mouth_y + mouth_height, mouth_y + 1, frame_h))
        if mouth_x2 <= mouth_x or mouth_y2 <= mouth_y:
            return None
        return (mouth_x, mouth_y, mouth_x2, mouth_y2)

    def _resolve_manual_mouth_region(
        self,
        rgba: np.ndarray,
        params: VideoParams | None,
    ) -> Optional[tuple[int, int, int, int]]:
        if not params or not bool(getattr(params, "character_manual_mapping_enabled", False)):
            return None

        frame_h, frame_w = rgba.shape[0], rgba.shape[1]

        def pct_to_px(value: float, total: int) -> int:
            return int(round(float(np.clip(value, 0.0, 100.0)) * (total / 100.0)))

        face_x = pct_to_px(float(getattr(params, "character_face_x", 0.0) or 0.0), frame_w)
        face_y = pct_to_px(float(getattr(params, "character_face_y", 0.0) or 0.0), frame_h)
        face_w = max(1, pct_to_px(float(getattr(params, "character_face_w", 0.0) or 0.0), frame_w))
        face_h = max(1, pct_to_px(float(getattr(params, "character_face_h", 0.0) or 0.0), frame_h))

        face_x2 = int(np.clip(face_x + face_w, face_x + 1, frame_w))
        face_y2 = int(np.clip(face_y + face_h, face_y + 1, frame_h))
        face_x = int(np.clip(face_x, 0, frame_w - 1))
        face_y = int(np.clip(face_y, 0, frame_h - 1))

        mouth_x = pct_to_px(float(getattr(params, "character_mouth_x", 0.0) or 0.0), frame_w)
        mouth_y = pct_to_px(float(getattr(params, "character_mouth_y", 0.0) or 0.0), frame_h)
        mouth_w = max(1, pct_to_px(float(getattr(params, "character_mouth_w", 0.0) or 0.0), frame_w))
        mouth_h = max(1, pct_to_px(float(getattr(params, "character_mouth_h", 0.0) or 0.0), frame_h))

        mouth_x2 = int(np.clip(mouth_x + mouth_w, mouth_x + 1, frame_w))
        mouth_y2 = int(np.clip(mouth_y + mouth_h, mouth_y + 1, frame_h))
        mouth_x = int(np.clip(mouth_x, 0, frame_w - 1))
        mouth_y = int(np.clip(mouth_y, 0, frame_h - 1))

        # Keep mouth mapping inside the manual face box when face mapping is defined.
        if face_x2 > face_x and face_y2 > face_y:
            mouth_x = int(np.clip(mouth_x, face_x, max(face_x, face_x2 - 1)))
            mouth_y = int(np.clip(mouth_y, face_y, max(face_y, face_y2 - 1)))
            mouth_x2 = int(np.clip(mouth_x2, mouth_x + 1, face_x2))
            mouth_y2 = int(np.clip(mouth_y2, mouth_y + 1, face_y2))

        if mouth_x2 <= mouth_x or mouth_y2 <= mouth_y:
            return None
        return (mouth_x, mouth_y, mouth_x2, mouth_y2)

    def _resolve_subject_bbox(self, rgba: np.ndarray) -> Optional[tuple[int, int, int, int]]:
        alpha = rgba[:, :, 3]
        non_transparent = np.argwhere(alpha > 8)
        if non_transparent.size == 0:
            return None
        top, left = non_transparent.min(axis=0)
        bottom, right = non_transparent.max(axis=0)
        return (int(left), int(top), int(right) + 1, int(bottom) + 1)

    def _resolve_face_bbox(
        self,
        rgba: np.ndarray,
        subject_bbox: tuple[int, int, int, int],
    ) -> Optional[tuple[int, int, int, int]]:
        if not CV2_AVAILABLE or cv2 is None:
            return None

        left, top, right, bottom = subject_bbox
        roi = rgba[top:bottom, left:right, :3]
        if roi.size == 0:
            return None
        bgr_roi = cv2.cvtColor(roi, cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(bgr_roi, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        if cascade.empty():
            return None
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.08,
            minNeighbors=4,
            minSize=(max(20, gray.shape[1] // 6), max(20, gray.shape[0] // 6)),
        )
        if len(faces) == 0:
            # Haar cascade misses most stylized/illustration avatars.
            # Retry with relaxed parameters before giving up so the heuristic
            # fallback at least has a chance to place the mouth correctly.
            faces = cascade.detectMultiScale(
                gray,
                scaleFactor=1.05,
                minNeighbors=2,
                minSize=(max(10, gray.shape[1] // 10), max(10, gray.shape[0] // 10)),
            )
        if len(faces) == 0:
            logger.debug(
                "face detection found no face in character image — "
                "falling back to heuristic mouth placement. "
                "Enable 'Manual Face/Lips Mapping' in the UI for precise control."
            )
            return None
        x, y, w, h = max(faces, key=lambda item: item[2] * item[3])
        return (left + int(x), top + int(y), left + int(x + w), top + int(y + h))