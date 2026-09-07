from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from loguru import logger
from PIL import Image


SUPPORTED_CHARACTER_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_CHARACTER_IMAGE_BYTES = 50 * 1024 * 1024
MAX_CHARACTER_DIMENSION = 8192
MIN_CHARACTER_DIMENSION = 32


@dataclass
class PreparedCharacterImage:
    image: Image.Image
    source_path: str
    original_size: tuple[int, int]
    content_size: tuple[int, int]


@dataclass
class ScaledCharacterImage:
    image: Image.Image
    width: int
    height: int


class CharacterImageService:
    def prepare(
        self,
        image_path: str,
        remove_background: bool = True,
        crop_transparent_edges: bool = True,
    ) -> PreparedCharacterImage:
        path = Path(image_path or "")
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"character image not found: {image_path}")
        if path.suffix.lower() not in SUPPORTED_CHARACTER_IMAGE_EXTENSIONS:
            raise ValueError(f"unsupported character image format: {path.suffix.lower()}")
        if path.stat().st_size > MAX_CHARACTER_IMAGE_BYTES:
            raise ValueError(f"character image too large: {path.stat().st_size} bytes")

        with Image.open(path) as source_image:
            rgba_image = source_image.convert("RGBA")
        if (
            rgba_image.width < MIN_CHARACTER_DIMENSION
            or rgba_image.height < MIN_CHARACTER_DIMENSION
            or rgba_image.width > MAX_CHARACTER_DIMENSION
            or rgba_image.height > MAX_CHARACTER_DIMENSION
        ):
            raise ValueError(f"character image dimensions out of range: {rgba_image.size}")

        processed_image = rgba_image
        if remove_background and not self._has_meaningful_alpha(rgba_image):
            try:
                processed_image = self._remove_background_from_edges(rgba_image)
            except Exception as exc:
                logger.warning(f"character background removal failed, using original image: {exc}")
                processed_image = rgba_image

        if crop_transparent_edges:
            processed_image = self._crop_transparent_edges(processed_image)
        return PreparedCharacterImage(
            image=processed_image,
            source_path=str(path),
            original_size=rgba_image.size,
            content_size=processed_image.size,
        )

    def scale_for_canvas(
        self,
        prepared_image: PreparedCharacterImage,
        canvas_size: tuple[int, int],
        scale: float,
        max_width_ratio: float,
        max_height_ratio: float,
    ) -> ScaledCharacterImage:
        canvas_width, canvas_height = canvas_size
        requested_scale = max(0.05, float(scale or 0.28)) / 0.28
        allowed_width = canvas_width * min(0.95, max(0.05, float(max_width_ratio or 0.35) * requested_scale))
        allowed_height = canvas_height * min(0.95, max(0.05, float(max_height_ratio or 0.45) * requested_scale))

        source_width, source_height = prepared_image.image.size
        resize_factor = min(allowed_width / max(1, source_width), allowed_height / max(1, source_height))
        target_width = max(1, int(round(source_width * resize_factor)))
        target_height = max(1, int(round(source_height * resize_factor)))
        resized_image = prepared_image.image.resize((target_width, target_height), Image.LANCZOS)
        return ScaledCharacterImage(image=resized_image, width=target_width, height=target_height)

    def _has_meaningful_alpha(self, image: Image.Image) -> bool:
        alpha_channel = image.getchannel("A")
        alpha_min, alpha_max = alpha_channel.getextrema()
        return alpha_min < alpha_max or alpha_max < 255

    def _crop_transparent_edges(self, image: Image.Image) -> Image.Image:
        alpha_channel = image.getchannel("A")
        bounding_box = alpha_channel.getbbox()
        if not bounding_box:
            return image
        return image.crop(bounding_box)

    def _remove_background_from_edges(self, image: Image.Image, tolerance: int = 28) -> Image.Image:
        rgba_array = np.array(image, dtype=np.uint8)
        height, width = rgba_array.shape[:2]
        visited = np.zeros((height, width), dtype=bool)
        seeds = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]

        def within_tolerance(pixel: np.ndarray, reference: np.ndarray) -> bool:
            return bool(np.max(np.abs(pixel.astype(np.int16) - reference.astype(np.int16))) <= tolerance)

        for seed_x, seed_y in seeds:
            if visited[seed_y, seed_x]:
                continue
            reference_color = rgba_array[seed_y, seed_x, :3].copy()
            queue: deque[tuple[int, int]] = deque([(seed_x, seed_y)])
            max_iterations = max(1, width * height * 2)
            iterations = 0
            while queue and iterations < max_iterations:
                iterations += 1
                x, y = queue.popleft()
                if x < 0 or y < 0 or x >= width or y >= height or visited[y, x]:
                    continue
                visited[y, x] = True
                current_pixel = rgba_array[y, x]
                if current_pixel[3] == 0 or not within_tolerance(current_pixel[:3], reference_color):
                    continue
                rgba_array[y, x, 3] = 0
                queue.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))

        return Image.fromarray(rgba_array, mode="RGBA")