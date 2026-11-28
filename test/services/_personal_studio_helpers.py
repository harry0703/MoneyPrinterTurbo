"""Utilidades compartidas por las pruebas de BYNEX AI Personal Studio."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

VOICE_CONSENT = {
    "subject_name": "Nelson Julio",
    "granted": True,
    "age_confirmed": True,
    "scope": ["voz"],
}
IMAGE_CONSENT = {
    "subject_name": "Nelson Julio",
    "granted": True,
    "age_confirmed": True,
    "scope": ["imagen"],
}


def make_speechlike_wav(path: str | Path, *, seconds: float = 8.0, rate: int = 24000) -> Path:
    """Tono modulado con pausas: suficiente para nivel, ruido y silencios."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(seconds * rate)
    payload = bytearray()
    for index in range(frames):
        time = index / rate
        phase = time % 2.4
        # 1.8 s de voz y 0.6 s de pausa, con envolvente suave.
        if phase > 1.8:
            value = 0
        else:
            envelope = math.sin(math.pi * phase / 1.8) ** 0.5
            value = int(
                9000
                * envelope
                * math.sin(2 * math.pi * 180 * time)
            )
        payload += struct.pack("<h", max(-32768, min(32767, value)))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(payload))
    return path
