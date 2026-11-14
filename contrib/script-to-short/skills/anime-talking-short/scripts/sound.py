"""Sound design for render.py: synthesized SFX, voice-ducked music with drops, one mixed track.
Everything is 48 kHz stereo float; no sample libraries needed."""
import subprocess

import numpy as np

SR = 48000
RNG = np.random.default_rng(3)
# husky, chesty narrator: low shelf + warmth + presence, firm compression, soft saturation
VOICE_CHAIN = ("bass=g=6:f=110:w=0.6,equalizer=f=250:t=q:w=1.2:g=2,equalizer=f=3200:t=q:w=1:g=3,"
               "acompressor=threshold=-22dB:ratio=4:attack=5:release=80:makeup=5,asoftclip=type=tanh,volume=-1dB")


def decode(ff, src, af=None, data=None):
    cmd = [ff, "-v", "error", "-i", "pipe:0" if data is not None else src] + (["-af", af] if af else []) + \
          ["-f", "f32le", "-ac", "2", "-ar", str(SR), "-"]
    raw = subprocess.run(cmd, input=data, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).copy()


def env(n, attack, release):
    t = np.arange(n) / SR
    return np.minimum(1, t / max(attack, 1e-4)) * np.exp(-np.maximum(0, t - attack) / release)


def band_noise(dur, f0, f1, width=0.5):
    """Noise whose pass band slides f0 -> f1 (log), by overlap-added FFT blocks."""
    n, blk = int(dur * SR), 1024
    out, win = np.zeros(n + blk), np.hanning(blk)
    freqs = np.fft.rfftfreq(blk, 1 / SR)
    for i, s in enumerate(range(0, n, blk // 2)):
        fc = f0 * (f1 / f0) ** min(1, s / max(n, 1))
        mask = np.exp(-0.5 * (np.log2(np.maximum(freqs, 1) / fc) / width) ** 2)
        out[s:s + blk] += np.fft.irfft(np.fft.rfft(RNG.standard_normal(blk) * win) * mask) * win
    out = out[:n]
    return out / (np.abs(out).max() + 1e-9)


def stereo(x, pan=0.0):
    """pan -1..1, or an array for a moving pan"""
    p = (np.asarray(pan) + 1) * np.pi / 4
    return np.stack([x * np.cos(p), x * np.sin(p)], 1)


def sweep(dur, f0, f1):
    f = f0 * (f1 / f0) ** (np.arange(int(dur * SR)) / (dur * SR))
    return np.sin(2 * np.pi * np.cumsum(f) / SR)


def whoosh(d=0.5):
    x = band_noise(d, 400, 4000, 0.6) * np.sin(np.linspace(0, np.pi, int(d * SR))) ** 2
    return stereo(x * 0.9, np.linspace(-0.8, 0.8, len(x)))


def boom(d=1.4):
    n = int(d * SR)
    sub = np.tanh(2.2 * sweep(d, 95, 32) * env(n, 0.005, 0.45))
    click = band_noise(0.03, 3000, 1500) * env(int(0.03 * SR), 0.0005, 0.008)
    sub[: len(click)] += 0.5 * click
    return stereo(sub * 0.95)


def riser(d=1.2):
    n = int(d * SR)
    ramp = np.linspace(0, 1, n) ** 2.2
    x = (0.6 * band_noise(d, 300, 6000, 0.7) + 0.4 * sweep(d, 180, 1400)) * ramp
    return stereo(x * 0.6)


def hit(d=1.0):
    n = int(d * SR)
    tail = band_noise(d, 900, 300, 1.0) * env(n, 0.002, 0.25)
    return stereo(0.7 * tail) + boom(d)[:n] * 0.6


def pop(d=0.07):
    return stereo(sweep(d, 1300, 500) * env(int(d * SR), 0.001, 0.02) * 0.7)


def tick(d=0.012):
    return stereo(band_noise(d, 6000, 6000) * env(int(d * SR), 0.0002, 0.003) * 0.5)


def scratch(d=0.4):
    n = int(d * SR)
    wob = np.sin(np.linspace(0, 4 * np.pi, n))  # two back-and-forth hand moves
    x = band_noise(d, 900, 900, 0.5) * np.abs(wob) * (0.5 + 0.5 * np.sign(wob) * sweep(d, 300, 300))
    return stereo(x * env(n, 0.003, 0.3) * 0.8)


def glitch(d=0.22):
    n, out = int(d * SR), np.zeros(int(d * SR))
    for s in range(0, n, int(0.02 * SR)):  # 20 ms stutter slices of square tone + noise
        e = min(n, s + int(0.016 * SR))
        f = RNG.choice([180, 360, 720, 1440])
        out[s:e] = 0.5 * np.sign(np.sin(2 * np.pi * f * np.arange(e - s) / SR)) + 0.3 * RNG.standard_normal(e - s)
    return stereo(np.round(out * 6) / 6 * 0.45)  # bit-crushed


def beep(d=0.32):
    x = np.zeros(int(d * SR))
    for s in (0, int(0.16 * SR)):
        x[s:s + int(0.08 * SR)] = np.sin(2 * np.pi * 2000 * np.arange(int(0.08 * SR)) / SR) * 0.35
    return stereo(x)


SFX = {"whoosh": whoosh, "boom": boom, "riser": riser, "hit": hit, "pop": pop, "tick": tick,
       "scratch": scratch, "glitch": glitch, "beep": beep}
ENDS_AT_MARK = {"riser"}  # build-ups finish on the beat instead of starting on it


def mix(ff, voice_wav, music, events, drops, out_wav, seconds):
    """voice_wav: dry voice; events: [(t, sfx name)]; drops: [(start, end)] music muted, slams back at end."""
    n = int(seconds * SR)
    v = decode(ff, voice_wav, VOICE_CHAIN)[:n]
    v = np.pad(v, ((0, n - len(v)), (0, 0)))
    bus = v.copy()

    if music:
        m = decode(ff, music)
        m = np.tile(m, (n // len(m) + 1, 1))[:n]
        # sidechain duck: music sits up in the gaps, dips under speech (10 ms frames, fast attack, slow release)
        fr = SR // 100
        lvl = np.sqrt((np.pad(v[:, 0], (0, -n % fr)).reshape(-1, fr) ** 2).mean(1))
        speaking = np.clip(lvl / (np.percentile(lvl, 90) + 1e-9) * 3, 0, 1)
        g, out = 0.0, np.empty_like(speaking)
        for i, s in enumerate(speaking):
            g += (s - g) * (0.5 if s > g else 0.04)
            out[i] = g
        gain = np.repeat(0.34 - 0.24 * out, fr)[:n]
        for a, b in drops:  # 60 ms fade out, hard back in
            i, j = int(a * SR), int(b * SR)
            fade = min(int(0.06 * SR), max(j - i, 1))
            gain[i:i + fade] *= np.linspace(1, 0, fade)
            gain[i + fade:j] = 0
            events = events + [(b, "boom")]
        bus += m * gain[:, None]

    for t, name in events:
        x = SFX[name]()
        s = int((t - (len(x) / SR if name in ENDS_AT_MARK else 0)) * SR)
        a, b = max(s, 0), min(s + len(x), n)
        if b > a:
            bus[a:b] += x[a - s:b - s] * 0.55

    bus = np.tanh(bus * 1.1) / np.tanh(1.1)  # glue + safety limiter
    pcm = (np.clip(bus, -1, 1) * 32767).astype("<i2")
    import wave
    with wave.open(out_wav, "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(pcm.tobytes())


def selftest():
    for name, fn in SFX.items():
        x = fn()
        assert x.ndim == 2 and x.shape[1] == 2 and np.isfinite(x).all() and np.abs(x).max() <= 1.5, name
    print("sound selftest ok")


if __name__ == "__main__":
    selftest()
