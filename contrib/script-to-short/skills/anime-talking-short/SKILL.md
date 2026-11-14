---
name: anime-talking-short
description: Render a cinematic vertical 9:16 Short/Reel from a screenplay where a 2D cartoon character performs the script with gesture poses on illustrated sets, lip-sync from the audio (Rhubarb), voice with highs and lows per line (hype/sarcastic) and a husky bass treatment, shot sizes from wide to extreme close-up with eased push-ins, dutch angles, aspect-ratio changes (2.39 letterbox, 4:3 camcorder look), whip/zoom/glitch/fade transitions, depth of field and parallax, live word captions and a designed sound mix (ducked music, drops, booms, whooshes, risers). Use whenever the user wants a talking-character / VTuber / anime-narrator video from a script, or wants to change its shots, edit, voice, sound, poses or lip-sync. For the full script-to-YouTube pipeline use script-to-short.
---

# Anime talking short

`scripts/render.py` makes the video from a screenplay (the script text plus direction tags). It runs on the processor and takes about 5–6 minutes per minute of video. The output is at YouTube Shorts and Instagram Reels upload quality: 1080x1920 30 fps, H.264 High (crf 17, closed GOP), AAC 384k 48 kHz, -14 LUFS. It uses the repo's `.venv` (made by `install.py`).

```bash
PY={{PY}}
R={{REPO}}/skills/anime-talking-short/scripts/render.py
$PY $R --script script.txt --out short.mp4 --dry          # voice only: prints the spoken length
$PY $R --script script.txt --out short.mp4 --music <config.json music>
```

## Screenplay tags

These are listed at the top of render.py. Any tag except pause and tone starts a new spoken segment, so put tags at sentence boundaries.

| Tag | Effect |
|---|---|
| `[pause 1.0]` | Silence after this sentence. |
| `{AJ=A J}` | The caption shows "AJ" while the voice says "A J". Use it for the creator's name (from config.json) and words the voice gets wrong. |
| `[normal]` `[hype]` `[sarcastic]` | Delivery from here on. Hype is faster and higher; sarcastic is slower and lower. |
| `[shot frame=… move=… pose=… bg=… aspect=… tilt=… in=… look=…]` | A new shot at the next sentence. `frame`, `pose`, `bg`, `aspect` and `look` carry over to later shots; `move`, `tilt` and `in` apply to that shot only. |
| `[sfx whoosh boom riser hit pop tick scratch glitch beep]` | Sound at the next sentence. A riser ends there instead of starting there. |
| `[drop]` | The music cuts out in the gap before the next sentence and slams back with a boom. |
| `*word*` | Emphasis: a giant tilted accent caption for that word, and a camera punch-in held to the end of the sentence. Use 6–10 per minute, on the word that carries the joke or the point. |

**Shot values:**
- `frame` / `move`: `wide`, `med` (chest up), `cu` (face), `ecu` (eyes to mouth). `move` pushes the camera from `frame` to that size over the shot.
- `aspect`: `9:16`, `4:5`, `1:1`, `4:3`, `2.39`. The black bars glide in, and captions move into the bottom bar.
- `in`: `cut` (default), `whip`, `zoom`, `glitch`, `fade`. Each gets a matching sound automatically.
- `look`: `clean` or `cam` (camcorder: REC dot, timecode, grain).
- `tilt`: a dutch angle in degrees. It creeps a little during the shot.
- `side`: `left` or `right` puts the face on a third, with open space on the other side. Default is centred.
- `lens`: `tele` isolates the subject: the set looms larger and softer behind him.
- `focus`: `pull` racks focus at the start of the shot, from the set to him. Use it when arriving at a new location.
- Every shot without a `move` creeps in slowly (a dolly), and a soft light follows his face.

## Directing guide (what makes it cinematic, not busy)

- **Pacing:** change the shot every sentence (2–4 s). Random transitions read as amateur, so use hard cuts by default and only about 4 transitions a minute, each motivated (fade in, whip on a location and energy change, glitch for the camcorder beat, zoom into the final reveal). No flashes.
- **Coverage like a two-camera shoot:** alternate an A-cam (`med`, centred, normal lens) with a B-cam (`cu`, `side=left|right`, `lens=tele`). Flip the side between consecutive B-cam shots. Use `ecu` plus `lens=tele` for the sharpest beats.
- **Opening:** start with `in=fade focus=pull` on `frame=wide move=med`, which is the "normal shot to portrait shot" move. Then cut to `cu` on the hook.
- **Delivery and camera together:** sarcastic lines get `[sarcastic]` plus `ecu` or `tilt=±4–6`, often with `[sfx scratch]` right before. Hype lines get `[hype]` plus `point` or `explain` poses and a `whip` or `zoom`.
- **Reveals:** a name or punchline gets `[sfx riser]`, then `aspect=2.39` on `cu move=ecu`, then `[pause]`, then `[drop]` before the next line.
- **Talking about filming:** use `look=cam aspect=4:3`. Reset with `look=clean aspect=9:16` afterwards.
- **Poses:** pick each shot's pose for meaning, never at random:

  | Pose | Use it for |
  |---|---|
  | `point` | "you" |
  | `shrug` | sarcasm or "whatever" |
  | `facepalm` | a fail; the mouth is hidden, so there's no lip-sync |
  | `crossed` | attitude |
  | `think` | questions |
  | `explain` | lists |
  | `thumbsup` | calls to action |
  | `rest` | neutral lines |

- **Change the pose only on a cut.** A pose cannot change inside a shot.
- **Sets:** move between 3–4 backgrounds so the video feels like several locations.

## Assets (`--char`, default `{{REPO}}/my/built`)

```
poses/<name>/X.png, B..F.png, pose.json    one folder per pose, made by build_poses.py
backgrounds/<name>.png                     1440x2560 stage size
```

Make the images with any image generator that can keep a character consistent from a reference (the user runs the generator themselves; never log in to, or enter credentials for, any account on their behalf). Attach the closed-mouth figure from the user's sheet and ask, for each pose: the same character, waist-up, the gesture, **closed mouth with neutral lips**, on a **plain #00FF00 green background**, vertical 9:16. Backgrounds: vertical 9:16 illustrated sets in the same art style, no people. Save poses as `{{REPO}}/my/poses/<pose>.jpg|png` and sets as `{{REPO}}/my/backgrounds/<set>.jpg|png`; the file name becomes the tag value (`pose=point`, `bg=room`). Rebuild whenever images change:

```bash
$PY {{REPO}}/skills/anime-talking-short/scripts/build_poses.py --check {{REPO}}/my/sheet.png      # once: verify the calibration boxes
$PY {{REPO}}/skills/anime-talking-short/scripts/build_poses.py {{REPO}}/my/sheet.png {{REPO}}/my/poses {{REPO}}/my/backgrounds {{REPO}}/my/built
```

- **Poses:** images on flat green. The importer removes the green background, finds the mouth by matching the sheet's mouth area (`TPL` in `my/sheet.json`) at any size, erases the lips, and draws five mouth shapes cut from the sheet's open-mouth art at that pose's scale.
- **Hidden mouth:** a pose scoring below 0.45 (a hand over the mouth, for example) gets no lip-sync, and its face position is only a guess.
- **The sheet:** a two-figure sheet of the character, closed mouth on the left and open mouth on the right. Its pixel calibration lives in `my/sheet.json` (template: `my/sheet.example.json`); `--check` draws it on the sheet for review.
- **Check:** after building, view the mouths of a pose pasted on a bright background.

## Sound (`scripts/sound.py`)

- **Voice:** husky bass treatment (low shelf, warmth, presence, compression, soft saturation). The voice itself is `voice` in config.json.
- **Music:** ducks under speech and swells in gaps, with drops.
- **SFX:** synthesized, so no sample files are needed.
- **Level:** the final mix is loudness-normalized to -14 LUFS, the Shorts and Reels target.

## Checks

- `--selftest` checks the tag parsing, the shot plan and the caption logic. `sound.py` has its own self-test.
- For a preview, tile a few frames with the venv's ffmpeg (`imageio_ffmpeg.get_ffmpeg_exe()`): `-vf "select='eq(n\,30)+eq(n\,300)',scale=270:480,tile=6x1" -frames:v 1 -fps_mode vfr sheet.png`.
- `timeline.json`, next to the video, holds the words, the mouth shape of every frame and the shots.
- The voice service sometimes returns no audio. The script retries up to 8 times by itself.
- **Lip sync:** Rhubarb lives in `{{REPO}}/tools/rhubarb/` (installed by `install.py`). Without it, mouth shapes fall back to spelling rules.
