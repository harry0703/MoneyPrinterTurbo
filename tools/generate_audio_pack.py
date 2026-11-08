"""Generate an original, royalty-free audio pack (beds + hooks) for
Chamanismo y Holistica and Silhouette Punto Total.

Everything is synthesized from scratch with numpy/scipy (no samples),
so the output carries no third-party rights.

Usage: python3 make_pack.py OUT_DIR
"""
import os
import subprocess
import sys

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, sosfilt, sosfiltfilt

SR = 44100
OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)


# ---------------------------------------------------------------- helpers
def t_axis(dur):
    return np.arange(int(dur * SR)) / SR


def lowpass(x, fc, order=4):
    return sosfilt(butter(order, fc, "low", fs=SR, output="sos"), x)


def highpass(x, fc, order=4):
    return sosfilt(butter(order, fc, "high", fs=SR, output="sos"), x)


def bandpass(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], "band", fs=SR, output="sos"), x)


def fade(x, fin=0.01, fout=0.05):
    n = len(x)
    a, b = int(fin * SR), int(fout * SR)
    env = np.ones(n)
    if a:
        env[:a] = np.linspace(0, 1, a)
    if b:
        env[-b:] = np.minimum(env[-b:], np.linspace(1, 0, b))
    return x * env if x.ndim == 1 else x * env[:, None]


def pan(mono, p):
    """p in [-1, 1] -> stereo with equal-power law."""
    ang = (p + 1) * np.pi / 4
    return np.stack([mono * np.cos(ang), mono * np.sin(ang)], axis=1)


def place(bus, clip, start):
    i = int(start * SR)
    if i >= len(bus):
        return
    j = min(len(bus), i + len(clip))
    bus[i:j] += clip[: j - i]


def reverb_ir(rng, seconds=3.5, decay=2.2, bright=6000):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    env = np.exp(-t * (6.9 / decay))
    left = lowpass(rng.standard_normal(n), bright) * env
    right = lowpass(rng.standard_normal(n), bright) * env
    ir = np.stack([left, right], axis=1)
    return ir / np.sqrt((ir ** 2).sum(axis=0, keepdims=True))


def add_reverb(x, ir, wet=0.3):
    out = np.zeros((len(x) + len(ir) - 1, 2))
    for ch in range(2):
        out[:, ch] = fftconvolve(x[:, ch], ir[:, ch])
    out = out[: len(x)]
    return (1 - wet) * x + wet * out


def norm(x, peak=0.89):
    m = np.max(np.abs(x))
    return x if m == 0 else x * (peak / m)


def pink(rng, n):
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    f = np.fft.rfftfreq(n, 1 / SR)
    f[0] = 1
    spec /= np.sqrt(f)
    out = np.fft.irfft(spec, n)
    return out / np.max(np.abs(out))


def lfo(t, rate, depth, phase=0.0):
    return 1 + depth * np.sin(2 * np.pi * rate * t + phase)


# ---------------------------------------------------------- instruments
def bowl(f0, dur, rng, decay=7.0):
    """Singing bowl: inharmonic partials, each a slowly beating pair."""
    t = t_axis(dur)
    ratios = [1.0, 2.76, 5.40, 8.93]
    amps = [1.0, 0.55, 0.28, 0.12]
    out = np.zeros_like(t)
    for k, (r, a) in enumerate(zip(ratios, amps)):
        f = f0 * r
        beat = 0.6 + 0.8 * rng.random()
        tau = decay / (1 + 0.7 * k)
        env = np.exp(-t / tau)
        out += a * env * (np.sin(2 * np.pi * f * t) + np.sin(2 * np.pi * (f + beat) * t)) / 2
    strike = lowpass(rng.standard_normal(len(t)), 3000) * np.exp(-t / 0.01) * 0.15
    return fade(out + strike, 0.004, 0.3)


def gong(dur, rng):
    t = t_axis(dur)
    out = np.zeros_like(t)
    swell = np.clip(t / 1.2, 0, 1) ** 2 * np.exp(-t / 5.0)
    for k in range(18):
        f = 55 * (1 + k * 0.73 + 0.11 * rng.random() * k)
        out += np.sin(2 * np.pi * f * t + rng.random() * 6.28) / (1 + 0.35 * k)
    noise = lowpass(rng.standard_normal(len(t)), 1800) * 0.2
    return fade((out + noise) * swell, 0.01, 0.6)


def frame_drum(rng, f_hi=95, f_lo=52, dur=0.9, tone=1.0):
    t = t_axis(dur)
    f = f_lo + (f_hi - f_lo) * np.exp(-t / 0.06)
    phase = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(phase) * np.exp(-t / 0.28) * tone
    skin = lowpass(rng.standard_normal(len(t)), 900) * np.exp(-t / 0.035) * 0.35
    return fade(body + skin, 0.001, 0.1)


def kick(dur=0.45):
    t = t_axis(dur)
    f = 45 + 85 * np.exp(-t / 0.035)
    phase = 2 * np.pi * np.cumsum(f) / SR
    return fade(np.sin(phase) * np.exp(-t / 0.16), 0.001, 0.05)


def hat(rng, dur=0.06, level=0.25):
    t = t_axis(dur)
    return highpass(rng.standard_normal(len(t)), 7000) * np.exp(-t / 0.015) * level


def rim(rng, dur=0.12):
    t = t_axis(dur)
    tone = np.sin(2 * np.pi * 820 * t) * np.exp(-t / 0.02)
    noise = bandpass(rng.standard_normal(len(t)), 1500, 5000) * np.exp(-t / 0.03)
    return (0.5 * tone + 0.6 * noise) * 0.5


def shaker(rng, dur=0.18):
    t = t_axis(dur)
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 2
    return highpass(rng.standard_normal(len(t)), 4000) * env * 0.18


def ep_note(f, dur):
    """Soft electric-piano-ish tone."""
    t = t_axis(dur)
    out = (np.sin(2 * np.pi * f * t)
           + 0.35 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t / 0.4)
           + 0.12 * np.sin(2 * np.pi * 3 * f * t) * np.exp(-t / 0.2))
    env = np.exp(-t / 1.6) * lfo(t, 4.5, 0.08)
    return fade(out * env, 0.006, 0.25)


def pluck(f, dur, rng):
    """Karplus-Strong pluck."""
    n = int(dur * SR)
    period = max(2, int(SR / f))
    buf = rng.uniform(-1, 1, period)
    out = np.zeros(n)
    for i in range(n):
        out[i] = buf[i % period]
        buf[i % period] = 0.996 * 0.5 * (buf[i % period] + buf[(i + 1) % period])
    return fade(lowpass(out, 5000), 0.002, 0.2)


def pad(freqs, dur, rng, bright=1400, detune=0.25):
    t = t_axis(dur)
    out = np.zeros_like(t)
    for f in freqs:
        for d in (-detune, 0, detune):
            ff = f + d
            ph = rng.random() * 6.28
            out += (np.sin(2 * np.pi * ff * t + ph)
                    + 0.3 * np.sin(2 * np.pi * 2 * ff * t + ph)
                    + 0.12 * np.sin(2 * np.pi * 3 * ff * t + ph))
    out = lowpass(out, bright)
    return out / (len(freqs) * 3)


def note(name):
    names = {"C": -9, "C#": -8, "D": -7, "D#": -6, "E": -5, "F": -4,
             "F#": -3, "G": -2, "G#": -1, "A": 0, "A#": 1, "B": 2}
    pitch, octave = name[:-1], int(name[-1])
    return 440.0 * 2 ** ((names[pitch] + 12 * (octave - 4)) / 12)


def chord(names):
    return [note(n) for n in names]


def write(name, x, loud=-18.0, bitrate="128k"):
    x = norm(x)
    wav = os.path.join(OUT, name + ".wav")
    mp3 = os.path.join(OUT, name + ".mp3")
    wavfile.write(wav, SR, x.astype(np.float32))
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", wav,
         "-af", f"loudnorm=I={loud}:TP=-1.5:LRA=11",
         "-ar", str(SR), "-c:a", "libmp3lame", "-b:a", bitrate, mp3],
        check=True)
    os.remove(wav)
    print("wrote", mp3)


# ------------------------------------------------------------------ beds
BED = 180.0  # seconds; both generators loop or cut as needed


def bed_cuencos(seed=1):
    rng = np.random.default_rng(seed)
    t = t_axis(BED)
    bus = np.zeros((len(t), 2))
    drone = pad(chord(["D2", "A2", "D3"]), BED, rng, bright=600) * lfo(t, 0.05, 0.25)
    bus += pan(drone * 0.55, 0)
    scale = chord(["D3", "F3", "G3", "A3", "C4", "D4"])
    at = 2.0
    while at < BED - 4:
        f = scale[rng.integers(len(scale))]
        place(bus, pan(bowl(f, 14, rng) * 0.6, rng.uniform(-0.6, 0.6)), at)
        at += rng.uniform(8, 14)
    bus = add_reverb(bus, reverb_ir(rng, 5, 4.0, 4000), 0.4)
    return fade(bus, 4, 6)


def bed_tambor(seed=2):
    rng = np.random.default_rng(seed)
    t = t_axis(BED)
    bus = np.zeros((len(t), 2))
    drone = pad(chord(["A1", "E2", "A2"]), BED, rng, bright=500) * lfo(t, 0.04, 0.3)
    bus += pan(drone * 0.5, 0)
    beat = 60 / 66  # heartbeat-like pulse
    at, n = 3.0, 0
    while at < BED - 2:
        place(bus, pan(frame_drum(rng) * 0.9, -0.1), at)
        place(bus, pan(frame_drum(rng, 88, 58, tone=0.55) * 0.6, 0.1), at + 0.32)
        if n % 4 == 3:
            place(bus, pan(shaker(rng) * 1.2, 0.5), at + 0.6)
        at += beat * 2
        n += 1
    bus = add_reverb(bus, reverb_ir(rng, 3, 2.5, 3000), 0.3)
    return fade(bus, 5, 6)


def bed_binaural(seed=3):
    """Theta-range (6 Hz) binaural beat under a warm pad and soft wind."""
    rng = np.random.default_rng(seed)
    t = t_axis(BED)
    left = np.sin(2 * np.pi * 196 * t)
    right = np.sin(2 * np.pi * 202 * t)
    bus = np.stack([left, right], axis=1) * 0.18
    p = pad(chord(["G2", "D3", "G3", "B3"]), BED, rng, bright=900) * lfo(t, 0.03, 0.2)
    bus += pan(p * 0.6, 0)
    wind = bandpass(pink(rng, len(t)), 200, 1200) * lfo(t, 0.07, 0.6) * 0.12
    bus += np.stack([wind, np.roll(wind, SR // 3)], axis=1)
    bus = add_reverb(bus, reverb_ir(rng, 4, 3.0, 3000), 0.25)
    return fade(bus, 6, 6)


def bed_viento(seed=4):
    rng = np.random.default_rng(seed)
    t = t_axis(BED)
    wl = bandpass(pink(rng, len(t)), 150, 1600) * lfo(t, 0.06, 0.7)
    wr = bandpass(pink(rng, len(t)), 150, 1600) * lfo(t, 0.05, 0.7, 1.7)
    bus = np.stack([wl, wr], axis=1) * 0.35
    scale = chord(["E5", "G5", "A5", "B5", "D6", "E6"])
    at = 1.5
    while at < BED - 3:
        for _ in range(rng.integers(1, 4)):
            f = scale[rng.integers(len(scale))]
            ch = bowl(f, 4, rng, decay=1.4) * 0.25
            place(bus, pan(ch, rng.uniform(-0.9, 0.9)), at + rng.uniform(0, 0.6))
        at += rng.uniform(3, 7)
    bus = add_reverb(bus, reverb_ir(rng, 4, 3.2, 7000), 0.35)
    return fade(bus, 5, 6)


def bed_spa(seed=5):
    rng = np.random.default_rng(seed)
    t = t_axis(BED)
    bus = np.zeros((len(t), 2))
    prog = [["C3", "E3", "G3", "B3"], ["A2", "E3", "G3", "C4"],
            ["F2", "A2", "C3", "E3"], ["G2", "B2", "D3", "A3"]]
    seg = 8.0
    for i in range(int(BED / seg) + 1):
        c = prog[i % len(prog)]
        clip = fade(pad(chord(c), seg + 2, rng, bright=1200), 2, 2)
        place(bus, pan(clip * 0.7, 0), i * seg)
    mel = chord(["E5", "G5", "A5", "C6", "D6"])
    at = 4.0
    while at < BED - 3:
        place(bus, pan(ep_note(mel[rng.integers(len(mel))], 3) * 0.18, rng.uniform(-0.5, 0.5)), at)
        at += rng.uniform(2.5, 5.5)
    water = bandpass(pink(rng, len(t)), 800, 4000) * lfo(t, 0.2, 0.4) * 0.05
    bus += np.stack([water, np.roll(water, SR // 5)], axis=1)
    bus = add_reverb(bus, reverb_ir(rng, 4, 3.0, 5000), 0.35)
    return fade(bus, 4, 6)


def bed_lofi(seed=6):
    rng = np.random.default_rng(seed)
    t = t_axis(BED)
    bus = np.zeros((len(t), 2))
    bpm = 80
    beat = 60 / bpm
    swing = 0.06
    prog = [["F3", "A3", "C4", "E4"], ["E3", "G3", "B3", "D4"],
            ["D3", "F3", "A3", "C4"], ["C3", "E3", "G3", "B3"]]
    bars = int(BED / (4 * beat))
    for b in range(bars):
        t0 = 1.0 + b * 4 * beat
        c = chord(prog[b % 4])
        for f in c:
            place(bus, pan(ep_note(f, 4 * beat) * 0.22, rng.uniform(-0.3, 0.3)), t0 + rng.uniform(0, 0.03))
        place(bus, pan(ep_note(c[0] / 2, 4 * beat) * 0.35, 0), t0)
        if b >= 2:
            for s in (0, 2.5):
                place(bus, pan(kick() * 0.8, 0), t0 + s * beat)
            for s in (1, 3):
                place(bus, pan(rim(rng) * 0.9, 0.1), t0 + s * beat)
            for e in range(8):
                off = swing if e % 2 else 0
                place(bus, pan(hat(rng, level=0.2 if e % 2 else 0.3), 0.3), t0 + (e * 0.5 + off) * beat)
    crackle = np.zeros(len(t))
    idx = rng.integers(0, len(t), int(BED * 12))
    crackle[idx] = rng.uniform(-1, 1, len(idx))
    crackle = highpass(crackle, 2000) * 0.25
    bus += np.stack([crackle, np.roll(crackle, 97)], axis=1)
    bus[:, 0] = lowpass(bus[:, 0], 7000)
    bus[:, 1] = lowpass(bus[:, 1], 7000)
    bus = add_reverb(bus, reverb_ir(rng, 2, 1.4, 4000), 0.18)
    return fade(bus, 2, 6)


def bed_pulso(seed=7):
    rng = np.random.default_rng(seed)
    t = t_axis(BED)
    bus = np.zeros((len(t), 2))
    bpm = 104
    beat = 60 / bpm
    prog = [["A3", "C4", "E4"], ["F3", "A3", "C4"], ["C4", "E4", "G4"], ["G3", "B3", "D4"]]
    bars = int(BED / (4 * beat))
    for b in range(bars):
        t0 = 0.5 + b * 4 * beat
        c = chord(prog[b % 4])
        arp = c + [c[1] * 2]
        for s in range(8):
            f = arp[s % len(arp)] * 2
            place(bus, pan(pluck(f, 0.5, rng) * 0.3, -0.4 if s % 2 else 0.4), t0 + s * 0.5 * beat)
        place(bus, pan(ep_note(c[0] / 2, 4 * beat) * 0.4, 0), t0)
        if b >= 4:
            for s in range(4):
                place(bus, pan(kick() * 0.65, 0), t0 + s * beat)
                place(bus, pan(hat(rng, level=0.22), 0.2), t0 + (s + 0.5) * beat)
            for s in (1, 3):
                place(bus, pan(rim(rng) * 0.6, -0.1), t0 + s * beat)
    bus = add_reverb(bus, reverb_ir(rng, 2.5, 1.8, 6000), 0.22)
    return fade(bus, 2, 6)


# ----------------------------------------------------------------- hooks
def hook_cuenco(seed=11):
    rng = np.random.default_rng(seed)
    x = pan(bowl(note("D4"), 4.5, rng, decay=3.5), 0)
    return fade(add_reverb(x, reverb_ir(rng, 3, 2.5, 5000), 0.35), 0.002, 0.8)


def hook_gong(seed=12):
    rng = np.random.default_rng(seed)
    x = pan(gong(5.0, rng), 0)
    return fade(add_reverb(x, reverb_ir(rng, 3, 3.0, 4000), 0.3), 0.01, 1.0)


def hook_riser(seed=13):
    rng = np.random.default_rng(seed)
    dur = 2.5
    t = t_axis(dur)
    n = pink(rng, len(t))
    out = np.zeros_like(t)
    steps = 50
    for k in range(steps):
        a, b = k * len(t) // steps, (k + 1) * len(t) // steps
        fc = 300 * (40 ** (k / steps))
        seg = bandpass(n, fc * 0.7, min(fc * 1.4, 18000))
        out[a:b] = seg[a:b]
    f = 200 * (8 ** (t / dur))
    sweep = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.15
    env = (t / dur) ** 2
    x = (out * 0.8 + sweep) * env
    st = np.stack([x, np.roll(x, 220)], axis=1)
    return fade(add_reverb(st, reverb_ir(rng, 1.5, 1.0, 9000), 0.2), 0.01, 0.05)


def hook_brillo(seed=14):
    rng = np.random.default_rng(seed)
    bus = np.zeros((int(2.8 * SR), 2))
    notes = chord(["E6", "G6", "B6", "D7", "E7"])
    for i, f in enumerate(notes):
        place(bus, pan(bowl(f, 2.0, rng, decay=0.7) * 0.4, -0.8 + 0.4 * i), i * 0.07)
    return fade(add_reverb(bus, reverb_ir(rng, 2, 1.8, 10000), 0.35), 0.002, 0.5)


def hook_tambor(seed=15):
    rng = np.random.default_rng(seed)
    bus = np.zeros((int(2.2 * SR), 2))
    place(bus, pan(frame_drum(rng, 100, 50, 1.2), 0), 0.02)
    place(bus, pan(frame_drum(rng, 100, 50, 1.2) * 0.85, 0), 0.42)
    return fade(add_reverb(bus, reverb_ir(rng, 2.5, 2.0, 3000), 0.3), 0.002, 0.4)


def hook_pop(seed=16):
    rng = np.random.default_rng(seed)
    dur = 0.5
    t = t_axis(dur)
    f = 500 + 900 * (1 - np.exp(-t / 0.03))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.07)
    bus = pan(x, 0)
    return fade(add_reverb(bus, reverb_ir(rng, 0.8, 0.5, 9000), 0.15), 0.002, 0.08)


def hook_reverso(seed=17):
    rng = np.random.default_rng(seed)
    b = bowl(note("A3"), 3.0, rng, decay=2.2)[::-1]
    hit = bowl(note("A3"), 3.0, rng, decay=2.2)
    x = np.concatenate([b, hit])
    st = pan(x, 0)
    return fade(add_reverb(st, reverb_ir(rng, 3, 2.5, 5000), 0.3), 0.3, 0.8)


if __name__ == "__main__":
    beds = {
        "chamanismo_cuencos_profundos": bed_cuencos,
        "chamanismo_tambor_ritual": bed_tambor,
        "chamanismo_binaural_calma_theta": bed_binaural,
        "chamanismo_viento_y_campanas": bed_viento,
        "silhouette_spa_ambiente": bed_spa,
        "silhouette_lofi_suave_80bpm": bed_lofi,
        "silhouette_pulso_ligero_104bpm": bed_pulso,
    }
    hooks = {
        "gancho_cuenco_golpe": hook_cuenco,
        "gancho_gong_swell": hook_gong,
        "gancho_riser_whoosh": hook_riser,
        "gancho_brillo_campanitas": hook_brillo,
        "gancho_tambor_doble": hook_tambor,
        "gancho_pop_suave": hook_pop,
        "gancho_cuenco_reverso": hook_reverso,
    }
    only = set(sys.argv[2:])
    for name, fn in {**hooks, **beds}.items():
        if only and name not in only:
            continue
        loud = -16.0 if name.startswith("gancho") else -18.0
        write(name, fn(), loud=loud, bitrate="160k" if name.startswith("gancho") else "128k")
