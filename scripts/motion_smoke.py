"""Render a Motion Studio video from a ready-made storyboard, without calling an LLM.

Usage: python scripts/motion_smoke.py <storyboard.json> <voice> [character.glb|png] [out_dir]
Checks the voice, scene engine, host and renderer end to end. Needs Playwright.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.motion import Storyboard  # noqa: E402
from app.services.motion import pipeline, renderer  # noqa: E402


def main() -> None:
    source, voice = Path(sys.argv[1]), sys.argv[2]
    character = Path(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] != "-" else None
    out_dir = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("storage/motion/smoke")
    out_dir.mkdir(parents=True, exist_ok=True)
    storyboard = Storyboard.model_validate(json.loads(source.read_text(encoding="utf-8")))
    started = time.time()
    speech = pipeline.prepare(out_dir, storyboard, voice, character)
    print(f"voice: {len(speech.words)} words, {speech.duration:.1f}s ({time.time() - started:.0f}s)")
    video = renderer.render(out_dir, lambda done, total: print(f"\rframes {done}/{total}", end="", flush=True))
    print(f"\nwrote {video} ({time.time() - started:.0f}s total)")


if __name__ == "__main__":
    main()
