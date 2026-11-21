"""Chatterbox voice engine for render.py: one cloned voice, emotion from the model (exaggeration / cfg), not from pitch shifting.
Needs a lab folder (default ~/tts-lab, or $TTS_LAB) holding .venv with chatterbox-tts and ref_voice.wav (a neutral 10 s clip of the voice to clone).
Set it up with `python setup_chatterbox.py` from the repo, or by hand as described in anime-talking-short/SKILL.md.
Lines are cached by their settings in ~/tts-lab/cache, so re-renders that only change visuals cost nothing."""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

LAB = Path(os.environ.get("TTS_LAB") or Path.home() / "tts-lab")
PY = next((p for p in (LAB / ".venv/Scripts/python.exe", LAB / ".venv/bin/python") if p.exists()), LAB / ".venv/bin/python")
REF, CACHE = LAB / "ref_voice.wav", LAB / "cache"
SEED = 7
# tone -> (exaggeration, cfg_weight, tempo, gain dB). Higher exaggeration = bigger swings and higher pitch; lower cfg = slower, more deliberate.
CB_TONES = {"normal": (0.5, 0.5, 1.0, 0), "hype": (0.8, 0.4, 1.0, 1), "excited": (0.95, 0.4, 1.0, 1), "elated": (1.3, 0.3, 1.0, 1.5),
            "relaxed": (0.35, 0.5, 0.97, -0.5), "sarcastic": (0.35, 0.55, 0.95, -0.5), "tired": (0.2, 0.6, 0.93, -1.5),
            "bored": (0.2, 0.6, 0.92, -2), "exhausted": (0.1, 0.7, 0.88, -2.5)}
LOUD = 0.07  # target RMS of the speech (float full scale) before tone gain; the final mix is normalised to -14 LUFS anyway


def available():
    """True when the engine is set up (the auto engine falls back to edge-tts otherwise)"""
    return PY.exists() and REF.exists()


def words_of(text):
    return re.findall(r"[A-Za-z0-9']+", text)


def tts_text(text):
    """A spelled-out name ("A J", from {AJ=A J}) becomes "A. J." so the model says the letters"""
    return re.sub(r"\b(?:[A-Z] )+[A-Z]\b\.?", lambda m: ". ".join(m[0].rstrip(".").split()) + ".", text)


def path_for(seg):
    ex, cfg, _, _ = CB_TONES[seg["tone"]]
    key = hashlib.sha1(f"{tts_text(seg['text'])}|{ex}|{cfg}|{SEED}|{REF.stat().st_mtime}".encode()).hexdigest()[:12]
    return CACHE / f"{key}.wav"


def prepare(segs):
    """Generate every missing line in one model session (about 12x slower than real time on a CPU)."""
    CACHE.mkdir(exist_ok=True)
    jobs = [{"out": str(path_for(s)), "tts_text": tts_text(s["text"]), "n_words": len(words_of(s["text"])), "exag": CB_TONES[s["tone"]][0],
             "cfg": CB_TONES[s["tone"]][1], "seed": SEED} for s in segs if not s.get("silent") and not path_for(s).exists()]
    if not jobs:
        return
    jf = CACHE / "jobs.json"
    jf.write_text(json.dumps(jobs), encoding="utf-8")
    print(f"chatterbox: generating {len(jobs)} lines (slow on CPU, cached afterwards)", flush=True)
    subprocess.run([str(PY), str(Path(__file__).with_name("cb_synth.py")), str(jf), str(REF)], check=True,
                   env={**__import__("os").environ, "HF_HUB_DISABLE_SYMLINKS_WARNING": "1", "PYTHONIOENCODING": "utf-8"})


def syllables(word):
    w = re.sub(r"[^a-z]", "", word.lower())
    n = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and not w.endswith(("le", "ee")) and n > 1:
        n -= 1
    if w.endswith("ed") and not w.endswith(("ted", "ded")) and n > 1:
        n -= 1
    return max(n, 1)


def estimate_words(x, text, sr):
    """Word times for a clip with no timestamps (Chatterbox has none). The clip splits into voiced chunks at its real pauses;
    each pause is pinned to the script boundary it most likely is (punctuation preferred), and the words inside a chunk share its
    time by syllables and length. Mean error 56 ms, p90 121 ms against Edge's own timestamps (whisper tiny.en was worse: 139 ms
    against audible onsets). -> [(start, end, word)] in seconds"""
    hop = sr // 100
    env = np.sqrt(np.convolve(x.astype(float) ** 2, np.ones(hop * 2) / (hop * 2), "same"))[::hop]
    voiced = env > 0.04 * env.max()
    chunks, f = [], 0
    while f < len(env):  # voiced runs, bridging quiet gaps shorter than 80 ms
        if not voiced[f]:
            f += 1
            continue
        s, q = f, 0
        while f < len(env) and (voiced[f] or q < 8):
            q = 0 if voiced[f] else q + 1
            f += 1
        chunks.append((s, f - q))
    toks = text.split()
    nt = len(toks)
    base = np.array([0.5 + syllables(t) + 0.6 * len(re.sub(r"[^A-Za-z0-9']", "", t)) for t in toks])
    pause = np.array([4.0 if t[-1] in ",;:" else 3.0 if t[-1] in ".!?" and i < nt - 1 else 0.0 for i, t in enumerate(toks)])
    cum = np.concatenate([[0], np.cumsum(base + pause)])
    pred = chunks[0][0] + (chunks[-1][1] - chunks[0][0]) * cum / cum[-1]  # predicted time of each token boundary
    cuts, last = [], 0
    for k in range(len(chunks) - 1):  # the pause between chunk k and k+1 -> the nearest unused boundary, punctuation preferred
        tg = (chunks[k][1] + chunks[k + 1][0]) / 2
        free = [j for j in range(last + 1, nt) if j <= nt - 1 - (len(chunks) - 2 - k)]
        if not free:
            break
        last = min(free, key=lambda j: abs(pred[j] - tg) - (15 if toks[j - 1][-1] in ",;:.!?" else 0))
        cuts.append(last)
    bounds = [0] + cuts + [nt]
    times = []
    for k in range(len(bounds) - 1):
        lo, hi = bounds[k], bounds[k + 1]
        cs, ce = chunks[min(k, len(chunks) - 1)]
        c = np.concatenate([[0], np.cumsum(base[lo:hi])])
        e = (cs + (ce - cs) * c / c[-1]) / 100
        times += [(e[i], e[i + 1]) for i in range(hi - lo)]
    names = [re.sub(r"[^A-Za-z0-9']", "", t) for t in toks]
    return [(float(a), float(b), n) for (a, b), n in zip(times, names) if n]  # plain floats: numpy ones break PIL's blur radius later


def segment(seg, sr, ff):
    """-> (int16 pcm at sr with the leading silence kept, [(start, end, word)] relative to the clip)"""
    ex, cfg, tempo, gain = CB_TONES[seg["tone"]]
    af = ([f"atempo={tempo}"] if tempo != 1.0 else [])
    raw = subprocess.run([ff, "-v", "error", "-i", str(path_for(seg)), *(["-af", ",".join(af)] if af else []), "-f", "s16le", "-ac", "1", "-ar", str(sr), "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.int16).astype(float)
    on = np.abs(x) > 0.05 * np.abs(x).max()
    x *= LOUD * 32767 * 10 ** (gain / 20) / max(np.sqrt(np.mean(x[on] ** 2)), 1)
    x = np.clip(x, -32000, 32000).astype(np.int16)
    return x, estimate_words(x, seg["text"], sr)


if __name__ == "__main__":  # self-check of the word-time estimator against the Edge voice, whose true word times are known
    sys.path.insert(0, str(Path(__file__).parent))
    import asyncio
    import render
    errs = []
    for line in ["Today is Wednesday, and I really love it.", "It lets you dump all your inner struggles, all your internal battles, straight onto the tester.",
                 "Three days of bugs, deadlines, and meetings that should have been emails, finally leave my body.", "Comment your worst tester battle, and I will read every single one."]:
        mp3, ws = asyncio.run(render.speak(line, "en-US-AndrewNeural", "+8%", "+0Hz"))
        pcm = np.frombuffer(subprocess.run([render.ffmpeg(), "-v", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", "24000", "-"], input=mp3, capture_output=True, check=True).stdout, np.int16)
        est = estimate_words(pcm, line, 24000)
        errs += [e[0] - t[0] for e, t in zip(est, ws)]
    errs = np.abs(np.array(errs) - np.median(errs))  # Edge's own word times sit a constant ~40-80 ms off the audible onsets
    print(f"mean {errs.mean() * 1000:.0f} ms, p90 {np.percentile(errs, 90) * 1000:.0f} ms (a 30 fps frame is 33 ms)")
