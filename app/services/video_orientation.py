"""从抽样画面判断横倒方向，视频帧始终在本地处理。"""

import hashlib
import os
import tempfile
import threading
from collections.abc import Iterable, Iterator
from functools import lru_cache
from pathlib import Path

import numpy as np
import requests
from filelock import FileLock
from loguru import logger
from PIL import Image, ImageOps

from app.config import config
from app.utils import utils
from app.utils.request_logging import trace_http_call


# 固定官方 RightWayUp Fast INT8 的版本和权重校验值，避免更新后方向判断悄然变化。
_MODEL_REVISION = "69076d99f16fafbc3d7e12958390972b5f291e81"
_MODEL_NAME = "fast-s224-int8.onnx"
_MODEL_URL = f"https://huggingface.co/ortusai/rightwayup/resolve/{_MODEL_REVISION}/{_MODEL_NAME}"
_MODEL_SIZE = 24_437_831
_MODEL_SHA256 = "5f07e08676068e798efc9206f4ca4130dfc6073ad57289cf6b4c9f8805a5069f"
_INPUT_SIZE = 224
_RGB_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_RGB_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
_CONFIDENCE_BINS = np.arange(-10, 11)
_STRICT_CONFIDENCE = 0.738
_VIDEO_SAMPLE_POINTS = (0.05, 0.2, 0.4, 0.6, 0.85)
_load_lock = threading.Lock()


class SidewaysDetector:
    def __init__(self, session):
        self._session = session

    def _direction(self, image: Image.Image) -> int | None:
        image = ImageOps.contain(image.convert("RGB"), (_INPUT_SIZE, _INPUT_SIZE), Image.Resampling.BICUBIC)
        canvas = Image.new("RGB", (_INPUT_SIZE, _INPUT_SIZE), (124, 116, 104))
        canvas.paste(image, ((_INPUT_SIZE - image.width) // 2, (_INPUT_SIZE - image.height) // 2))
        pixels = ((np.asarray(canvas, dtype=np.float32) / 255.0 - _RGB_MEAN) / _RGB_STD)
        probabilities = self._session.run(["prob"], {"image": pixels.transpose(2, 0, 1)[None]})[0][0]
        peak = int(np.argmax(probabilities))
        confidence = probabilities[(peak + _CONFIDENCE_BINS) % 360].sum()
        snapped = ((peak + 45) // 90 * 90) % 360
        distance = abs((peak - snapped + 180) % 360 - 180)
        if confidence >= _STRICT_CONFIDENCE and distance <= 20:
            return snapped
        return None

    def is_sideways(self, images: Iterable[Image.Image]) -> bool:
        # 至少三帧确认同一个横倒方向。清晰正向或方向冲突的素材保留，保护倾斜镜头和混剪。
        direction = None
        matching_frames = 0
        try:
            for image in images:
                measured = self._direction(image)
                if measured is None:
                    continue
                if measured not in (90, 270) or (direction is not None and direction != measured):
                    return False
                direction = measured
                matching_frames += 1
        except Exception as exc:
            logger.debug(f"could not classify video orientation: {type(exc).__name__}")
            return False
        return matching_frames >= 3

    def is_sideways_video(self, clip) -> bool:
        def frames() -> Iterator[Image.Image]:
            for fraction in _VIDEO_SAMPLE_POINTS:
                yield Image.fromarray(clip.get_frame(clip.duration * fraction))

        return self.is_sideways(frames())


def _fetch_model(path: Path) -> None:
    digest = hashlib.sha256()
    size = 0
    temporary = None
    try:
        with (
            trace_http_call(
                "GET",
                requests.get,
                _MODEL_URL,
                stream=True,
                timeout=(5, 25),
                proxies=config.proxy,
            ) as response,
            tempfile.NamedTemporaryFile(dir=path.parent, prefix=".orientation-", delete=False) as output,
        ):
            temporary = Path(output.name)
            response.raise_for_status()
            for chunk in response.iter_content(1024 * 1024):
                size += len(chunk)
                if size > _MODEL_SIZE:
                    raise ValueError("orientation model size mismatch")
                digest.update(chunk)
                output.write(chunk)
        if size != _MODEL_SIZE or digest.hexdigest() != _MODEL_SHA256:
            raise ValueError("orientation model checksum mismatch")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@lru_cache(maxsize=1)
def _load_detector(path: Path) -> SidewaysDetector:
    # onnxruntime 随现有 faster-whisper 依赖安装，只在爱给网竖屏任务中加载。
    import onnxruntime

    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(path.with_suffix(".lock"), timeout=60):
        valid = False
        if path.is_file() and path.stat().st_size == _MODEL_SIZE:
            with path.open("rb") as model_file:
                valid = hashlib.file_digest(model_file, "sha256").hexdigest() == _MODEL_SHA256
        if not valid:
            logger.info("Downloading the Aigei video orientation model (24 MB)")
            _fetch_model(path)

    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 2
    session = onnxruntime.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
    return SidewaysDetector(session)


def load_detector() -> SidewaysDetector | None:
    path = Path(utils.root_dir()) / "models" / f"rightwayup-{_MODEL_SHA256[:12]}.onnx"
    with _load_lock:
        try:
            return _load_detector(path)
        except Exception as exc:
            logger.warning(
                f"Aigei orientation model unavailable; checking displayed dimensions only: {type(exc).__name__}"
            )
            return None
