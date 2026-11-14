# Script to Short: talking-character Shorts pipeline

Turn a rough script into a **1-minute cinematic vertical Short** where **your own 2D cartoon character** talks it to camera. The Short gets lip-sync, gestures, camera moves, live captions and sound design, then posts to **YouTube Shorts** (and optionally **Instagram Reels**) with titles, tags and hashtags written for reach.

It runs inside [Claude Code](https://claude.com/claude-code) as a set of skills. You type:

```
/script-to-short <your rough script>
```

Claude develops the script, directs the shots, renders, checks the frames, fixes problems, writes the metadata and publishes. Everything renders locally on your CPU with free tools, so no GPU is needed. You make the character art yourself in an image generator of your choice, and the voice comes from edge-tts, an unofficial Microsoft endpoint with no service guarantee.

> This folder is self-contained and independent of MoneyPrinterTurbo's app: it has its own `.venv`, config and requirements, and imports nothing from `app/`. Where MoneyPrinterTurbo assembles stock footage, this pipeline performs your script with a recurring character.

## What you get per video

- **Script:** developed from your draft. The hook comes in the first second, there's a twist every 10–15 s, a call to action, and a last line that loops back into the opening. It's timed to 56–60 s.
- **Voice:** a free neural voice (edge-tts) with **hype / normal / sarcastic** delivery per line, given a husky bass treatment.
- **Lip-sync:** mouth shapes come from the audio ([Rhubarb Lip Sync](https://github.com/DanielSWolf/rhubarb-lip-sync)), drawn onto your character at every pose's scale.
- **Camera:** shots range from wide to extreme close-up, with eased push-ins, faces placed on a third, tele lens, rack focus, dutch angles and depth of field. Aspect ratios switch for effect (2.39 letterbox reveals, a 4:3 camcorder look).
- **Edit:** hard cuts with a few motivated transitions (whip, zoom, glitch, fade).
- **Captions:** bold word-by-word captions with a highlighted active word, and giant tilted words for emphasis.
- **Sound design:** the music ducks under speech, plus drops, booms, whooshes, risers and record scratches (all synthesized).
- **Export:** 1080×1920, 30 fps, H.264 High, AAC 384k, −14 LUFS, valid for both Shorts and Reels.
- **Metadata and publishing:** title, description, tags, category, Instagram caption and cover frame, published at the same daily slot.

## Requirements

- Claude Code
- Python 3.10+
- Git
- About 2 GB of disk

Developed and tested on Windows only. The code has macOS and Linux paths (font lookup, Rhubarb download, venv layout) but they have not been exercised.

## Setup (one time, about 45 minutes)

### 1. Install

From the root of a MoneyPrinterTurbo checkout:

```bash
cd contrib/script-to-short
python install.py
```

All paths below are relative to `contrib/script-to-short/`.

`install.py` does the following:
- creates `.venv` and installs the requirements
- downloads Rhubarb into `tools/`
- creates `config.json`
- installs the 4 skills into `~/.claude/skills/`, pointing at this folder
- runs the self-tests

It never overwrites a skill of the same name you already have unless you pass `--force`.

### 2. Fill in `config.json`

| Key | What to put |
|---|---|
| `creator_name` / `creator_name_spoken` | Your on-screen name and how the voice should say it. For initials, use `"AJ"` and `"A J"`. The video always pauses after your name. |
| `youtube_channel` | Your channel handle, e.g. `@my_channel`. The uploader refuses any other channel. |
| `instagram_account` | Your Instagram username, or empty to skip Instagram. |
| `voice` | Any edge-tts voice. List them with `.venv/Scripts/python -m edge_tts --list-voices` (on Windows; `.venv/bin/python` elsewhere). |
| `music` | Optional royalty-free track, e.g. from the YouTube Audio Library, saved under `my/music/`. |
| `publish_time` / `utc_offset` | Your daily slot, e.g. `"18:30"` and `"+05:30"`. |
| `auto_publish` | `false` means Claude asks before every upload. Set `true` once you trust it. |
| `channel_style` | One line about your tone, so scripts sound like you. |

### 3. Your character

Everything under `my/` is yours and is git-ignored.

1. **Character sheet:** `my/sheet.png`, one image with the character twice. The **closed mouth** figure goes on the left and the **open mouth** (mid-word) figure on the right, front-facing, on a plain background.
2. **Calibration:** copy `my/sheet.example.json` to `my/sheet.json` and set the pixel boxes for your sheet. Every field is explained inside the file; any image editor that shows cursor x,y works. Then check it:
   ```bash
   .venv/Scripts/python skills/anime-talking-short/scripts/build_poses.py --check my/sheet.png
   ```
   Open `my/sheet-check.png`:
   - the red box frames the closed figure
   - the yellow box frames its mouth area
   - the cyan dot sits on the lip line
   - the green box frames the open mouth
   - the magenta dot sits inside the open mouth
3. **Poses:** generate gesture poses with an image generator that can follow a reference. Attach the closed-mouth figure and ask for each pose, for example:
   > Same character, same outfit and art style, waist-up, front-facing, **pointing at the camera**, **closed mouth with neutral lips**, on a **plain flat #00FF00 green background**, vertical 9:16, no text.

   Good starter set:
   | Pose | Use |
   |---|---|
   | `rest` | neutral lines |
   | `point` | "you" |
   | `shrug` | sarcasm |
   | `facepalm` | fails |
   | `crossed` | attitude (arms crossed) |
   | `think` | questions |
   | `explain` | lists (open hands) |
   | `thumbsup` | calls to action |

   Save each as `my/poses/<name>.png`; the file name becomes the pose name.
4. **Backgrounds:** 2–4 vertical 9:16 illustrated sets in the same style, with no people, e.g. a neon bedroom studio, a rooftop at dusk, a corridor. Save them as `my/backgrounds/<name>.png`.
5. **Build:**
   ```bash
   .venv/Scripts/python skills/anime-talking-short/scripts/build_poses.py my/sheet.png my/poses my/backgrounds my/built
   ```
   Each pose prints a mouth score. Below 0.45 means the mouth wasn't found, so that pose plays without lip-sync (fine for a facepalm). Otherwise, regenerate it with the mouth clearly visible.

### 4. YouTube login (OAuth; no password is ever stored)

1. At [console.cloud.google.com](https://console.cloud.google.com), create a project and enable **YouTube Data API v3**.
2. Open the **OAuth consent screen**, choose External, and add your Google account under **Test users**.
3. Open **Credentials** → OAuth client ID → **Desktop app**. Download the JSON to `~/.youtube-upload/client_secret.json`.
4. Run `.venv/Scripts/python skills/youtube-upload/scripts/upload.py --auth-only` and pick your channel in the browser.

The token is saved in `~/.youtube-upload/`, outside the repo. Videos from an unverified Google project may be forced to private; switch them to Public in YouTube Studio or apply for Google's API audit.

### 5. Instagram (optional)

Your account must be a **Creator or Business** account. No Facebook Page is needed.

1. At [developers.facebook.com](https://developers.facebook.com), create an app with the use case **"Manage messaging & content on Instagram"**.
2. Open Use cases → Customize → **API setup with Unified login**. Connect a **business portfolio** (free), then **create the configuration**. Pick a token that never expires.
3. Open App roles → Roles → Add people → **Instagram Tester** and enter your username. Accept the invite in the Instagram app: Settings → Website permissions → Apps and websites → Tester invites.
4. In **Generate access tokens**, click **Generate token** and paste it into `~/.instagram-upload/token.txt` yourself.
5. Check: `.venv/Scripts/python skills/instagram-upload/scripts/upload.py --account <username> --check`

Instagram's API can't schedule posts. For a future slot, Claude uploads early and publishes at the slot, so keep Claude Code open until then.

### 6. Go

Restart Claude Code, then:

```
/script-to-short my rough take on why everyone quits the gym in February ...
```

## How it works

```
rough script -> develop (hook, ~185 words, loop ending) -> direct (screenplay tags)
  -> [new poses/sets if needed] -> render (voice, lip-sync, camera, captions, sound, encode)
  -> review frames -> fix -> metadata -> YouTube + Instagram at your slot -> report
```

| Skill | Job |
|---|---|
| `script-to-short` | The daily routine; reads `config.json` and chains the others |
| `anime-talking-short` | `render.py` (screenplay → video), `sound.py` (mix and SFX), `build_poses.py` (art → poses) |
| `youtube-upload` | YouTube Data API v3 upload with a channel check and scheduling |
| `instagram-upload` | Instagram API (Unified Login) Reel publishing with an account check |

The screenplay format (shots, tones, sound cues, emphasis) is documented in `skills/anime-talking-short/SKILL.md` and at the top of `render.py`. You can render by hand too:

```bash
.venv/Scripts/python skills/anime-talking-short/scripts/render.py --script jobs/demo/script.txt --out jobs/demo/short.mp4
```

## Privacy and safety

- **Never committed:** your details (`config.json`), art (`my/`), videos (`jobs/`, `reels/`) and logins are all in `.gitignore`.
- **Logins live outside the repo** in `~/.youtube-upload/` and `~/.instagram-upload/`, and are only ever OAuth or dashboard tokens, never passwords.
- **Account checks:** the uploaders refuse to post if the login belongs to a different channel or account than `config.json` names.
- **No deleting:** nothing deletes videos, so Claude asks before re-posting a video that's already live.

## Monetization notes

- YouTube pays only for **original** content. Write a new idea every day in your own voice, and don't mass-produce near-identical videos.
- The YouTube Partner Program needs 1,000 subscribers plus 10 million Shorts views in 90 days, or 4,000 watch hours.
- A clearly cartoon character doesn't need an altered-content label. Never imitate real people.

## Limits

- Rendering takes about 5–6 minutes per minute of video on a laptop CPU.
- Character poses are still images with swapped mouths: no blinking, and no motion within a pose; the camera and cuts carry the energy.
- The free edge-tts voice service occasionally refuses requests; the renderer retries 8 times.
- The Instagram uploader has had far less real-world use than the YouTube one. Check the first Reel it posts.
- The sheet calibration is manual (about 10 minutes, once per character).

## License

MIT, same as the rest of this repository. Third-party tools keep their own licenses: edge-tts, Rhubarb Lip Sync and FFmpeg via imageio-ffmpeg.
