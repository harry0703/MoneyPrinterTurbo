"""Perfiles de avatar a partir de fotografías autorizadas.

No se hace identificación de personas: solo se estima una caja de rostro para
encuadrar y animar. Sin OpenCV instalado se usa una heurística de tono de piel;
el resultado se marca como heurístico y el panel permite ajustar el encuadre.
No se recorta el fondo porque no hay segmentación disponible en este equipo.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageStat

from app.services.personal_studio.presets import AVATAR_STYLES
from app.services.personal_studio.security import (
    StudioError,
    atomic_json,
    build_consent,
    confined_path,
    delete_tree,
    digest_bytes,
    ensure_private,
    read_json,
    require_consent,
    safe_identifier,
    studio_root,
    timestamp,
)

SUPPORTED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MIN_SIDE = 512
PORTRAIT_SIZE = 1024


class AvatarError(StudioError):
    pass


def _open_image(payload: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(payload))
        image.load()
    except Exception as exc:  # noqa: BLE001 - Pillow lanza muchos tipos
        raise AvatarError("La imagen no es válida o está dañada") from exc
    image = ImageOps.exif_transpose(image)
    return image.convert("RGB")


def _cv2_face_box(image: Image.Image) -> tuple[int, int, int, int] | None:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return None
    try:
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        if cascade.empty():
            return None
        gray = np.asarray(image.convert("L"))
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
    except Exception:  # noqa: BLE001 - detección opcional
        return None
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda box: int(box[2]) * int(box[3]))
    return int(x), int(y), int(w), int(h)


def _skin_mask_box(image: Image.Image) -> tuple[int, int, int, int] | None:
    """Caja aproximada por tono de piel; heurística, no detector facial."""
    small = image.copy()
    small.thumbnail((180, 180))
    width, height = small.size
    pixels = small.load()
    xs: list[int] = []
    ys: list[int] = []
    for y in range(0, int(height * 0.85)):
        for x in range(width):
            r, g, b = pixels[x, y]
            if r > 95 and g > 40 and b > 20 and max(r, g, b) - min(r, g, b) > 15:
                if abs(r - g) > 12 and r > g and r > b:
                    xs.append(x)
                    ys.append(y)
    if len(xs) < 0.01 * width * height:
        return None
    xs.sort()
    ys.sort()
    trim_x = xs[int(len(xs) * 0.05) : max(1, int(len(xs) * 0.95))]
    trim_y = ys[int(len(ys) * 0.05) : max(1, int(len(ys) * 0.95))]
    if not trim_x or not trim_y:
        return None
    scale_x = image.width / float(width)
    scale_y = image.height / float(height)
    left, right = min(trim_x), max(trim_x)
    top, bottom = min(trim_y), max(trim_y)
    box_w = (right - left + 1) * scale_x
    box_h = (bottom - top + 1) * scale_y
    if box_w < image.width * 0.08 or box_h < image.height * 0.08:
        return None
    return (
        int(left * scale_x),
        int(top * scale_y),
        int(box_w),
        int(box_h),
    )


def detect_face(image: Image.Image) -> dict:
    box = _cv2_face_box(image)
    source = "opencv"
    if box is None:
        box = _skin_mask_box(image)
        source = "skin-heuristic"
    if box is None:
        return {"box": None, "source": "none"}
    x, y, w, h = box
    x = max(0, min(image.width - 1, x))
    y = max(0, min(image.height - 1, y))
    w = max(1, min(image.width - x, w))
    h = max(1, min(image.height - y, h))
    return {"box": [x, y, w, h], "source": source}


def _square_crop(image: Image.Image, face: dict) -> tuple[Image.Image, tuple[float, float, float, float]]:
    """Recorta un cuadrado alrededor del rostro y devuelve la caja normalizada."""
    width, height = image.size
    box = face.get("box")
    if box:
        x, y, w, h = box
        center_x = x + w / 2.0
        center_y = y + h * 0.55
        side = min(max(w, h) * 3.4, min(width, height))
        side = max(side, min(width, height) * 0.35)
    else:
        center_x = width / 2.0
        center_y = height * 0.42
        side = min(width, height)
    side = min(side, min(width, height))
    left = center_x - side / 2.0
    top = center_y - side / 2.0
    left = max(0.0, min(width - side, left))
    top = max(0.0, min(height - side, top))
    crop = image.crop((int(left), int(top), int(left + side), int(top + side)))
    normalized = (
        (x - left) / side if box else 0.2,
        (y - top) / side if box else 0.2,
        w / side if box else 0.6,
        h / side if box else 0.5,
    )
    return crop, normalized


def _quality(image: Image.Image) -> dict:
    gray = image.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    sharpness = ImageStat.Stat(edges).var[0]
    brightness = ImageStat.Stat(gray).mean[0]
    contrast = ImageStat.Stat(gray).stddev[0]
    width, height = image.size
    warnings: list[str] = []
    score = 100.0
    if min(width, height) < MIN_SIDE:
        warnings.append(f"La imagen es pequeña ({width}×{height}); usa al menos {MIN_SIDE} px.")
        score -= 25
    if sharpness < 45:
        warnings.append("La imagen parece poco nítida.")
        score -= 20
    if brightness < 55:
        warnings.append("La imagen está oscura.")
        score -= 15
    elif brightness > 215:
        warnings.append("La imagen está sobreexpuesta.")
        score -= 15
    if contrast < 25:
        warnings.append("La imagen tiene poco contraste.")
        score -= 10
    return {
        "width": width,
        "height": height,
        "sharpness": round(sharpness, 1),
        "brightness": round(brightness, 1),
        "contrast": round(contrast, 1),
        "score": max(0.0, min(100.0, score)),
        "warnings": warnings,
    }


def _dominant_palette(image: Image.Image, face: dict) -> dict[str, str]:
    """Colores dominantes de la foto para la caricatura 2D."""
    sample = image.copy()
    sample.thumbnail((120, 120))
    quantized = sample.quantize(colors=5, method=Image.Quantize.MEDIANCUT).convert("RGB")
    colors = sorted(quantized.getcolors(120 * 120) or [], reverse=True)[:5]
    hexes = ["#%02X%02X%02X" % color for _, color in colors] or ["#4A90D9"]
    primary = hexes[0]
    accent = hexes[1] if len(hexes) > 1 else "#FFD24A"

    def darken(value: str, factor: float = 0.72) -> str:
        r, g, b = (int(value[i : i + 2], 16) for i in (1, 3, 5))
        return "#%02X%02X%02X" % (int(r * factor), int(g * factor), int(b * factor))

    def lighten(value: str, factor: float = 0.75) -> str:
        r, g, b = (int(value[i : i + 2], 16) for i in (1, 3, 5))
        return "#%02X%02X%02X" % (
            int(r + (255 - r) * factor),
            int(g + (255 - g) * factor),
            int(b + (255 - b) * factor),
        )

    return {
        "blue": primary,
        "blue_dark": darken(primary),
        "blue_light": lighten(primary),
        "yellow": accent,
    }


def _skin_color(image: Image.Image, face_box: list[float] | None) -> str:
    if not face_box:
        return "#E8B98F"
    x, y, w, h = face_box
    left = int((x + w * 0.2) * image.width)
    right = int((x + w * 0.8) * image.width)
    top = int((y + h * 0.05) * image.height)
    bottom = int((y + h * 0.35) * image.height)
    if right - left < 4 or bottom - top < 4:
        return "#E8B98F"
    patch = image.crop((left, top, right, bottom)).convert("RGB")
    mean = ImageStat.Stat(patch).mean
    return "#%02X%02X%02X" % tuple(int(max(0, min(255, value))) for value in mean[:3])


class AvatarStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or studio_root()).resolve()
        self.avatars = confined_path(self.root, "avatars")
        self.avatars.mkdir(parents=True, exist_ok=True)

    # -- rutas ---------------------------------------------------------
    def avatar_dir(self, avatar_id: str) -> Path:
        identifier = safe_identifier(avatar_id, "perfil de avatar")
        directory = confined_path(self.avatars, identifier)
        if not directory.is_dir():
            raise AvatarError(f"El avatar no existe: {identifier}")
        return directory

    def _meta_path(self, avatar_id: str) -> Path:
        return self.avatar_dir(avatar_id) / "avatar.json"

    def _save(self, avatar: dict) -> dict:
        avatar["updated_at"] = timestamp()
        atomic_json(self._meta_path(avatar["id"]), avatar)
        return avatar

    def image(self, avatar_id: str, kind: str = "portrait") -> Path:
        avatar = self.get(avatar_id)
        relative = (avatar.get("files") or {}).get(kind)
        if not relative:
            raise AvatarError(f"El avatar no tiene el archivo {kind}")
        path = confined_path(self.avatar_dir(avatar_id), relative)
        if not path.is_file():
            raise AvatarError(f"Falta el archivo {kind} del avatar")
        return path

    # -- CRUD ----------------------------------------------------------
    def create(
        self,
        *,
        name: str,
        style: str,
        consent: dict,
        filename: str,
        payload: bytes,
        background: str = "estudio",
    ) -> dict:
        if style not in AVATAR_STYLES:
            raise AvatarError("Estilo de avatar no soportado")
        name = str(name or "").strip()
        if len(name) < 2 or len(name) > 80:
            raise AvatarError("El nombre del avatar debe tener entre 2 y 80 caracteres")
        suffix = Path(str(filename or "")).suffix.lower()
        if suffix not in SUPPORTED_IMAGE_EXTENSIONS:
            raise AvatarError(
                "Formato no admitido. Usa: " + ", ".join(SUPPORTED_IMAGE_EXTENSIONS)
            )
        if not payload:
            raise AvatarError("La imagen está vacía")
        if len(payload) > MAX_IMAGE_BYTES:
            raise AvatarError("La imagen supera los 25 MB")
        document = build_consent(consent, scope=("imagen",))
        image = _open_image(payload)
        if min(image.size) < MIN_SIDE:
            raise AvatarError(
                f"La imagen debe medir al menos {MIN_SIDE} px por lado; recibida {image.size[0]}×{image.size[1]}"
            )
        if max(image.size) > 4096:
            image.thumbnail((4096, 4096))

        identifier = f"a_{uuid.uuid4().hex[:10]}"
        directory = confined_path(self.avatars, identifier)
        directory.mkdir(parents=True, exist_ok=False)
        ensure_private(directory)

        face = detect_face(image)
        quality = _quality(image)
        crop, face_normalized = _square_crop(image, face)
        portrait = crop.resize((PORTRAIT_SIZE, PORTRAIT_SIZE), Image.LANCZOS)
        thumb = portrait.resize((256, 256), Image.LANCZOS)

        source_path = directory / "source.png"
        portrait_path = directory / "portrait.png"
        thumb_path = directory / "thumb.png"
        image.save(source_path, format="PNG")
        portrait.save(portrait_path, format="PNG")
        thumb.save(thumb_path, format="PNG")
        for path in (source_path, portrait_path, thumb_path):
            ensure_private(path)

        palette = _dominant_palette(image, face)
        avatar = {
            "schema_version": 1,
            "id": identifier,
            "name": name,
            "style": style,
            "style_label": AVATAR_STYLES[style]["label"],
            "engine": AVATAR_STYLES[style]["engine"],
            "background": str(background),
            "consent": document,
            "is_minor": bool(document.get("is_minor")),
            "files": {
                "source": "source.png",
                "portrait": "portrait.png",
                "thumb": "thumb.png",
            },
            "image": {
                **quality,
                "face": face,
                "face_normalized": [round(value, 4) for value in face_normalized],
                "sha256": digest_bytes(payload),
            },
            "cartoon": {
                "palette": palette,
                "skin": _skin_color(image, face_normalized),
            },
            "created_at": timestamp(),
            "updated_at": timestamp(),
        }
        self._save(avatar)
        return avatar

    def get(self, avatar_id: str) -> dict:
        return read_json(self._meta_path(avatar_id))

    def list(self) -> list[dict]:
        items: list[dict] = []
        for entry in sorted(self.avatars.iterdir()):
            if not entry.is_dir():
                continue
            path = entry / "avatar.json"
            if not path.is_file():
                continue
            try:
                items.append(read_json(path))
            except StudioError:
                continue
        items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return items

    def update(
        self,
        avatar_id: str,
        *,
        name: str | None = None,
        background: str | None = None,
    ) -> dict:
        avatar = self.get(avatar_id)
        if name is not None:
            name = str(name).strip()
            if len(name) < 2 or len(name) > 80:
                raise AvatarError("El nombre del avatar debe tener entre 2 y 80 caracteres")
            avatar["name"] = name
        if background is not None:
            avatar["background"] = str(background)[:40]
        return self._save(avatar)

    def remove(self, avatar_id: str) -> None:
        avatar = self.get(avatar_id)
        require_consent(avatar.get("consent"), ("imagen",))
        delete_tree(self.avatars, avatar_id)

    # -- vista previa --------------------------------------------------
    def preview(self, avatar_id: str, destination: str | Path) -> Path:
        """Miniatura con fondo para revisar el encuadre antes de animar."""
        avatar = self.get(avatar_id)
        portrait = Image.open(self.image(avatar_id, "portrait")).convert("RGB")
        canvas = _backdrop(str(avatar.get("background") or "estudio"), (512, 640))
        fitted = ImageOps.fit(portrait, (512, 640), method=Image.LANCZOS)
        canvas.paste(fitted, (0, 0))
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(target, format="PNG")
        return target


def _backdrop(scene: str, size: tuple[int, int]) -> Image.Image:
    """Fondo local determinista para avatares; sin descargas."""
    width, height = size
    palettes = {
        "estudio": ((28, 38, 56), (8, 12, 20)),
        "oficina": ((224, 228, 236), (140, 150, 165)),
        "tecnologico": ((18, 32, 64), (2, 8, 20)),
    }
    top, bottom = palettes.get(scene, palettes["estudio"])
    canvas = Image.new("RGB", size)
    draw = ImageDraw.Draw(canvas)
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = (
            int(top[0] + (bottom[0] - top[0]) * ratio),
            int(top[1] + (bottom[1] - top[1]) * ratio),
            int(top[2] + (bottom[2] - top[2]) * ratio),
        )
        draw.line([(0, y), (width, y)], fill=color)
    return canvas
