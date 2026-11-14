"""Render a 9:16 short from a screenplay: a 2D character performs the script with lip-sync from the audio
(Rhubarb), gesture poses, a camera (shot sizes, push-ins, dutch angles, aspect ratios), transitions,
live word captions and a designed sound mix (sound.py).
Run with the repo's .venv python (install.py sets it up: edge-tts, Pillow, numpy, imageio-ffmpeg).

Screenplay markup. Tags other than pause/tone split the speech, so put them at sentence boundaries.
  [pause 1.0]                     silence in seconds ([pause] = 0.8)
  {AJ=A J}                        caption shows "AJ", the voice says "A J"
  [normal] [hype] [sarcastic]     delivery from here on
  [shot frame=wide|med|cu|ecu move=<frame> pose=<name> bg=<name> aspect=9:16|4:5|1:1|4:3|2.39
        tilt=<deg> in=cut|whip|zoom|glitch|fade look=clean|cam]
                                  new shot at the next sentence; frame/pose/bg/aspect/look carry over,
                                  move/tilt/in belong to that shot only
  [sfx whoosh boom ...]           sound(s) at the next sentence (a riser ends there); names in sound.SFX
  [drop]                          music cuts out in the gap before the next sentence, slams back with a boom
  *word*                          emphasis: giant tilted caption, camera punch-in until the sentence ends
  shot extras: side=left|right (face on a third), lens=tele (isolate: bigger, softer set), focus=pull (rack focus in)"""
import argparse
import asyncio
import bisect
import json
import math
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
import sound  # noqa: E402

W, H, FPS, SR = 1080, 1920, 30, 24000  # SR divisible by FPS -> exact audio hop per frame
CW, CH = 1440, 2560                    # stage canvas; poses and backgrounds are prepared at this size
CAPTION_Y = 1450
ACCENT = (255, 214, 0)
FONTS = ("C:/Windows/Fonts/ariblk.ttf", "/System/Library/Fonts/Supplemental/Arial Black.ttf", "/usr/share/fonts/truetype/msttcorefonts/Arial_Black.ttf",
         "C:/Windows/Fonts/impact.ttf", "C:/Windows/Fonts/arialbd.ttf", "DejaVuSans-Bold.ttf")
TONES = {"normal": ("+8%", "+0Hz"), "hype": ("+16%", "+14Hz"), "sarcastic": ("-8%", "-12Hz")}
FACE_SHARE = {"wide": 0, "med": 0.3, "cu": 0.55, "ecu": 0.85}  # face width as a share of the frame width
FACE_DROP = {"wide": 0, "med": 0.9, "cu": 0.2, "ecu": 0.05}    # frame centre below the face centre, in face widths
ASPECTS = {"9:16": 9 / 16, "4:5": 4 / 5, "1:1": 1.0, "4:3": 4 / 3, "2.39": 2.39}
TRANSITIONS = {"cut", "whip", "zoom", "glitch", "fade"}
PER_SHOT = {"move": None, "tilt": 0.0, "in": "cut", "side": "center", "lens": "normal", "focus": "none"}
REPO = Path(__file__).resolve().parents[3]
# install.py unpacks Rhubarb into <repo>/tools/rhubarb; a system-wide install on PATH also works
RHUBARB = Path(next((str(p) for p in REPO.glob("tools/rhubarb/*/rhubarb*") if p.stem == "rhubarb"), None) or shutil.which("rhubarb") or "rhubarb-missing")
RB_MAP = {"A": "X", "B": "B", "C": "C", "D": "D", "E": "E", "F": "F", "G": "B", "H": "C", "X": "X"}
SAY = re.compile(r"\{([^=}]+)=([^}]+)\}")
EMPH = re.compile(r"\*([^*]+)\*")
def norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())
TAG = re.compile(r"\[([a-z]+(?:\s[^\]]*)?)\]")
# Fallback mouth shapes from spelling, used only when Rhubarb is missing. First matching rule wins at each letter.
RULES = [(re.compile(p), s) for p, s in [
    (r"[mbp]+", "X"), (r"igh|I|ar", "D"), (r"al(?=[lk])|au|aw|or|oi|oy|[eiu]r|r", "E"),
    (r"oo|ou|ow|ew|ue|oa|o$|O|U|wh?|qu", "F"), (r"ee|ea|i|y", "B"), (r"ai|ay|[aeouA]|l+", "C"),
    (r"h", ""), (r".", "B")]]
WEIGHT = {"X": 0.8, "B": 1.0}


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def parse(text):
    """-> segments [{text, tone, pause, marks}], says [(spoken tokens, caption)]"""
    says = [(m[2].split(), m[1]) for m in SAY.finditer(text)]
    parts = TAG.split(SAY.sub(lambda m: m[2], text))  # text, tag, text, tag, ...
    segs, tone, marks = [], "normal", []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            if part.strip():
                emph = [norm(w) for m in EMPH.finditer(part) for w in m[1].split()]
                segs.append({"text": EMPH.sub(r"\1", part.strip()), "emph": emph, "tone": tone, "pause": 0.0, "marks": marks})
                marks = []
            continue
        name, *args = part.split()
        if name == "pause":
            if segs:
                segs[-1]["pause"] += float(args[0]) if args else 0.8
        elif name in TONES:
            tone = name
        elif name in ("shot", "sfx", "drop"):
            marks.append((name, args))
        else:
            sys.exit(f"unknown script tag [{part}]")
    return segs, says


async def speak(text, voice, rate, pitch):
    import edge_tts
    for attempt in range(8):  # the free endpoint randomly returns no audio; a retry usually works
        audio, words = bytearray(), []
        try:
            async for c in edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary").stream():
                if c["type"] == "audio":
                    audio += c["data"]
                elif c["type"] == "WordBoundary":
                    words.append((c["offset"] / 1e7, (c["offset"] + c["duration"]) / 1e7, c["text"]))
        except edge_tts.exceptions.NoAudioReceived:
            words = []
        if words:
            return bytes(audio), words
        print(f"edge-tts gave no audio (try {attempt + 1}/8), retrying", flush=True)
        await asyncio.sleep(3 * (attempt + 1))
    sys.exit("edge-tts returned no audio after 8 tries; the Microsoft voice service is down or blocking, try again later")


def voice_track(segs, says, voice, wav):
    """Speak each segment in its tone, join with exact silences. Sets seg t/end. -> seconds, [(start, end, word)]"""
    pcm, words, t, emph_t = [], [], 0.0, set()
    for seg in segs:
        mp3, ws = asyncio.run(speak(seg["text"], voice, *TONES[seg["tone"]]))
        raw = subprocess.run([ffmpeg(), "-v", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                             input=mp3, capture_output=True, check=True).stdout
        lead = max(0.0, ws[0][0] - 0.04)  # trim the service's silence at both ends: tight pacing, exact pauses
        x = np.frombuffer(raw, np.int16)[int(lead * SR): int((ws[-1][1] + 0.12) * SR)]
        off = t - lead  # where the trimmed clip's time zero lands in the track
        seg["t"], seg["end"] = ws[0][0] + off, ws[-1][1] + off
        words += [(s + off, e + off, w) for s, e, w in ws]
        todo = list(seg["emph"])
        for s_, e_, w_ in ws:
            if norm(w_) in todo:
                todo.remove(norm(w_))
                emph_t.add(s_ + off)
        pcm += [x, np.zeros(int(seg["pause"] * SR), np.int16)]
        t += len(x) / SR + seg["pause"]
    for spoken, caption in says:  # spelled-out tokens back into one caption word
        k, i = len(spoken), 0
        while i + k <= len(words):
            if [w[2].lower() for w in words[i:i + k]] == [s.lower() for s in spoken]:
                words[i:i + k] = [(words[i][0], words[i + k - 1][1], caption)]
            i += 1
    audio = np.concatenate(pcm + [np.zeros(SR // 2, np.int16)])  # tail so the video doesn't end on the last syllable
    with wave.open(wav, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(audio.tobytes())
    return len(audio) / SR, words, {i for i, w in enumerate(words) if w[0] in emph_t}


def visemes(word):
    w = re.sub(r"[^a-zI]", "", re.sub(r"^i\b", "I", word.lower()))  # I, I'm, I'll: long i
    if re.search(r"[aiou][^aeiouy]e$", w):  # magic e: time, make, home
        w = w[:-3] + w[-3].upper() + w[-2]
    elif w.endswith("e") and re.search(r"[aeiouy]", w[:-1]):  # silent final e
        w = w[:-1]
    elif w.endswith("y") and not re.search(r"[aeiou]", w):  # my, why, try
        w = w[:-1] + "I"
    out, i = [], 0
    while i < len(w):
        for rx, shape in RULES:
            m = rx.match(w, i)
            if m:
                if shape and (not out or out[-1] != shape):
                    out.append(shape)
                i = m.end()
                break
    return out or ["C"]


def lip_cues(words):
    cues = [(0.0, "X")]
    for k, (a, b, text) in enumerate(words):
        shapes = visemes(text)
        total, t = sum(WEIGHT.get(s, 1.5) for s in shapes), a
        for s in shapes:
            cues.append((t, s))
            t += (b - a) * WEIGHT.get(s, 1.5) / total
        if k + 1 == len(words) or words[k + 1][0] - b > 0.1:
            cues.append((b, "X"))
    return cues


def mouth_cues(wav, segs, words):
    if not RHUBARB.exists():
        print("Rhubarb not found: mouth timed from spelling, exact to the word only", flush=True)
        return lip_cues(words)
    work = Path(wav).parent
    (work / "dialog.txt").write_text(" ".join(s["text"] for s in segs), encoding="utf-8")
    subprocess.run([str(RHUBARB), "-q", "-f", "json", "--extendedShapes", "X", "-d", str(work / "dialog.txt"),
                    "-o", str(work / "rhubarb.json"), wav], check=True)
    return [(c["start"], RB_MAP[c["value"]]) for c in json.loads((work / "rhubarb.json").read_text())["mouthCues"]]


def segment(words, emph=(), max_words=3):
    """Caption chunks break on short pauses/3 words and around emphasized words; sentence-length pauses are cut points."""
    chunks, cur, cuts = [], [], [0.0]
    for i, w in enumerate(words):
        if i in emph and cur:
            chunks.append(cur)
            cur = []
        cur.append(w)
        gap = words[i + 1][0] - w[1] if i + 1 < len(words) else 1.0
        if len(cur) >= max_words or gap > 0.15 or i in emph or i + 1 in emph:
            chunks.append(cur)
            cur = []
        if gap > 0.35 and i + 1 < len(words):
            cuts.append(words[i + 1][0])
    return chunks, cuts


def plan(segs, cuts, poses, bgs):
    """Shots, sound events and music drops from the screenplay tags. Exits on any unknown name."""
    def first(pref, names):
        return pref if pref in names else sorted(names)[0]
    base = {"frame": "med", "pose": first("rest", poses), "bg": first("room", bgs), "aspect": "9:16", "look": "clean"}
    opening, shots, events, drops = dict(base), [], [], []
    for k, seg in enumerate(segs):
        for name, args in seg["marks"]:
            if name == "shot":
                kv = dict(x.split("=", 1) for x in args)
                base = {**base, **{key: kv[key] for key in base if key in kv}}
                shots.append({**base, "move": kv.get("move"), "tilt": float(kv.get("tilt", 0)), "in": kv.get("in", "cut"),
                              "side": kv.get("side", "center"), "lens": kv.get("lens", "normal"), "focus": kv.get("focus", "none"), "t": seg["t"]})
                bad = set(kv) - set(shots[-1])
            elif name == "sfx":
                events += [(seg["t"], s) for s in args]
                bad = set(args) - set(sound.SFX)
            else:
                drops.append((segs[k - 1]["end"] if k else 0.0, seg["t"]))
                bad = set()
            if bad:
                sys.exit(f"unknown {name} option(s) {sorted(bad)}")
    if not shots:  # plain script: a simple cut pattern at sentence pauses
        auto = [{"frame": "med", "move": "cu"}, {"frame": "wide", "in": "whip"}, {"frame": "cu", "move": "ecu"}, {"frame": "med", "in": "zoom"}]
        shots = [{**base, **PER_SHOT, **auto[i % 4], "t": c} for i, c in enumerate(cuts)]
    if shots[0]["t"] > 0.3:
        shots.insert(0, {**opening, **PER_SHOT, "t": 0.0})
    shots[0]["t"] = 0.0
    for i, s in enumerate(shots):
        checks = {"frame": s["frame"] in FACE_SHARE, "move": s["move"] in FACE_SHARE or s["move"] is None, "pose": s["pose"] in poses,
                  "bg": s["bg"] in bgs, "aspect": s["aspect"] in ASPECTS, "in": s["in"] in TRANSITIONS, "look": s["look"] in ("clean", "cam"),
                  "side": s["side"] in ("center", "left", "right"), "lens": s["lens"] in ("normal", "tele"), "focus": s["focus"] in ("none", "pull")}
        bad = [f"{k}={s[k]}" for k, ok in checks.items() if not ok]
        if bad:
            sys.exit(f"shot {i} at {s['t']:.1f}s: unknown {', '.join(bad)}; poses {sorted(poses)}, backgrounds {sorted(bgs)}")
        events += {"whip": [(s["t"] - 0.25, "whoosh")], "zoom": [(s["t"] - 0.2, "whoosh")], "glitch": [(s["t"], "glitch")]}.get(s["in"], [])
        if s["look"] == "cam" and (i == 0 or shots[i - 1]["look"] != "cam"):
            events.append((s["t"], "beep"))
    return shots, events, drops


def load_pose(d):
    meta = json.loads((d / "pose.json").read_text())
    rest = Image.open(d / "X.png").convert("RGBA")
    assert rest.size == (CW, CH), f"{d} is {rest.size}, not the {CW}x{CH} stage"
    return {"X": rest, "face": meta["face"], "box": meta["box"],
            "patches": {p.stem: Image.open(p).convert("RGBA") for p in d.glob("[BCDEF].png")}}


def load_bg(path):
    if path is None:  # no backgrounds supplied
        t = np.linspace(0, 1, CH)[:, None, None]
        im = Image.fromarray(np.repeat((np.array((24, 14, 48)) * (1 - t) + np.array((70, 30, 90)) * t).astype(np.uint8), CW, 1))
    else:
        im = Image.open(path).convert("RGB")
        s = max(CW / im.width, CH / im.height)
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        im = im.crop(((im.width - CW) // 2, (im.height - CH) // 2, (im.width - CW) // 2 + CW, (im.height - CH) // 2 + CH))
    return [im] + [im.filter(ImageFilter.GaussianBlur(r)) for r in (5, 11, 18)]  # depth-of-field levels


def target(pose, frame, aspect):
    fx, fy, fw = pose["face"]
    keep = min(1.0, (W / ASPECTS[aspect]) / H)  # letterboxed: centre on the face, the strip is the frame
    z = max(1.0, FACE_SHARE[frame] * CW / fw)
    if keep < 1:
        z = max(z, 1.05 * CH / (2 * fy))  # tight enough that the crop can centre on the face
    return z, fx, fy + (FACE_DROP[frame] * fw if keep == 1 else 0.05 * fw)  # letterbox strip: eyes to mouth


def crop(img, cx, cy, z, resample=Image.BILINEAR):
    cw = CW / max(z, 1.0)  # never wider than the stage (breathing dips just under 1 on wide shots)
    ch = cw * H / W
    x0, y0 = min(max(cx - cw / 2, 0), CW - cw), min(max(cy - ch / 2, 0), CH - ch)
    box = (x0, y0, x0 + cw, y0 + ch)
    return img.resize((W, H), resample, box=box), box


def smear(frame, k, kv=1):
    """Cheap motion blur: shrink and re-grow (k horizontal, kv vertical)."""
    return frame.resize((max(1, W // k), max(1, H // kv)), Image.BILINEAR).resize((W, H), Image.BILINEAR)


def font_for(size, cache={}):
    if size not in cache:
        for f in FONTS:
            try:
                cache[size] = ImageFont.truetype(f, size)
                break
            except OSError:
                pass
        else:
            cache[size] = ImageFont.load_default(size)
    return cache[size]


def draw_caption(frame, chunk, t, y, big):
    """Heavy caps with a drop shadow; the spoken word sits in an accent box. big: one emphasized word, giant and tilted."""
    a = min(1.0, (t - chunk[0][0]) * FPS / 6)
    pop = 0.75 + 0.25 * a + 0.35 * math.sin(math.pi * a) * (1 - a)  # overshoot pop-in
    texts = [w[2].upper() for w in chunk]
    size = 200 if big else 108
    d = ImageDraw.Draw(frame)
    while True:
        f = font_for(size)
        widths = [d.textlength(x, font=f) for x in texts]
        gap = size * 0.28
        total = sum(widths) + gap * (len(texts) - 1)
        if total <= W * 0.86 or size < 50:
            break
        size -= 8
    lh = int(size * 1.6)
    layer, shadow = Image.new("RGBA", (W, lh), (0, 0, 0, 0)), Image.new("RGBA", (W, lh), (0, 0, 0, 0))
    dl, ds = ImageDraw.Draw(layer), ImageDraw.Draw(shadow)
    x, base = (W - total) / 2, lh * 0.72
    for txt, w, (s0, s1, _) in zip(texts, widths, chunk):
        ds.text((x + size * 0.06, base + size * 0.08), txt, font=f, fill=(0, 0, 0, 170), anchor="ls")
        if big:
            dl.text((x, base), txt, font=f, fill=ACCENT, stroke_width=12, stroke_fill=(0, 0, 0), anchor="ls")
        elif s0 <= t < s1 + 0.05:
            left, top, r, bot = dl.textbbox((x, base), txt, font=f, anchor="ls")
            dl.rounded_rectangle((left - 16, top - 12, r + 16, bot + 12), radius=int(size * 0.18), fill=ACCENT)
            dl.text((x, base), txt, font=f, fill=(10, 10, 10), anchor="ls")
        else:
            dl.text((x, base), txt, font=f, fill=(255, 255, 255), stroke_width=10, stroke_fill=(0, 0, 0), anchor="ls")
        x += w + gap
    shadow = shadow.filter(ImageFilter.GaussianBlur(size * 0.06))
    shadow.alpha_composite(layer)
    if big:
        shadow = shadow.rotate(4, Image.BICUBIC, expand=True)
    cap = shadow.resize((max(1, round(shadow.width * pop)), max(1, round(shadow.height * pop))), Image.BILINEAR)
    frame.paste(cap, (round((W - cap.width) / 2), round(y - cap.height * 0.6)), cap)


def render(a):
    out = Path(a.out).resolve()
    work = out.with_suffix("")
    work.mkdir(parents=True, exist_ok=True)
    wav = str(work / "voice.wav")
    segs, says = parse(Path(a.script).read_text(encoding="utf-8").strip())
    seconds, words, emph = voice_track(segs, says, a.voice, wav)
    print(f"voice {seconds:.1f}s, {len(words)} caption words, {len(segs)} segments", flush=True)
    if a.dry:
        return
    char = Path(a.char).expanduser()
    pose_dirs = {p.parent.name: p.parent for p in char.glob("poses/*/pose.json")}
    bg_files = {p.stem: p for p in sorted(char.glob("backgrounds/*")) if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")} or {"none": None}
    if not pose_dirs:
        sys.exit(f"no poses in {char / 'poses'}; build them with build_poses.py")
    chunks, cuts = segment(words, emph)
    shots, events, drops = plan(segs, cuts, pose_dirs, bg_files)
    big = [len(c) == 1 and words.index(c[0]) in emph for c in chunks]
    punches = [(words[i][0], next((g["end"] for g in segs if g["t"] - 0.01 <= words[i][0] <= g["end"] + 0.01), words[i][1])) for i in sorted(emph)]
    poses = {k: load_pose(pose_dirs[k]) for k in {s["pose"] for s in shots}}
    bgs = {k: load_bg(bg_files[k]) for k in {s["bg"] for s in shots}}
    cues = mouth_cues(wav, segs, words)
    cue_t, starts, shot_t = [c[0] for c in cues], [c[0][0] for c in chunks], [s["t"] for s in shots]
    n = int(seconds * FPS)
    mixed = str(work / "mix.wav")
    sound.mix(ffmpeg(), wav, a.music, events, drops, mixed, n / FPS)

    yy, xx = np.mgrid[0:2 * H, 0:2 * W]
    light = Image.fromarray((255 * (1 - 0.55 * (((xx - W) / (W * 0.85)) ** 2 + ((yy - H) / (H * 0.5)) ** 2))).clip(70, 255).astype(np.uint8))
    black = Image.new("RGB", (W, H), 0)
    grain = [Image.fromarray(np.random.default_rng(i).integers(0, 255, (H // 2, W // 2), np.uint8)).resize((W, H)).convert("RGB") for i in range(4)]

    enc = subprocess.Popen([ffmpeg(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                            "-i", "-", "-i", mixed, "-map", "0:v", "-map", "1:a", "-af", "loudnorm=I=-14:TP=-1.0:LRA=11", "-ar", "48000", "-ac", "2",
                            # YouTube's recommended upload spec (also fine for Reels): H.264 High, closed GOP of half the frame rate,
                            # 2 B-frames, generous VBR, BT.709 tags, AAC-LC 48 kHz stereo 384k
                            "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-maxrate", "16M", "-bufsize", "32M", "-profile:v", "high",
                            "-level:v", "4.2", "-g", str(FPS // 2), "-bf", "2", "-flags", "+cgop", "-pix_fmt", "yuv420p",
                            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                            "-c:a", "aac", "-b:a", "384k", "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
    shapes, pic_h = [], H
    for i in range(n):
        t = i / FPS
        k = bisect.bisect_right(shot_t, t) - 1
        sh, nxt = shots[k], shots[k + 1] if k + 1 < len(shots) else None
        end = nxt["t"] if nxt else n / FPS
        since, left = (t - sh["t"]) * FPS, (end - t) * FPS
        pose = poses[sh["pose"]]

        # camera: eased push from frame to move, plus handheld drift and transition moves
        z0, x0, y0 = target(pose, sh["frame"], sh["aspect"])
        z1, x1, y1 = target(pose, sh["move"] or sh["frame"], sh["aspect"])
        p = (t - sh["t"]) / max(end - sh["t"], 0.1)
        p = p * p * (3 - 2 * p)
        z, cx, cy = math.exp(math.log(z0) + (math.log(z1) - math.log(z0)) * p), x0 + (x1 - x0) * p, y0 + (y1 - y0) * p
        if not sh["move"]:
            z *= 1 + 0.05 * p  # slow dolly keeps every shot alive
        if any(s0 <= t < s1 for s0, s1 in punches):
            z *= 1.16  # punch-in on an emphasized word, held to the end of the sentence
        cx += {"left": 1, "right": -1}.get(sh["side"], 0) * CW / z / 6  # face on the left or right third
        cx += CW / z * 0.006 * (math.sin(1.1 * t) + 0.5 * math.sin(2.7 * t + 1))
        cy += CW / z * 0.005 * (math.sin(0.9 * t + 2) + 0.5 * math.sin(2.3 * t))
        if sh["in"] == "zoom" and since < 8:
            z *= 1 + 0.35 * (1 - since / 8) ** 2
        if nxt and nxt["in"] == "zoom" and left < 4:
            z *= 1 + 0.35 * (1 - left / 4) ** 2
        tilt = sh["tilt"] + (0.6 * p if sh["tilt"] else 0)  # dutch angles keep creeping
        if tilt:
            z *= math.cos(math.radians(abs(tilt))) + H / W * math.sin(math.radians(abs(tilt)))  # cover the corners after rotating

        # background with parallax and depth of field, then the character, then the mouth
        levels = bgs[sh["bg"]]
        tele = sh["lens"] == "tele"  # long lens: the set looms larger and softer behind him
        bz = (1 + (z - 1) * 0.5) * (1.35 if tele else 1)
        bx, by = CW / 2 + (cx - CW / 2) * 0.5, CH / 2 + (cy - CH / 2) * 0.5
        pull = max(0.0, 1 - since / 18) if sh["focus"] == "pull" else 0.0  # rack focus: set sharp first, then him
        f = min(3.0, max(0.0, (z - 1) * 1.4 + (1.2 if tele else 0))) * (1 - pull)
        frame = crop(levels[int(f)], bx, by, bz)[0]
        if 0.2 < f - int(f) < 0.8 and int(f) < 3:
            frame = Image.blend(frame, crop(levels[int(f) + 1], bx, by, bz)[0], f - int(f))
        breath = 1 + 0.004 * math.sin(2 * math.pi * t / 3.4)
        body, box = crop(pose["X"], cx, cy, z * breath, Image.LANCZOS if z > 2 else Image.BILINEAR)
        if pull > 0.05:
            body = body.filter(ImageFilter.GaussianBlur(12 * pull ** 2))
        frame.paste(body, (0, 0), body)
        shape = cues[bisect.bisect_right(cue_t, t) - 1][1]
        shapes.append(shape)
        if shape in pose["patches"]:
            patch, (px, py) = pose["patches"][shape], pose["box"]
            s = W / (box[2] - box[0])
            pr = patch.resize((max(1, round(patch.width * s)), max(1, round(patch.height * s))), Image.BILINEAR)
            frame.paste(pr, (round((px - box[0]) * s), round((py - box[1]) * s)), pr)
        if tilt:
            frame = frame.rotate(tilt, Image.BICUBIC)

        # transitions
        if sh["in"] == "whip" and since < 6:
            frame = smear(frame, int(4 + 20 * (1 - since / 6)))
        if nxt and nxt["in"] == "whip" and left < 3:
            frame = smear(frame, int(4 + 20 * (1 - left / 3)))
        if sh["in"] == "zoom" and since < 4:
            frame = smear(frame, 3, 3)
        if sh["in"] == "glitch" and since < 5:
            dx = int(30 * (1 - since / 5)) + 4
            r, g, b = frame.split()
            frame = Image.merge("RGB", (ImageChops.offset(r, dx, 0), g, ImageChops.offset(b, -dx, 0)))
            for j in range(3):
                y = (i * 397 + j * 641) % (H - 120)
                frame.paste(frame.crop((0, y, W, y + 60 + 30 * j)), ((-1) ** j * dx * 3, y))
        if sh["in"] == "fade" and since < 9:
            frame = Image.blend(black, frame, since / 9)

        # look, aspect bars, captions
        sc = W / (box[2] - box[0])  # light follows his face
        fx, fy = (pose["face"][0] - box[0]) * sc, (pose["face"][1] - box[1]) * sc
        fx, fy = int(min(max(fx, 0), W)), int(min(max(fy, 0), H))
        frame = Image.composite(frame, black, light.crop((W - fx, H - fy, 2 * W - fx, 2 * H - fy)))
        if sh["look"] == "cam":
            frame = Image.blend(Image.blend(frame, frame.convert("L").convert("RGB"), 0.3), grain[i % 4], 0.07)
        goal = min(H, W / ASPECTS[sh["aspect"]])
        pic_h += (goal - pic_h) * 0.35  # bars glide in and out
        if pic_h < H - 2:
            bar = int((H - pic_h) / 2)
            d = ImageDraw.Draw(frame)
            d.rectangle((0, 0, W, bar), fill=0)
            d.rectangle((0, H - bar, W, H), fill=0)
        if sh["look"] == "cam":
            d, top = ImageDraw.Draw(frame), int((H - pic_h) / 2)
            if int(t * 2) % 2 == 0:
                d.ellipse((48, top + 44, 84, top + 80), fill=(230, 30, 30))
            d.text((100, top + 80), "REC", font=font_for(48), fill="white", anchor="ls")
            d.text((W - 48, H - top - 40), f"00:{int(t) // 60:02d}:{int(t) % 60:02d}:{i % FPS:02d}", font=font_for(44), fill="white", anchor="rs")
        ci = bisect.bisect_right(starts, t) - 1
        if ci >= 0 and t < chunks[ci][-1][1] + 1.2:  # hold through a forced pause
            bar = (H - pic_h) / 2
            draw_caption(frame, chunks[ci], t, CAPTION_Y if bar < 200 else H - bar / 2 + 36, big[ci])
        enc.stdin.write(frame.tobytes())
        if i % (FPS * 5) == 0:
            print(f"frame {i}/{n}", flush=True)
    enc.stdin.close()
    if enc.wait():
        sys.exit("ffmpeg encode failed")
    (work / "timeline.json").write_text(json.dumps({"words": words, "shapes": "".join(shapes), "shots": shots}))
    print(f"OK {out} ({n / FPS:.1f}s, {len(shots)} shots)")


def selftest():
    words = [(0.0, 0.3, "a"), (0.3, 0.6, "b"), (0.6, 0.9, "c"), (0.9, 1.2, "d"), (1.8, 2.0, "e")]
    chunks, cuts = segment(words)
    assert [len(c) for c in chunks] == [3, 1, 1], chunks
    assert cuts == [0.0, 1.8], cuts
    segs, says = parse("[hype] I am {AJ=A J}. [pause 1] [shot frame=cu move=ecu] [sfx boom] [sarcastic] Hi [drop] there")
    assert [(s["text"], s["tone"], s["pause"]) for s in segs] == [("I am A J.", "hype", 1.0), ("Hi", "sarcastic", 0.0), ("there", "sarcastic", 0.0)], segs
    assert segs[1]["marks"] == [("shot", ["frame=cu", "move=ecu"]), ("sfx", ["boom"])] and segs[2]["marks"] == [("drop", [])], segs
    assert says == [(["A", "J"], "AJ")]
    e = parse("This is *the plan*.")[0][0]
    assert e["text"] == "This is the plan." and e["emph"] == ["the", "plan"], e
    ew = [(0.0, 0.2, "This"), (0.2, 0.4, "is"), (0.4, 0.6, "the"), (0.6, 0.9, "plan.")]
    assert [len(c) for c in segment(ew, {2, 3})[0]] == [2, 1, 1]
    for s, t in zip(segs, (0.0, 2.0, 3.0)):
        s["t"], s["end"] = t, t + 0.5
    shots, events, drops = plan(segs, [0.0], {"rest": 1}, {"room": 1})
    assert [(s["t"], s["frame"], s["move"]) for s in shots] == [(0.0, "med", None), (2.0, "cu", "ecu")], shots
    assert events == [(2.0, "boom")] and drops == [(2.5, 3.0)], (events, drops)
    for word, want in {"my": "XD", "time": "BDX", "you": "BF", "talk": "BEB", "I'm": "DX"}.items():
        assert "".join(visemes(word)) == want, (word, visemes(word))
    print("selftest ok")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--script", help="UTF-8 screenplay file")
    p.add_argument("--out", default="short.mp4")
    p.add_argument("--char", default=str(REPO / "my" / "built"), help="folder with poses/ and backgrounds/ from build_poses.py")
    p.add_argument("--music", help="background music file")
    p.add_argument("--voice", default="en-US-AndrewNeural")
    p.add_argument("--dry", action="store_true", help="only make the voice and print its length (for tuning script length)")
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args()
    selftest() if a.selftest else render(a)
