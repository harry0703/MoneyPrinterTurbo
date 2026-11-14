"""Chatterbox batch synthesis. Runs in ~/tts-lab's venv (torch lives there), called by chatterbox_voice.prepare().
usage: cb_synth.py jobs.json ref.wav
jobs.json: [{"out": wav path, "tts_text": str, "n_words": int, "exag": float, "cfg": float, "seed": int}]
Existing outputs are skipped, so an interrupted run resumes."""
import functools
import json
import sys
import time
from pathlib import Path

import torch

torch.load = functools.partial(torch.load, map_location=torch.device("cpu"))  # the checkpoints were saved on CUDA
import soundfile as sf  # noqa: E402 (after the torch.load patch)
from chatterbox.tts import ChatterboxTTS  # noqa: E402

jobs, ref = json.load(open(sys.argv[1], encoding="utf-8")), sys.argv[2]
model = ChatterboxTTS.from_pretrained(device="cpu")
for j in jobs:
    out = Path(j["out"])
    if out.exists():
        continue
    n = j["n_words"]
    for attempt in range(4):  # the model sometimes mumbles or runs on: retry with another seed when the length is implausible
        torch.manual_seed(j["seed"] + attempt)
        t = time.time()
        x = model.generate(j["tts_text"], audio_prompt_path=ref, exaggeration=j["exag"], cfg_weight=j["cfg"]).squeeze().numpy()
        dur = len(x) / model.sr
        ok = 0.15 * n + 0.3 < dur < 0.8 * n + 1.5
        print(f"{out.name}: {dur:.2f}s for {n} words, {time.time() - t:.0f}s, seed+{attempt}{'' if ok else ' (implausible, retrying)'}", flush=True)
        if ok:
            break
    tmp = out.with_suffix(".tmp.wav")
    sf.write(tmp, x, model.sr)
    tmp.replace(out)
