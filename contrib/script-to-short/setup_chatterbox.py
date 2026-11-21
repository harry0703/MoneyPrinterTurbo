"""Optional: set up the Chatterbox voice engine (one cloned voice, moods made by the model, not by pitch-shifting).

    .venv/Scripts/python setup_chatterbox.py            # Windows
    .venv/bin/python setup_chatterbox.py                # macOS / Linux

Run it with the repo's venv python (it needs edge-tts and imageio-ffmpeg to make the reference clip).
It creates <lab>/.venv (Python 3.11, installs chatterbox-tts) and <lab>/ref_voice.wav. The lab is ~/tts-lab, or $TTS_LAB.
The first render downloads the model weights (about 3 GB) from Hugging Face. Without this setup the pipeline uses edge-tts.

    --check      only report what is missing
    --ref-only   only (re)build ref_voice.wav, e.g. after choosing another --voice
    --voice V    edge-tts voice to clone (default en-US-AndrewNeural). To clone any other voice, put a clean, neutral
                 8-12 s recording at <lab>/ref_voice.wav yourself and this step is skipped."""
import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parent
LAB = Path(os.environ.get("TTS_LAB") or Path.home() / "tts-lab")
VENV_PY = next((p for p in (LAB / ".venv/Scripts/python.exe", LAB / ".venv/bin/python") if p.exists()), None)
REF_TEXT = ("Welcome to this medium of communication. Today I want to talk about something every developer knows. "
            "You push the code, the pipeline turns green, and for a moment, life feels simple.")


def run(cmd):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, check=True)


def make_venv():
    if VENV_PY:
        return
    if shutil.which("uv"):  # uv fetches a matching Python by itself
        run(["uv", "venv", "--python", "3.11", str(LAB / ".venv")])
        return
    for py in (["py", "-3.11"], ["python3.11"], ["python3.12"], ["python3.10"]):
        if shutil.which(py[0]):
            run([*py, "-m", "venv", str(LAB / ".venv")])
            return
    sys.exit("chatterbox-tts needs Python 3.10-3.12 and none was found. Install uv (https://docs.astral.sh/uv/) or Python 3.11, then rerun.")


def install():
    global VENV_PY
    LAB.mkdir(parents=True, exist_ok=True)
    make_venv()
    VENV_PY = next(p for p in (LAB / ".venv/Scripts/python.exe", LAB / ".venv/bin/python") if p.exists())
    pkgs = ["chatterbox-tts", "soundfile", "setuptools<81"]  # setuptools<81: the watermarker imports pkg_resources, newer setuptools drops it
    run(["uv", "pip", "install", "--python", str(VENV_PY), *pkgs] if shutil.which("uv") else [str(VENV_PY), "-m", "pip", "install", *pkgs])


def make_reference(voice):
    ref = LAB / "ref_voice.wav"
    if ref.exists() and "--ref-only" not in sys.argv:
        print(f"{ref} exists, keeping it")
        return
    sys.path.insert(0, str(REPO / "skills/anime-talking-short/scripts"))
    import numpy as np
    import render
    mp3, ws = asyncio.run(render.speak(REF_TEXT, voice, "+0%", "+0Hz"))  # neutral: no rate or pitch offset
    raw = subprocess.run([render.ffmpeg(), "-v", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", "24000", "-"],
                         input=mp3, capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.int16)[int(max(0, ws[0][0] - 0.05) * 24000): int((ws[-1][1] + 0.15) * 24000)]
    LAB.mkdir(parents=True, exist_ok=True)
    with wave.open(str(ref), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000), w.writeframes(x.tobytes())
    print(f"wrote {ref} ({len(x) / 24000:.1f} s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--ref-only", action="store_true")
    ap.add_argument("--voice", default="en-US-AndrewNeural")
    a = ap.parse_args()
    if a.check:
        print(f"lab: {LAB}\n  venv with python: {'yes' if VENV_PY else 'MISSING'}\n  ref_voice.wav:    {'yes' if (LAB / 'ref_voice.wav').exists() else 'MISSING'}")
        sys.exit(0 if VENV_PY and (LAB / "ref_voice.wav").exists() else 1)
    if not a.ref_only:
        install()
    make_reference(a.voice)
    if VENV_PY or not a.ref_only:
        print("done. Renders now use the Chatterbox voice (--engine auto); the first one downloads ~3 GB of model weights.")
    else:
        print("reference clip written; run without --ref-only to create the environment (until then renders use edge-tts)")
