"""Stickman Studio pipeline for the daily agent (settings: [pipeline] mode = "stickman").

One run: Claude picks a "What if..." premise and writes a 5-scene script -> the voiceover
comes from MoneyPrinterTurbo's TTS (stickman-studio/voice.py, "tts": "moneyprinter") ->
Claude writes the scenes.swift animation for that narration -> it is compiled (compiler
errors go back to Claude), test frames are rendered and checked (blank frames, crashes,
and an optional visual review of a contact sheet) -> stickman-studio/make_video.sh renders
the final 1080x1920 video. agent.py then writes captions, runs the safety review and posts.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import agent as A

log = A.log
ENV_PATH = f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
W, H = 1080, 1920


def studio_dir(settings: dict) -> Path:
    return (A.HERE / settings["stickman"].get("studio_dir", "../../stickman-studio")).resolve()


def channel_settings(settings: dict) -> dict:
    """Settings view whose [content] is the stickman channel, for agent.write_metadata/safety_check."""
    return {**settings, "content": settings["stickman"]}


def _claude_args(settings: dict) -> list[str]:
    model = settings["stickman"].get("model", "")
    return ["--model", model] if model else []


def _run(cmd: list[str], cwd: Path, timeout: int = 600, **kw) -> subprocess.CompletedProcess:
    env = {**A._clean_env(), "PATH": ENV_PATH, "MPT_DIR": str(A.REPO)}
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, timeout=timeout, **kw)


# --------------------------------------------------------------------------- story


def pick_topic(settings: dict, history: list[dict]) -> str:
    s = settings["stickman"]
    studio = studio_dir(settings)
    previous = [h["topic"] for h in history if h.get("pipeline") == "stickman" and h.get("topic")][-300:]
    for f in sorted(studio.glob("videos/*/script.json")):  # the hand-made videos count too
        try:
            previous.append(json.loads(f.read_text()).get("title", ""))
        except (OSError, json.JSONDecodeError):
            pass
    previous = [p for p in previous if p]
    seen = {A._norm(t) for t in previous}
    prev_block = "\n".join(f"- {t}" for t in previous) or "(none yet)"
    prompt = f"""You run a faceless TikTok channel of 30-second animated stickman stories: {s['niche']}
Propose ONE new premise for the next video.
GOOD examples: {s.get('topic_good', '')}
BAD / forbidden: {s.get('topic_bad', '')}
Rules: {s.get('topic_rules', '')}
It must not repeat or closely resemble any previous premise:
{prev_block}

Respond with only JSON, no other text: {{"topic": "What if ...?"}}"""
    for _ in range(4):
        topic = str(A.ask_claude_json(prompt).get("topic", "")).strip().strip('"')
        if topic and A._norm(topic) not in seen:
            return topic
        log.warning("Claude proposed a duplicate/empty premise (%r); asking again", topic)
    raise RuntimeError("could not get a fresh premise from Claude")


def write_story(topic: str, settings: dict, revision_note: str = "") -> list[str]:
    s = settings["stickman"]
    n = int(s.get("scene_count", 5))
    max_words = int(s.get("max_words", 85))
    revision = (f"\nA reviewer rejected the previous draft; fix all of this: {revision_note}\n"
                if revision_note else "")
    prompt = f"""Write the narration for a 30-second animated stickman short titled: {topic}
Channel: {s['niche']}
{s['script_requirements']}
Split it into exactly {n} scenes (one string each, spoken in order, a new picture for each).
Total length {max_words - 20}-{max_words - 5} words.{revision}
Respond with only JSON: {{"scenes": ["...", "..."]}}"""
    for _ in range(3):
        scenes = [str(x).strip() for x in A.ask_claude_json(prompt).get("scenes", []) if str(x).strip()]
        words = sum(len(x.split()) for x in scenes)
        if len(scenes) == n and 45 <= words <= max_words:
            return scenes
        log.warning("Story had %d scenes / %d words; asking again", len(scenes), words)
    raise RuntimeError("Claude did not return a usable 5-scene story")


# --------------------------------------------------------------------------- folder + voice


def new_video_dir(settings: dict, topic: str) -> Path:
    slug = "-".join(re.findall(r"[a-z0-9]+", topic.lower().replace("what if", ""))[:5]) or "video"
    vdir = studio_dir(settings) / "videos" / f"auto-{datetime.now():%Y%m%d-%H%M}-{slug}"
    vdir.mkdir(parents=True, exist_ok=False)
    return vdir


def make_voice(vdir: Path, topic: str, scenes: list[str], settings: dict) -> dict:
    s = settings["stickman"]
    (vdir / "script.json").write_text(json.dumps({
        "title": topic, "tts": "moneyprinter",
        "voice": s.get("voice", "en-US-AndrewMultilingualNeural-Male"),
        "rate": float(s.get("rate", 1.0)), "scenes": scenes,
    }, indent=2, ensure_ascii=False))
    for attempt in range(1, 4):  # Edge TTS is occasionally flaky
        proc = _run(["python3", "voice.py", str(vdir)], studio_dir(settings), timeout=600, text=True)
        if proc.returncode == 0 and (vdir / "timing.json").exists():
            timing = json.loads((vdir / "timing.json").read_text())
            log.info("Voiceover: %.1fs (%s)", timing["total"], s.get("voice"))
            return timing
        log.warning("Voiceover attempt %d failed: %s", attempt, (proc.stderr or proc.stdout)[-500:])
        time.sleep(20)
    raise RuntimeError("voiceover failed")


# --------------------------------------------------------------------------- animation code


def _timing_block(timing: dict) -> str:
    lines = []
    for i, sc in enumerate(timing["scenes"]):
        lines.append(f"scene {i} (index {i}): length {sc['end'] - sc['start']:.2f}s, "
                     f"speech ends at {sc['speechEnd'] - sc['start']:.2f}s")
        for sub in timing["subs"]:
            if sc["start"] - 0.01 <= sub["start"] < sc["end"]:
                lines.append(f"    {sub['start'] - sc['start']:5.2f}s  \"{sub['text']}\"")
    return "\n".join(lines)


def _base_prompt(settings: dict, vdir: Path, timing: dict) -> str:
    studio = studio_dir(settings)
    example = settings["stickman"].get("example", "freeze-time")
    script = json.loads((vdir / "script.json").read_text())
    n = len(script["scenes"])
    return f"""You write scenes.swift for Stickman Studio: a Swift + CoreGraphics renderer for 1080x1920,
30 fps vertical shorts. Your file is compiled together with engine.swift and main.swift.

=== engine.swift (already compiled with your file; use its helpers, NEVER redefine anything in it) ===
```swift
{(studio / 'engine.swift').read_text()}
```

=== A finished hand-made scenes.swift for another video: match this quality and style ===
```swift
{(studio / 'videos' / example / 'scenes.swift').read_text()}
```

=== The NEW video ===
Title: {script['title']}
Narration per scene:
{chr(10).join(f'  scene {i}: {t}' for i, t in enumerate(script['scenes']))}
Timing (times relative to each scene start; these are the subtitle lines and when they are spoken):
{_timing_block(timing)}

Requirements:
- Define exactly `func drawScene(_ i: Int, _ t: Double, _ len: Double)` handling i = 0...{n - 1}
  (use `default:` for the last), and
  `func sceneCamera(_ i: Int, _ t: Double, _ len: Double) -> (zoom: CGFloat, x: CGFloat, y: CGFloat)`.
  t = seconds since the scene started, len = scene length.
- Every scene first paints the whole frame (vgrad or a full-size rect), then a ground/floor,
  props built from shapes, and the red-hoodie stickman (stickman(...)) acting out that line,
  with pose/eye changes timed to words via cue(i, "word", fallback) using words from the
  subtitle lines above. Something moves at all times (walking, falling objects, camera push).
- Scene 0 shows a big bold title (2-4 words, AvenirNext-Heavy ~110pt, outlined) in y 150-420.
  When the narration says a number, show it big on screen.
- Coordinates: x 0..1080 left to right, y 0..1920 top to bottom. The engine draws subtitles at
  y 1500-1700 and handles fades: put the ground line at y 1400-1450 with feet on it; keep text
  and key action above y 1450 and inside x 60..1020.
- Pure Swift with CoreGraphics/CoreText only. Deterministic (hash(n), never random). No force
  unwraps that can fail, no array indexing that can go out of range, no division by values that
  can be 0, no files, no network. Fonts: AvenirNext-Heavy, AvenirNext-Bold, Menlo-Bold.
- 180-320 lines. The Swift type checker is slow on long mixed expressions: split long arithmetic
  into separate `let` constants with explicit CGFloat/Double types.
- Nothing scary, gory or violent; cartoon-friendly for all ages.
"""


def _extract_swift(text: str) -> str:
    m = re.search(r"```swift\s*\n(.*?)```", text, re.S) or re.search(r"```\s*\n(.*?)```", text, re.S)
    code = (m.group(1) if m else text).strip()
    if "func drawScene" not in code or "func sceneCamera" not in code:
        raise RuntimeError("Claude's reply had no drawScene/sceneCamera")
    return code + "\n"


def compile_scenes(settings: dict, vdir: Path) -> str:
    """Returns "" on success, otherwise the compiler errors."""
    proc = _run(["swiftc", "-O", "engine.swift", "main.swift", str(vdir / "scenes.swift"), "-o", str(vdir / "render")],
                studio_dir(settings), timeout=600, text=True)
    if proc.returncode == 0:
        return ""
    errs = [l for l in (proc.stderr or proc.stdout).splitlines() if "error" in l or l.startswith(" ")]
    return "\n".join(errs[:60]) or (proc.stderr or proc.stdout)[-3000:]


def sample_times(timing: dict) -> list[float]:
    out = []
    for sc in timing["scenes"]:
        length = sc["end"] - sc["start"]
        out += [sc["start"] + 0.35 * length, sc["start"] + 0.8 * length]
    return out


def check_frames(settings: dict, vdir: Path, timing: dict) -> tuple[str, list[Path]]:
    """Render sample frames. Returns (problem description or "", PNG paths)."""
    from PIL import Image, ImageStat

    review = vdir / "review"
    shutil.rmtree(review, ignore_errors=True)
    review.mkdir()
    pngs, problems = [], []
    times = sample_times(timing) + [0.05, timing["total"] - 0.6]
    for n, t in enumerate(times):
        proc = _run([str(vdir / "render"), str(vdir / "timing.json"), f"{t:.3f}"], vdir, timeout=60)
        if proc.returncode != 0 or len(proc.stdout) != W * H * 4:
            err = proc.stderr.decode(errors="replace").strip()[-800:]
            problems.append(f"the renderer crashed at t={t:.2f}s: {err or 'no output'}")
            continue
        img = Image.frombytes("RGBA", (W, H), proc.stdout, "raw", "BGRA").convert("RGB")
        if sum(ImageStat.Stat(img.resize((108, 192))).stddev) < 6:
            problems.append(f"the frame at t={t:.2f}s is blank (one flat colour)")
        if n < len(times) - 2:
            p = review / f"f{n:02d}.png"
            img.resize((324, 576)).save(p)
            pngs.append(p)
    return "\n".join(problems), pngs


def visual_review(settings: dict, vdir: Path, timing: dict, pngs: list[Path]) -> tuple[str, str]:
    """Claude looks at a contact sheet. Returns (verdict ok/minor/broken, issues)."""
    from PIL import Image

    cols = 5
    rows = -(-len(pngs) // cols)
    sheet = Image.new("RGB", (324 * cols, 576 * rows), "black")
    for k, p in enumerate(pngs):
        sheet.paste(Image.open(p), ((k % cols) * 324, (k // cols) * 576))
    path = A.STATE / "stickman-review.png"
    sheet.save(path)
    script = json.loads((vdir / "script.json").read_text())
    narr = "\n".join(f"  scene {i}: {t}" for i, t in enumerate(script["scenes"]))
    prompt = f"""Use the Read tool to look at the image {path}.
It is a contact sheet of {len(pngs)} frames from a 30-second animated stickman short, left to right,
top to bottom, two frames per scene (early, late). Subtitles are part of the frames.
Narration:
{narr}

Judge it as a viewer would. "broken": a frame is empty or black, the stickman is missing or cut
off in most frames, shapes are obviously garbled, or title text runs off the frame. "minor": works
but some scene does not illustrate its narration or text overlaps badly. "ok": a clear, friendly
cartoon where each scene shows its line.
Respond with only JSON: {{"verdict": "ok" | "minor" | "broken", "issues": "concrete fixes, per scene"}}"""
    try:
        data = A.ask_claude_json_args(prompt, ["--allowedTools", "Read", *_claude_args(settings)])
    except Exception as exc:
        log.warning("Visual review failed (%s); skipping it", exc)
        return "ok", ""
    return str(data.get("verdict", "ok")).lower(), str(data.get("issues", ""))


def build_animation(settings: dict, vdir: Path, timing: dict) -> None:
    s = settings["stickman"]
    base = _base_prompt(settings, vdir, timing)
    budget = int(s.get("compile_attempts", 5))
    reviews_left = 1 if s.get("visual_review", True) else 0
    code = _extract_swift(A.ask_claude(
        base + "\nRespond with only the complete Swift file in one ```swift block.",
        timeout=1200, extra_args=_claude_args(settings)))
    for attempt in range(1, budget + 1):
        (vdir / "scenes.swift").write_text(code)
        problem = compile_scenes(settings, vdir)
        kind = "compile errors"
        if not problem:
            problem, pngs = check_frames(settings, vdir, timing)
            kind = "runtime problems"
        if not problem and reviews_left:
            verdict, issues = visual_review(settings, vdir, timing, pngs)
            log.info("Visual review: %s %s", verdict, issues[:300])
            if verdict in ("minor", "broken"):
                reviews_left -= 1
                problem, kind = issues or verdict, "visual review notes (improve the picture)"
        if not problem:
            log.info("Animation ready after %d attempt(s)", attempt)
            return
        log.info("Animation attempt %d: %s: %s", attempt, kind, problem[:400])
        if attempt == budget:
            break
        code = _extract_swift(A.ask_claude(
            f"{base}\n=== Your current scenes.swift ===\n```swift\n{code}```\n\n"
            f"It has these {kind}:\n{problem}\n\nFix them. Respond with only the complete corrected "
            f"Swift file in one ```swift block.", timeout=1200, extra_args=_claude_args(settings)))
    # Out of attempts: a visual "minor" is still postable, anything else is not.
    if compile_scenes(settings, vdir) or check_frames(settings, vdir, timing)[0]:
        raise RuntimeError(f"animation still failing after {budget} attempts")
    log.warning("Animation has unresolved review notes; using it anyway")


def render(settings: dict, vdir: Path) -> Path:
    studio = studio_dir(settings)
    env_cmd = ["/usr/bin/env", "SKIP_VOICE=1", "/bin/zsh", str(studio / "make_video.sh"), vdir.name]
    proc = _run(env_cmd, studio, timeout=1800, text=True)
    out = studio / "output" / f"{vdir.name}.mp4"
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError(f"make_video.sh failed: {(proc.stderr or proc.stdout)[-800:]}")
    for junk in ("render", "voice.wav"):
        (vdir / junk).unlink(missing_ok=True)
    return out


# --------------------------------------------------------------------------- entry points


def make_video(settings: dict, history: list[dict], topic: str | None = None) -> dict:
    """Pick a premise, pass the safety review, build the video. Returns the history entry."""
    chan = channel_settings(settings)
    entry = None
    for _ in range(3):
        t = topic or pick_topic(settings, history)
        log.info("Premise: %s", t)
        scenes = write_story(t, settings)
        script = " ".join(scenes)
        metadata = A.write_metadata(t, script, chan)
        ok, reason = A.safety_check(t, script, metadata, chan)
        if not ok and reason:
            log.info("Safety review asked for changes; revising once (%s)", reason[:160])
            scenes = write_story(t, settings, revision_note=reason)
            script = " ".join(scenes)
            metadata = A.write_metadata(t, script, chan)
            ok, reason = A.safety_check(t, script, metadata, chan)
        if ok:
            entry = {"created": datetime.now().isoformat(timespec="seconds"), "pipeline": "stickman",
                     "topic": t, "script": script, "scenes": scenes, "metadata": metadata}
            break
        log.warning("Safety review rejected this premise (%s); trying another", reason)
        history.append({"created": datetime.now().isoformat(timespec="seconds"), "pipeline": "stickman",
                        "topic": t, "note": f"rejected by safety review: {reason}"})
        A.save_history(history)
        if topic:
            break
    if entry is None:
        raise RuntimeError("no story passed the safety review")

    vdir = new_video_dir(settings, entry["topic"])
    entry["folder"] = str(vdir)
    timing = make_voice(vdir, entry["topic"], entry["scenes"], settings)
    last = None
    for attempt in range(1, 3):  # a second, fresh attempt if the first animation cannot be fixed
        try:
            build_animation(settings, vdir, timing)
            break
        except Exception as exc:
            last = exc
            log.warning("Animation build %d failed: %s", attempt, exc)
    else:
        raise RuntimeError(f"could not build the animation: {last}")
    entry["video"] = str(render(settings, vdir))
    return entry


def cleanup(settings: dict, history: list[dict]) -> None:
    """Delete stickman videos older than keep_days (scripts and scenes.swift are kept)."""
    keep_days = settings["housekeeping"].get("keep_days", 7)
    cutoff = time.time() - keep_days * 86400
    pending = {h.get("video") for h in history
               if any((h.get(p) or {}).get("status") in ("failed", "pending") for p in A.PLATFORMS)}
    studio = studio_dir(settings)
    removed = 0
    for mp4 in (studio / "output").glob("auto-*.mp4"):
        if str(mp4) not in pending and mp4.stat().st_mtime < cutoff:
            mp4.unlink()
            removed += 1
    for d in (studio / "videos").glob("auto-*"):
        for junk in ("render", "voice.wav", "review"):
            p = d / junk
            if p.exists() and p.stat().st_mtime < cutoff:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
    if removed:
        log.info("Cleanup removed %d old stickman videos", removed)
