#!/usr/bin/env python3
"""Autonomous short-video agent for MoneyPrinterTurbo.

Each run: pick a fresh topic with Claude -> generate the video with
MoneyPrinterTurbo -> write titles/captions -> post to YouTube and TikTok ->
record history -> clean up old files.

Commands:
  run [--topic T] [--force] [--no-youtube] [--no-tiktok] [--tiktok-dry-run]
  youtube-auth        one-time Google sign-in (opens browser)
  tiktok-login        one-time TikTok sign-in (opens Chrome)
  install-schedule    install/refresh the daily macOS launchd job
  uninstall-schedule  remove the launchd job
  status              show recent runs and setup state
"""
from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SECRETS = HERE / "secrets"
STATE = HERE / "state"
LOGS = HERE / "logs"
HISTORY_FILE = STATE / "history.json"
TIKTOK_PROFILE = SECRETS / "tiktok-chrome-profile"
LAUNCHD_LABEL = "local.moneyprinter.agent"
LAUNCHD_PLIST = Path.home() / "Library/LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
# A permanent `caffeinate -s -i` keeps the Mac from idle-sleeping (display may
# still sleep). It needs no sudo and survives MDM/System Settings resets of pmset.
AWAKE_LABEL = "local.moneyprinter.keepawake"
AWAKE_PLIST = Path.home() / "Library/LaunchAgents" / f"{AWAKE_LABEL}.plist"

for d in (SECRETS, STATE, LOGS):
    d.mkdir(parents=True, exist_ok=True)
os.chmod(SECRETS, 0o700)

log = logging.getLogger("agent")


def setup_logging() -> None:
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(LOGS / f"agent-{datetime.now():%Y-%m}.log")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.handlers[:] = [fh, sh]


def load_settings() -> dict:
    with open(HERE / "settings.toml", "rb") as f:
        return tomllib.load(f)


def load_history() -> list[dict]:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return []


def save_history(history: list[dict]) -> None:
    tmp = HISTORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, indent=2, ensure_ascii=False))
    tmp.replace(HISTORY_FILE)


def notify(message: str, title: str = "Video Agent") -> None:
    script = f"display notification {json.dumps(message)} with title {json.dumps(title)}"
    subprocess.run(["osascript", "-e", script], capture_output=True)


# --------------------------------------------------------------------------- Claude


def _clean_env() -> dict:
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_")) or key == "CLAUDECODE":
            env.pop(key)
    return env


def ask_claude(prompt: str, timeout: int = 300) -> str:
    claude = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    result = subprocess.run(
        [claude, "-p", prompt, "--output-format", "text"],
        cwd=STATE,
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def ask_claude_json(prompt: str, attempts: int = 3) -> dict:
    last_error = None
    for _ in range(attempts):
        text = ask_claude(prompt)
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError as exc:
                last_error = exc
        else:
            last_error = ValueError(f"no JSON in response: {text[:200]}")
    raise RuntimeError(f"Claude did not return valid JSON: {last_error}")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def pick_topic(settings: dict, history: list[dict]) -> str:
    previous = [h["topic"] for h in history if h.get("topic")][-300:]
    seen = {_norm(t) for t in previous}
    prev_block = "\n".join(f"- {t}" for t in previous) or "(none yet)"
    c = settings["content"]
    prompt = f"""You run a faceless TikTok/YouTube Shorts channel about: {c['niche']}.
Propose ONE new video topic that makes the viewer stop scrolling because it answers something
they privately wondered about but nobody explained plainly.
GOOD examples: {c.get('topic_good', '')}
BAD / forbidden: {c.get('topic_bad', 'myths, medical advice, politics, disputed claims')}
Rules: {c.get('topic_rules', 'accurate and widely accepted; concrete and visual')}
Phrase it as a punchy title of at most 10 words that states the claim itself.
It must not repeat or closely resemble any previous topic:
{prev_block}

Respond with only JSON, no other text: {{"topic": "..."}}"""
    for _ in range(4):
        topic = str(ask_claude_json(prompt).get("topic", "")).strip().strip('"')
        if topic and _norm(topic) not in seen:
            return topic
        log.warning("Claude proposed a duplicate/empty topic (%r); asking again", topic)
    raise RuntimeError("could not get a fresh topic from Claude")


def safety_check(topic: str, script: str, metadata: dict | None = None, settings: dict | None = None) -> tuple[bool, str]:
    """Independent review against the channel's safety criteria and platform rules."""
    c = (settings or load_settings())["content"]
    criteria = c.get("safety_criteria") or (
        "Reject if: explicit or erotic content; anything sexual involving minors; shaming; "
        "inaccurate or dangerous medical claims; anything TikTok would classify as adult content.")
    prompt = f"""You are an independent reviewer for a {c['niche']} channel (audience: {c.get('audience', 'general')}).
Review this short video before it is posted publicly on TikTok.
Topic: {topic}
Script: {script}
Caption: {(metadata or {}).get('tiktok_caption', '')}
Headline: {(metadata or {}).get('headline', '')}
Hashtags: {(metadata or {}).get('hashtags', [])}

{criteria}
Be strict: when in doubt, reject and say why.
Respond with only JSON: {{"ok": true/false, "reason": "..."}}"""
    data = ask_claude_json(prompt)
    return bool(data.get("ok")), str(data.get("reason", ""))


def pick_scene_prompts(topic: str, settings: dict) -> list[str]:
    """Scene descriptions for AI image generation, in narration order."""
    count = int(settings["video"].get("scene_count", 8))
    style = settings["video"].get("image_style", "photo")
    look = (
        "a bright, friendly Pixar-style 3D animated short: cute stylized characters, "
        "oversized props, clean colorful sets, one clear subject per scene"
        if style == "3d" else "a photorealistic image generator"
    )
    visual_rules = settings["content"].get(
        "visual_rules",
        "Vary the subjects; show the thing itself (animal, object, planet) at a dramatic scale.",
    )
    prompt = f"""A short video about {settings['content']['niche']} is titled: {topic}
Write {count} scene descriptions for {look}, following the likely narration order
(hook -> explanation details -> twist -> payoff). Each is one line of 10-18 words describing
a single concrete, visually striking image that illustrates that part: subject, action,
setting, lighting, camera angle. {visual_rules} No text, no numbers, no people's names,
no brand names, nothing violent or disturbing.
Respond with only JSON: {{"scenes": ["...", "..."]}}"""
    scenes = [str(s).strip().replace(",", ";") for s in ask_claude_json(prompt).get("scenes", [])]
    return [s for s in scenes if s][:count]


def ensure_image_server(style: str = "photo", timeout: int = 900) -> None:
    """Start automation/image_server.py (restarting it if its style differs)."""
    import urllib.request

    url = "http://127.0.0.1:7861/health"

    def current_style() -> str | None:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                return json.loads(r.read()).get("style")
        except Exception:
            return None

    running = current_style()
    if running == style:
        return
    if running is not None:
        log.info("Image server runs style %s; restarting with %s", running, style)
        subprocess.run(["pkill", "-f", "image_server.py"], capture_output=True)
        time.sleep(3)
    log.info("Starting local image server (style=%s)", style)
    env = {**_clean_env(), "IMAGE_STYLE": style}
    subprocess.Popen(
        [str(HERE / ".venv-images/bin/python"), str(HERE / "image_server.py")],
        cwd=HERE, env=env, stdout=open(LOGS / "image_server.log", "a"),
        stderr=subprocess.STDOUT, start_new_session=True,
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        if alive():
            return
        time.sleep(5)
    raise RuntimeError("local image server did not start")


def write_script(topic: str, settings: dict, revision_note: str = "") -> str:
    c = settings["content"]
    revision = (f"\nA medical reviewer rejected the previous draft and asked for these corrections; "
                f"apply all of them: {revision_note}\n") if revision_note else ""
    prompt = f"""Write the narration for a short vertical video titled: {topic}
Channel: {c['niche']}
Language: {c.get('language', 'en-US')}
{c['script_requirements']}{revision}
Respond with only the narration text, nothing else."""
    script = ask_claude(prompt).strip().strip('"')
    script = re.sub(r"^(narration|script)\s*:\s*", "", script, flags=re.I)
    max_words = int(c.get("max_script_words", 0) or 0)
    if max_words and len(script.split()) > max_words:
        log.info("Script is %d words (max %d); asking for a tighter version", len(script.split()), max_words)
        shorter = ask_claude(
            f"Shorten this narration to {max_words - 15}-{max_words - 5} words. Keep the hook sentence, "
            f"the key fact and the reassuring last line; keep the same tone and rules; cut everything else.\n\n"
            f"{script}\n\nRespond with only the narration text, nothing else."
        ).strip().strip('"')
        shorter = re.sub(r"^(narration|script)\s*:\s*", "", shorter, flags=re.I)
        if 40 <= len(shorter.split()) <= max_words:
            script = shorter
    if len(script.split()) < 40:
        raise RuntimeError(f"script too short: {script[:120]!r}")
    return script


def _pixabay_key() -> str:
    with open(REPO / "config.toml", "rb") as f:
        keys = tomllib.load(f).get("app", {}).get("pixabay_api_keys") or []
    return keys[0] if keys else ""


def pixabay_usable_hits(term: str, key: str) -> int:
    """How many Pixabay film clips for `term` are big enough for a 1080x1920 crop."""
    import urllib.parse
    import urllib.request

    url = ("https://pixabay.com/api/videos/?" + urllib.parse.urlencode(
        {"key": key, "q": term, "video_type": "film", "per_page": 50, "safesearch": "true"}))
    req = urllib.request.Request(url, headers={
        "User-Agent": "MoneyPrinterTurbo-agent/1.0 (+https://github.com/harry0703/MoneyPrinterTurbo)",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            hits = json.loads(r.read()).get("hits", [])
    except Exception as exc:
        log.warning("pixabay check failed for %r: %s", term, exc)
        return 0
    stop = {"the", "a", "an", "of", "and", "in", "on", "at", "with", "closeup", "close", "up"}
    words = [w for w in re.findall(r"[a-z]+", term.lower()) if w not in stop]
    needed = len(words) if len(words) <= 2 else len(words) - 1
    usable = 0
    for h in hits:
        tags = str(h.get("tags", "")).lower()
        if any(bad in tags for bad in ("green screen", "animation", "overlay", "bikini", "lingerie", "sexy")):
            continue
        if words and sum(1 for w in words if w.rstrip("s") in tags) < needed:
            continue
        if any(v.get("width", 0) >= 1080 and v.get("height", 0) >= 1920
               for v in (h.get("videos") or {}).values() if isinstance(v, dict)):
            usable += 1
    return usable


CLIPS_DIR = STATE / "clips"
_UA = {"User-Agent": "MoneyPrinterTurbo-agent/1.0 (+https://github.com/harry0703/MoneyPrinterTurbo)",
       "Accept": "application/json"}
_BAD_TAGS = ("green screen", "greenscreen", "animation", "overlay", "bikini", "lingerie",
             "underwear", "swimsuit", "sexy", "erotic", "nude", "smoking", "alcohol", "weapon")


def pixabay_search(term: str, key: str, per_page: int = 40) -> list[dict]:
    import urllib.parse
    import urllib.request

    url = "https://pixabay.com/api/videos/?" + urllib.parse.urlencode(
        {"key": key, "q": term, "video_type": "film", "safesearch": "true", "per_page": per_page})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=20) as r:
            return json.loads(r.read()).get("hits", [])
    except Exception as exc:
        log.warning("pixabay search failed for %r: %s", term, exc)
        return []


def _coverr_key() -> str:
    with open(REPO / "config.toml", "rb") as f:
        keys = tomllib.load(f).get("app", {}).get("coverr_api_keys") or []
    return keys[0] if keys else ""


def coverr_search(term: str, key: str, page_size: int = 20) -> list[dict]:
    """Coverr candidates (free tier: 50 calls/hour, so one call per scene)."""
    import urllib.parse
    import urllib.request

    url = "https://api.coverr.co/videos?" + urllib.parse.urlencode(
        {"query": term, "page_size": page_size, "urls": "true", "api_key": key})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=20) as r:
            hits = json.loads(r.read()).get("hits", [])
    except Exception as exc:
        log.warning("coverr search failed for %r: %s", term, exc)
        return []
    out = []
    for h in hits:
        url = (h.get("urls") or {}).get("mp4_download")
        try:
            duration = float(h.get("duration") or 0)
            w, hgt = int(h.get("max_width") or 0), int(h.get("max_height") or 0)
        except (TypeError, ValueError):
            continue
        if not url or duration < 3 or h.get("is_premium") or h.get("is_ai_generated"):
            continue
        if not ((w >= 1080 and hgt >= 1920) or (hgt >= 1080 and w >= 608)):
            continue
        tags = ", ".join(str(t) for t in (h.get("tags") or []))
        out.append({"id": f"coverr-{h.get('id')}", "tags": f"{h.get('title', '')}: {tags}",
                    "duration": round(duration), "url": url, "hd": w >= 1080 and hgt >= 1920})
    return out


def best_rendition(hit: dict) -> dict | None:
    """Prefer a file that fully covers 1080x1920 after a centre crop; otherwise the
    largest one that is at least 1080p tall (cropped to 608x1080 and upscaled)."""
    files = [v for v in (hit.get("videos") or {}).values()
             if isinstance(v, dict) and v.get("url") and v.get("width") and v.get("height")]
    full = [v for v in files if v["width"] >= 1080 and v["height"] >= 1920]
    if full:
        return min(full, key=lambda v: v["width"] * v["height"])
    ok = [v for v in files if v["height"] >= 1080 and v["width"] >= 608]
    return max(ok, key=lambda v: v["width"] * v["height"]) if ok else None


def _script_parts(script: str, n: int) -> list[str]:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script.strip()) if s.strip()]
    if not sentences:
        return [script] * n
    parts, size = [], max(1, round(len(sentences) / n))
    for i in range(0, len(sentences), size):
        parts.append(" ".join(sentences[i:i + size]))
    while len(parts) < n:
        parts.append(parts[-1])
    return parts[:n]


def download_clip(url: str, dest: Path, trim_seconds: float = 0, max_bytes: int = 200 * 1024 * 1024) -> bool:
    import urllib.request

    if dest.exists() and dest.stat().st_size > 0:
        return True
    tmp = dest.with_suffix(".part.mp4")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=60) as r, open(tmp, "wb") as f:
            total = 0
            while chunk := r.read(1 << 20):
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeError("clip too large")
                f.write(chunk)
        if trim_seconds > 0:
            # Keep only one cut's worth so a long clip cannot reappear later in the video.
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), "-t", f"{trim_seconds + 0.5:.1f}",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-an", str(dest)],
                           check=True, env={**os.environ, "PATH": "/opt/homebrew/bin:" + os.environ.get("PATH", "")})
            tmp.unlink(missing_ok=True)
        else:
            tmp.replace(dest)
        return True
    except Exception as exc:
        log.warning("download failed %s: %s", url, exc)
        tmp.unlink(missing_ok=True)
        return False


def curate_clips(topic: str, script: str, terms: list[str], settings: dict, per_scene: int = 2) -> list[str]:
    """Search Pixabay per scene, let Claude choose the clips that literally show that
    part of the narration, download them, return their paths in narration order."""
    key, ckey = _pixabay_key(), _coverr_key()
    if not key and not ckey:
        return []
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    rules = settings["content"].get("stock_rules", "")
    parts = _script_parts(script, len(terms))
    paths: list[str] = []
    for term, part in zip(terms, parts):
        candidates: list[dict] = []
        if ckey:  # Coverr: curated, well-tagged, mostly 4K
            candidates += coverr_search(term, ckey)
        if key:
            hits = pixabay_search(term, key)
            words = term.split()
            if len(hits) < 15 and len(words) > 1:  # broaden with the main noun
                hits += pixabay_search(words[-1], key, per_page=25)
            seen = set()
            for h in hits:
                if h.get("id") in seen or (h.get("duration") or 0) < 3:
                    continue
                tags = str(h.get("tags", "")).lower()
                if any(b in tags for b in _BAD_TAGS):
                    continue
                r = best_rendition(h)
                if not r:
                    continue
                seen.add(h["id"])
                candidates.append({"id": f"pixabay-{h['id']}", "tags": h.get("tags", ""),
                                   "duration": h.get("duration"), "url": r["url"], "hd": r["height"] >= 1920})
        already = {Path(p).stem for p in paths}  # never reuse a clip picked for an earlier scene
        candidates = [c for c in candidates
                      if c["id"] not in already and not any(b in c["tags"].lower() for b in _BAD_TAGS)]
        if not candidates:
            log.info("scene %r: no candidates", term)
            continue
        listing = "\n".join(f'{c["id"]}: {c["tags"][:160]} ({c["duration"]}s{", 4K" if c["hd"] else ""})'
                            for c in candidates[:50])
        prompt = f"""You are choosing real stock-footage clips for one part of a short video titled "{topic}".
This part of the narration: "{part}"
Search term used: "{term}"
Candidate clips (id: tags):
{listing}

Pick up to {per_scene} clips whose title/tags show something a viewer would recognise as
illustrating this narration (literally or as an obvious everyday equivalent). Prefer clips with
people in relatable everyday situations and clips marked 4K; prefer two different-looking clips.
Reject clips that are only loosely related (an unrelated animal, object, landscape or abstract
texture). {rules}
If nothing fits, return an empty list. Respond with only JSON: {{"ids": ["..."]}}"""
        try:
            ids = [str(i) for i in ask_claude_json(prompt).get("ids", [])][:per_scene]
        except Exception as exc:
            log.warning("clip selection failed for %r: %s", term, exc)
            ids = []
        by_id = {c["id"]: c for c in candidates}
        picked = [by_id[i] for i in ids if i in by_id]
        log.info("scene %r: %d candidates -> %s", term, len(candidates),
                 [c["tags"][:40] for c in picked] or "none")
        for c in picked:
            dest = CLIPS_DIR / f"{c['id']}.mp4"
            if download_clip(c["url"], dest, trim_seconds=float(settings["video"].get("clip_duration", 4))):
                paths.append(str(dest))
    return paths


def validate_terms(terms: list[str], topic: str, settings: dict, minimum: int = 2) -> list[str]:
    """Replace search terms that Pixabay cannot serve with workable alternatives."""
    key = _pixabay_key()
    if not key or settings["video"]["source"] != "pixabay":
        return terms
    rules = settings["content"].get("stock_rules", "")
    out = []
    for term in terms:
        if pixabay_usable_hits(term, key) >= minimum:
            out.append(term)
            continue
        prompt = f"""The stock-footage search "{term}" (for a video titled "{topic}") returned nothing on Pixabay.
Give 4 alternative search terms for the same visual idea, from most specific to most generic,
each 1-2 common English words that a stock site surely has (e.g. "sneakers", "basketball",
"students", "family", "walking"). {rules}
Respond with only JSON: {{"terms": ["...", "...", "...", "..."]}}"""
        chosen = None
        try:
            for alt in ask_claude_json(prompt).get("terms", []):
                alt = str(alt).strip().replace(",", " ")
                if alt and pixabay_usable_hits(alt, key) >= minimum:
                    chosen = alt
                    break
        except Exception as exc:
            log.warning("alternate term lookup failed for %r: %s", term, exc)
        log.info("term %r -> %r", term, chosen or "(dropped)")
        if chosen:
            out.append(chosen)
    return out or ["teenagers", "students", "family"]


def pick_search_terms(topic: str, script: str, settings: dict) -> list[str]:
    """Stock-footage search terms, one per part of the narration, in order."""
    count = int(settings["video"].get("scene_count", 8))
    rules = settings["content"].get("stock_rules", "")
    prompt = f"""A short video titled "{topic}" has this narration:
{script}

Split the narration into {count} consecutive parts and give ONE stock-footage search term
for each part, in order, so the clips follow the story. Each term is 1-3 plain English words
naming something literally visible that Pexels has many real clips of: people doing everyday
things, places, objects, close-ups, nature (e.g. "teenager sleeping", "alarm clock", "school
hallway", "washing face", "friends laughing", "city sunrise", "doctor talking"). Prefer human,
relatable scenes; vary subjects; no metaphors, no abstract ideas, no numbers, no text on screen,
no medical diagrams. {rules}
Respond with only JSON: {{"terms": ["...", "..."]}}"""
    terms = [str(t).strip().replace(",", " ") for t in ask_claude_json(prompt).get("terms", [])]
    return [t for t in terms if t][:count]


def write_metadata(topic: str, script: str, settings: dict | None = None) -> dict:
    c = (settings or load_settings())["content"]
    prompt = f"""Write social media metadata for a short vertical video on a {c['niche']} channel.
Topic: {topic}
Narration: {script}

Return only JSON with these keys:
- "headline": the on-screen opening text, 2-5 words, the single most surprising number or
  phrase, e.g. "1 DAY OLD", "3,000 YEAR OLD HONEY", "RAINS GLASS SIDEWAYS". No punctuation.
- "youtube_title": catchy, accurate, at most 80 characters, no hashtags, no clickbait lies
- "youtube_description": 2 short sentences summarising the fact, then a blank line, then "#Shorts" plus 3 relevant hashtags
- "tags": 8 plain keyword tags (no # symbol)
- "tiktok_caption": at most 110 characters, written like these viral examples: a formula or
  punchline stating the surprising fact plainly, ending with 1-2 fitting emoji.
  Examples: "Sticky tape + a pencil = a Nobel Prize 🐘✏️", "Whale vomit → $1.5 million 🐋💰",
  "You can pull your own DNA out of a glass of spit 🧬". No hashtags, no questions.
- "hashtags": 4 relevant hashtags without the # symbol, single words, e.g. "sciencefacts"
{c.get('caption_rules', 'Everything must comply with platform rules: no innuendo, no shaming, no medical claims beyond "talk to a doctor".')}
"""
    data = ask_claude_json(prompt)
    data["headline"] = re.sub(r"[^\w\s,'%$-]", "", str(data.get("headline") or topic)).strip()[:40]
    data["youtube_title"] = str(data.get("youtube_title") or topic)[:100]
    data["youtube_description"] = str(data.get("youtube_description") or f"{topic}\n\n#Shorts")
    data["tags"] = [str(t) for t in data.get("tags", [])][:15]
    data["tiktok_caption"] = str(data.get("tiktok_caption") or topic)[:150]
    data["hashtags"] = [re.sub(r"[^\w]", "", str(t)) for t in data.get("hashtags", [])][:5]
    data["hashtags"] = [t for t in data["hashtags"] if t] or ["sciencefacts", "funfacts", "learnontiktok"]
    return data


# --------------------------------------------------------------------------- video


def generate_video(settings: dict, topic: str, script: str | None = None) -> dict:
    v = settings["video"]
    cmd = [
        str(REPO / ".venv/bin/python"),
        "cli.py",
        "--video-subject", topic,
        "--video-language", settings["content"]["language"],
        "--video-script-prompt", settings["content"]["script_requirements"],
        "--video-clip-duration", str(v.get("clip_duration", 4)),
        "--voice-name", v["voice"],
        "--video-aspect", "9:16",
        "--subtitle-display-mode",
        "word_by_word" if v.get("subtitle_display_mode") == "phrase" else v.get("subtitle_display_mode", "sentence"),
        "--subtitle-animation", v.get("subtitle_animation", "none"),
        "--subtitle-position", v.get("subtitle_position", "bottom"),
        *(["--custom-position", str(v.get("subtitle_custom_position", 70))]
          if v.get("subtitle_position") == "custom" else []),
        "--font-name", v.get("font_name", "MicrosoftYaHeiBold.ttc"),
        "--font-size", str(v.get("font_size", 60)),
        "--text-fore-color", v.get("text_color", "#FFFFFF"),
        "--stroke-color", v.get("stroke_color", "#000000"),
        "--stroke-width", str(v.get("stroke_width", 1.5)),
    ]
    if script:
        cmd += ["--video-script", script]
    source_args = ["--video-source", v["source"], "--match-materials-to-script"]
    try:
        if v["source"] == "openai_image":
            ensure_image_server(v.get("image_style", "photo"))
            scenes = pick_scene_prompts(topic, settings)
            log.info("Scenes: %s", " | ".join(scenes))
            source_args += ["--video-terms", ",".join(scenes)]
        elif script:
            terms = pick_search_terms(topic, script, settings)
            log.info("Footage search terms: %s", ", ".join(terms))
            clips = curate_clips(topic, script, terms, settings) if v["source"] == "pixabay" else []
            if len(clips) >= 4:
                # Hand-picked clips in narration order, played sequentially.
                log.info("Using %d curated clips", len(clips))
                source_args = ["--video-source", "local", "--video-materials", ",".join(clips),
                               "--video-concat-mode", "sequential"]
            else:
                log.warning("Only %d curated clips; falling back to provider search", len(clips))
                source_args += ["--video-terms", ",".join(validate_terms(terms, topic, settings))]
    except Exception as exc:  # fall back to MoneyPrinterTurbo's own terms
        log.warning("Could not pick footage (%s); using provider defaults", exc)
    cmd += source_args
    env = _clean_env()
    env["PATH"] = f"{Path.home()}/.local/bin:/opt/homebrew/bin:" + env.get("PATH", "/usr/bin:/bin")
    if v.get("subtitle_display_mode") == "phrase":
        env["MPT_SUBTITLE_PHRASE_WORDS"] = str(v.get("phrase_words", 3))
    last_err = ""
    for attempt in range(1, 4):  # Edge TTS and stock APIs are occasionally flaky
        log.info("Generating video (attempt %d): %s", attempt, topic)
        proc = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=1800)
        with open(LOGS / "moneyprinter.log", "a") as f:
            f.write(f"\n===== {datetime.now():%F %T} {topic} (attempt {attempt}) =====\n")
            f.write(proc.stderr[-20000:])
        for line in reversed(proc.stdout.splitlines()):
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                videos = data.get("result", {}).get("videos") or []
                if proc.returncode == 0 and videos and Path(videos[0]).exists():
                    return {"task_id": data["task_id"], "video": videos[0],
                            "script": data["result"].get("script", "")}
        last_err = (proc.stderr.strip().splitlines() or ["unknown error"])[-1]
        log.warning("Video generation failed: %s", last_err)
        time.sleep(30)
    raise RuntimeError(f"video generation failed: {last_err}")


def add_headline(video_path: str, headline: str, seconds: float = 2.8) -> str:
    """Burn a big headline over the opening seconds; returns the new file path."""
    from PIL import Image, ImageDraw, ImageFont

    font_path = REPO / "resource/fonts/BeVietnamPro-Bold.ttf"
    W, H = 1080, 1920
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    words = headline.upper().split()
    size = 120 if len(headline) <= 16 else 100
    font = ImageFont.truetype(str(font_path), size)
    lines, line = [], ""
    for w in words:  # wrap to the frame width with a 70px margin each side
        trial = f"{line} {w}".strip()
        if draw.textlength(trial, font=font) > W - 140 and line:
            lines.append(line)
            line = w
        else:
            line = trial
    lines.append(line)
    y = int(H * 0.17)
    for text in lines[:3]:
        x = (W - draw.textlength(text, font=font)) / 2
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 255),
                  stroke_width=8, stroke_fill=(0, 0, 0, 255))
        y += int(size * 1.2)
    png = Path(video_path).with_name("headline.png")
    overlay.save(png)
    out = Path(video_path).with_name("final-headline.mp4")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", video_path, "-i", str(png),
         "-filter_complex", f"[0:v][1:v]overlay=0:0:enable='between(t,0,{seconds})'",
         "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "copy", "-movflags", "+faststart", str(out)],
        check=True, env={**os.environ, "PATH": "/opt/homebrew/bin:" + os.environ.get("PATH", "")},
    )
    return str(out)


# --------------------------------------------------------------------------- posting


def post_youtube(settings: dict, entry: dict) -> None:
    import youtube_uploader as yu

    y = settings["youtube"]
    creds = yu.get_credentials(SECRETS)
    m = entry["metadata"]
    result = yu.upload(
        creds, entry["video"], m["youtube_title"], m["youtube_description"], m["tags"],
        category_id=y.get("category_id", "28"), privacy=y.get("privacy", "public"),
        made_for_kids=y.get("made_for_kids", False),
    )
    if result["privacy"] != result["requested_privacy"]:
        log.warning("YouTube set privacy to %s (requested %s) - the Google project may need an audit",
                    result["privacy"], result["requested_privacy"])
    entry["youtube"] = {"status": "posted", **result}
    log.info("YouTube posted: %s (%s)", result["url"], result["privacy"])


def post_tiktok(settings: dict, entry: dict, dry_run: bool = False) -> None:
    import tiktok_uploader as tu

    m = entry["metadata"]
    result = tu.upload(
        entry["video"], m["tiktok_caption"], m["hashtags"], TIKTOK_PROFILE,
        headless=settings["tiktok"].get("headless", False), post=not dry_run, shot_dir=LOGS,
    )
    entry["tiktok"] = {"status": result["status"], "screenshot": result.get("screenshot")}
    log.info("TikTok %s", result["status"])


PLATFORMS = {"youtube": post_youtube, "tiktok": post_tiktok}


def try_post(platform: str, settings: dict, entry: dict, history: list[dict], **kw) -> bool:
    state = entry.setdefault(platform, {"status": "pending", "attempts": 0})
    state["attempts"] = state.get("attempts", 0) + 1
    try:
        PLATFORMS[platform](settings, entry, **kw)
        entry[platform]["attempts"] = state["attempts"]
        return True
    except Exception as exc:
        entry[platform] = {"status": "failed", "attempts": state["attempts"], "error": str(exc)[:500]}
        log.error("%s upload failed: %s", platform, exc)
        notify(f"{platform} upload failed: {str(exc)[:120]}")
        return False
    finally:
        save_history(history)


def retry_failed_uploads(settings: dict, history: list[dict], skip: set[str]) -> None:
    cutoff = datetime.now() - timedelta(days=2)
    max_attempts = settings["housekeeping"].get("max_upload_attempts", 3)
    for entry in history:
        if datetime.fromisoformat(entry["created"]) < cutoff or not Path(entry.get("video", "")).exists():
            continue
        for platform in PLATFORMS:
            st = entry.get(platform)
            if (platform not in skip and settings[platform].get("enabled")
                    and st and st.get("status") in ("failed", "pending")
                    and st.get("attempts", 0) < max_attempts):
                log.info("Retrying %s upload for earlier video: %s", platform, entry["topic"])
                try_post(platform, settings, entry, history)


# --------------------------------------------------------------------------- housekeeping


def cleanup(settings: dict, history: list[dict]) -> None:
    keep_days = settings["housekeeping"].get("keep_days", 7)
    cutoff = time.time() - keep_days * 86400
    in_use = {Path(h["video"]).parent for h in history
              if any((h.get(p) or {}).get("status") in ("failed", "pending") for p in PLATFORMS)}
    removed = 0
    for folder in (REPO / "storage/tasks", REPO / "storage/cache_videos", CLIPS_DIR):
        if not folder.exists():
            continue
        for item in folder.iterdir():
            if item in in_use or item.stat().st_mtime > cutoff:
                continue
            shutil.rmtree(item) if item.is_dir() else item.unlink()
            removed += 1
    if removed:
        log.info("Cleanup removed %d old task folders/clips", removed)


# --------------------------------------------------------------------------- commands


def cmd_run(args) -> int:
    settings = load_settings()
    lock = open(STATE / "agent.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.warning("Another run is in progress; exiting")
        return 0

    history = load_history()
    skip = {p for p in PLATFORMS if getattr(args, f"no_{p}")}
    retry_failed_uploads(settings, history, skip)

    today = datetime.now().date().isoformat()
    made_today = sum(1 for h in history if h["created"].startswith(today) and h.get("video"))
    if made_today >= settings["schedule"].get("max_videos_per_day", 1) and not args.force:
        log.info("Already made %d video(s) today; skipping (use --force to override)", made_today)
        return 0

    try:
        entry = None
        for attempt in range(3):
            topic = args.topic or pick_topic(settings, history)
            log.info("Topic: %s", topic)
            script = write_script(topic, settings)
            metadata = write_metadata(topic, script, settings)
            ok, reason = safety_check(topic, script, metadata, settings)
            if not ok and reason:
                # One revision pass: reviews often come with a concrete fix.
                log.info("Safety review asked for changes; revising script once (%s)", reason[:160])
                script = write_script(topic, settings, revision_note=reason)
                metadata = write_metadata(topic, script, settings)
                ok, reason = safety_check(topic, script, metadata, settings)
            if ok:
                entry = {"created": datetime.now().isoformat(timespec="seconds"),
                         "topic": topic, "script": script, "metadata": metadata}
                break
            log.warning("Safety review rejected this script (%s); trying another topic", reason)
            history.append({"created": datetime.now().isoformat(timespec="seconds"), "topic": topic,
                            "note": f"rejected by safety review: {reason}"})
            save_history(history)
            if args.topic:
                break
        if entry is None:
            raise RuntimeError("no script passed the safety review")
        entry.update(generate_video(settings, topic, script=entry["script"]))
        if settings["video"].get("headline_enabled", True):
            try:
                entry["video"] = add_headline(
                    entry["video"], entry["metadata"]["headline"],
                    float(settings["video"].get("headline_seconds", 2.8)),
                )
            except Exception as exc:
                log.warning("Headline overlay failed (%s); posting without it", exc)
        history.append(entry)
        save_history(history)
        log.info("Video ready: %s", entry["video"])
    except Exception as exc:
        log.exception("Run failed before posting")
        notify(f"Video generation failed: {str(exc)[:150]}")
        return 1

    ok = True
    if settings["youtube"].get("enabled") and "youtube" not in skip:
        ok &= try_post("youtube", settings, entry, history)
    if settings["tiktok"].get("enabled") and "tiktok" not in skip:
        ok &= try_post("tiktok", settings, entry, history, dry_run=args.tiktok_dry_run)

    cleanup(settings, history)
    if ok:
        notify(f"Posted: {entry['metadata']['youtube_title']}")
    return 0 if ok else 2


def cmd_youtube_auth(_args) -> int:
    import youtube_uploader as yu

    creds = yu.get_credentials(SECRETS, interactive=True)
    print(f"YouTube authorized for channel: {yu.channel_title(creds)}")
    return 0


def cmd_tiktok_login(_args) -> int:
    import tiktok_uploader as tu

    ok = tu.login(TIKTOK_PROFILE)
    print("TikTok session saved." if ok else "Timed out waiting for TikTok login.")
    return 0 if ok else 1


def cmd_install_schedule(_args) -> int:
    settings = load_settings()
    intervals = []
    for t in settings["schedule"]["times"]:
        hour, minute = (int(x) for x in t.split(":"))
        intervals.append({"Hour": hour, "Minute": minute})
    plist = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [str(HERE / ".venv/bin/python"), str(HERE / "agent.py"), "run"],
        "WorkingDirectory": str(HERE),
        "EnvironmentVariables": {
            "PATH": f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONUNBUFFERED": "1",
        },
        "StartCalendarInterval": intervals,
        "StandardOutPath": str(LOGS / "launchd.out.log"),
        "StandardErrorPath": str(LOGS / "launchd.err.log"),
    }
    awake = {
        "Label": AWAKE_LABEL,
        "ProgramArguments": ["/usr/bin/caffeinate", "-s", "-i"],
        "RunAtLoad": True,
        "KeepAlive": True,
    }
    LAUNCHD_PLIST.parent.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    for label, path, data in ((LAUNCHD_LABEL, LAUNCHD_PLIST, plist), (AWAKE_LABEL, AWAKE_PLIST, awake)):
        with open(path, "wb") as f:
            plistlib.dump(data, f)
        subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True)
        res = subprocess.run(["launchctl", "bootstrap", domain, str(path)], capture_output=True, text=True)
        if res.returncode != 0:
            print(f"launchctl bootstrap failed for {label}: {res.stderr}")
            return 1
    print(f"Scheduled daily at {', '.join(settings['schedule']['times'])} ({LAUNCHD_PLIST})")
    print("Keep-awake agent installed (caffeinate -s -i).")
    return 0


def cmd_uninstall_schedule(_args) -> int:
    for label, path in ((LAUNCHD_LABEL, LAUNCHD_PLIST), (AWAKE_LABEL, AWAKE_PLIST)):
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"], capture_output=True)
        path.unlink(missing_ok=True)
    print("Schedule and keep-awake agent removed.")
    return 0


def cmd_status(_args) -> int:
    print(f"YouTube token:   {'yes' if (SECRETS / 'youtube_token.json').exists() else 'NO - run youtube-auth'}")
    print(f"TikTok profile:  {'yes' if TIKTOK_PROFILE.exists() else 'NO - run tiktok-login'}")
    print(f"Schedule:        {'installed' if LAUNCHD_PLIST.exists() else 'not installed'}")
    for h in load_history()[-10:]:
        yt = (h.get("youtube") or {}).get("status", "-")
        tt = (h.get("tiktok") or {}).get("status", "-")
        print(f"{h['created']}  yt={yt:<8} tiktok={tt:<8} {h['topic']}")
    return 0


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--topic")
    run.add_argument("--force", action="store_true", help="ignore the daily cap")
    run.add_argument("--no-youtube", action="store_true")
    run.add_argument("--no-tiktok", action="store_true")
    run.add_argument("--tiktok-dry-run", action="store_true", help="fill the TikTok form but don't click Post")
    run.set_defaults(func=cmd_run)
    for name, func in [("youtube-auth", cmd_youtube_auth), ("tiktok-login", cmd_tiktok_login),
                       ("install-schedule", cmd_install_schedule),
                       ("uninstall-schedule", cmd_uninstall_schedule), ("status", cmd_status)]:
        sub.add_parser(name).set_defaults(func=func)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
