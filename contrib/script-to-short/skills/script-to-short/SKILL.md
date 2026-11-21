---
name: script-to-short
description: Daily content routine. Turn a rough script into a polished 1-minute cinematic vertical Short where the user's own 2D cartoon character performs it (developed script, screenplay direction, poses/sets from an image generator when needed, lip-synced render, review-and-fix loop, YouTube Shorts and Instagram Reels quality), publish it to the user's YouTube channel with marketing metadata at a fixed daily slot, post the Instagram Reel if set up, and hand over the files. Use whenever the user pastes or points to a script or idea and wants a video made and/or posted, says "here's today's script", "make this a short/reel", "generate and upload", or asks to run the YouTube automation pipeline.
---

# Daily Short: rough script → cinematic Short → YouTube (+ Instagram)

The user gives a rough script. You do everything else and come back with live links and a ready Instagram kit.

This skill chains **anime-talking-short** (screenplay tags, assets, render), **youtube-upload** and **instagram-upload**. Read anime-talking-short's SKILL.md once per session for the tag reference and directing guide.

```bash
REPO={{REPO}}
PY={{PY}}
R=$REPO/skills/anime-talking-short/scripts/render.py
UP="$PY $REPO/skills/youtube-upload/scripts/upload.py"
IG="$PY $REPO/skills/instagram-upload/scripts/upload.py"
FF=$($PY -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")
```

## Start: read the user's settings

Read `$REPO/config.json` first. Every personal value comes from there, never from this file:

| Key | Use |
|---|---|
| `creator_name`, `creator_name_spoken` | Write the name as `{creator_name=creator_name_spoken}`, e.g. `{AJ=A J}`, then `[pause 1.0]` after the sentence that ends with it. |
| `youtube_channel` | `--channel` for the uploader. It refuses any other channel. |
| `instagram_account` | `--account` for the Instagram uploader. If empty, skip Instagram posting and hand over the kit. |
| `voice`, `music` | `--voice`, `--music` for the renderer (`music` is relative to `$REPO`; empty means none). |
| `publish_time`, `utc_offset` | The daily slot. |
| `auto_publish` | `false`: show the title, description and slot and ask before any upload. `true`: publish without asking. |
| `channel_style` | Tone to keep when developing the script. |

If `config.json` is missing or still has the example values, stop and tell the user to run `python install.py` and fill it in. Check for `$REPO/my/built/poses/*/pose.json` too. If there are no poses, walk them through the README's character section first.

## Steps

1. **Develop the script** into `$REPO/jobs/<yyyy-mm-dd>-<slug>/script.txt`.
   - **Keep their voice** (`channel_style`) and their phrases and jokes. Don't sanitize it.
   - **Hook:** the first sentence is the hook, a bold claim, question or contradiction in at most 8 words, because the swipe decision happens in the first second.
   - **Middle:** one idea, with a turn or a sarcastic beat every 10–15 s.
   - **Ending:** a call to action, then a final line that loops back into the opening, so replays feel seamless.
   - **Length:** about 185 words for a minute. Measure with `$PY $R --script script.txt --out short.mp4 --voice <voice> --dry`, aim for 56–60 s (pauses included), and trim or add until it fits. Run the dry run in the background: voice-service retries can push it past a 5-minute tool timeout. With the Chatterbox engine the dry run generates every line (about 13 minutes per minute of speech on a CPU) and caches them, so the later render reuses them. Slower moods (`relaxed`, `tired`, `exhausted`) lengthen the video.

2. **Direct it.** Add delivery, shot, sound, drop and `*emphasis*` tags following anime-talking-short's directing guide. You are the screenwriter, cinematographer and editor:
   - **Coverage:** A-cam and B-cam, faces on a third, tele lens or rack focus on new locations.
   - **Emphasis:** 6–10 `*emphasis*` punch-ins.
   - **Transitions:** about 4, each with a reason.
   - **Poses:** chosen by meaning.
   - **Reveals:** letterbox for them. On a big-face pose use `frame=cu` without `move=ecu`, or the push-in cuts the eyes off in the 2.39 strip.
   - **Moods:** tag every line with the emotion the user wants and avoid long runs in one tone: `[excited]`/`[elated]` for high-pitched joy, `[relaxed]`, `[tired]`, `[exhausted]`, `[bored]` for a flat drawl, `[sarcastic]`, `[hype]`, `[normal]`. Map the user's bracketed hints such as `(high pitch)` or `(boring)` to these.
   - **Names:** only use pose and set names that exist in `$REPO/my/built/`.

3. **Assets.** Reuse first. Generate new art only when the script truly needs it (a topic-specific set or a missing gesture). Follow the prompt rules in anime-talking-short ("Assets"), save into `$REPO/my/poses|backgrounds/`, rebuild, and check the importer's mouth scores (below 0.45 means no lip-sync for that pose).

4. **Render.** This takes about 5–6 minutes per minute of video on a CPU (plus the Chatterbox voice generation if it isn't cached), so run it in the background. **Run one render per output folder at a time:** two overlapping renders write the same `short.mp4` and leave a damaged file. The output is already at platform quality: 1080x1920 30 fps, H.264 High, AAC 384k, -14 LUFS.
   ```bash
   $PY $R --script script.txt --out short.mp4 --voice <voice> [--music $REPO/<music>]
   ```

5. **Review and fix until it's clean.** Re-render after each fix.
   - **Every shot:** tile the middle frame of every shot from `short/timeline.json`:
     ```bash
     $FF -i short.mp4 -vf "select='eq(n\,F1)+eq(n\,F2)+...',scale=180:320,tile=8x3" -frames:v 1 -fps_mode vfr shots.png
     ```
     Check that:
     - the face is fully in frame, and letterbox strips show eyes to mouth
     - captions don't cover the mouth, and the emphasis words land
     - each pose fits its line
     - nothing is black or broken
   - **Mouth:** tile 12 consecutive close-up frames and check that the mouth opens on the speech. Correlating the timeline's mouth-open frames with the final audio's loudness should give a best lag of 0.
   - **Integrity:** after every render, `$FF -v error -i short.mp4 -f null -` must print nothing. Only a full decode catches a half-written file.
   - **Fixing:** fix the screenplay tags first. Change code only for real bugs, and run `--selftest` after any change to code.

6. **Marketing metadata.** Write `meta.json` with `title`, `description`, `tags`, `category`, `publish_at` and `ig_caption`.
   - **Title:** 40–70 characters, ending in ` #Shorts`. Lead with the hook or curiosity gap, main keyword early, no profanity (it limits reach), and no promise the video doesn't keep.
   - **Description:**
     - Line 1: the hook with the search keyword.
     - Line 2: "Follow <youtube_channel> for a new one every day."
     - A blank line.
     - Then 3–5 hashtags: `#Shorts`, 2–3 for the topic and 1 for the niche.
   - **Tags:** 8–12 tags (topic phrase, variants, channel name, creator name), under 500 characters.
   - **Category:** `23` Comedy, `24` Entertainment, `22` People & Blogs or `27` Education.
   - **Publish slot:** `publish_at` is today at `publish_time` with `utc_offset`, because the same time every day beats picking the perfect hour. If that time has already passed, use `null` and publish now. If the user asks to publish "now", do that and skip the slot. Ask early if it is unclear: the YouTube uploader can't change a scheduled video afterwards (see step 8).
   - **ig_caption:** write it as UTF-8 (emoji are fine, but don't print them in a Windows console). The hook line, 1–2 lines of context, a comment prompt ("Comment your pick 👇 and I'll read every single one."), "Follow for a new one every day.", then **at most 5 hashtags**.

7. **Instagram kit,** in `$REPO/reels/`:
   - **Video:** `<date>-<slug>.mp4`.
   - **Caption:** `<date>-<slug>.txt` with `ig_caption`.
   - **Cover:** `<date>-<slug>-cover.jpg`, the strongest close-up with a giant emphasis caption, taken with `$FF -ss <t> -i short.mp4 -frames:v 1 -q:v 2 cover.jpg`. Keep `t` in ms for Instagram.

8. **Publish.** Open `short.mp4` for the user first so they can watch it. If `auto_publish` is false, confirm with the user before any upload.
   ```bash
   $UP short.mp4 --channel <youtube_channel> --privacy public [--publish-at <publish_at>] \
     --title "..." --description "..." --tags "..." --category NN
   ```
   If `instagram_account` is set, also post the Reel. **Pick the route by length:** some Meta apps refuse the direct upload above about 32 s (`ProcessingFailedError`, `bytes_transferred: 0`), and a Short is about 57 s. Check yours with a >32 s test early.
   - **Tear down the tunnel right after publishing:** stop the `cloudflared` and `http.server` processes (match the process name AND its command line, never the command line alone, or you may kill unrelated shells), delete the served folder and check that the public URL now returns an error (502).
   - **Up to ~30 s, or if your app accepts longer files: direct upload** (in the background when `--at` is in the future):
     ```bash
     $IG short.mp4 --account <instagram_account> --caption-file reels/<date>-<slug>.txt --thumb-offset <t ms> [--at <publish_at>]
     ```
   - **Longer videos, when the direct upload fails: the `video_url` route** with `$REPO/skills/instagram-upload/scripts/upload_url.py` through a temporary Cloudflare quick tunnel. A tunnel is a third-party relay, so **ask the user first, every time**, whatever `auto_publish` says. The full recipe (serve one randomly named copy, test the tunnel speed, publish, tear everything down) is in instagram-upload's SKILL.md.
   - **Never post a shrunken or lower-quality copy as a fallback** (for example through instagram.com with a file squeezed under a browser tool's upload cap). If no route can publish the full-quality file, stop and give the user the files to post from their phone.
   - **Redo of a published video:** always ask first. The uploaders can't delete, so a redo leaves a duplicate the user must remove by hand.
   - **Missing login, wrong channel or wrong account:** stop and tell the user. Never upload anywhere else.
   - **Unexpectedly `privacy=private`:** the Google Cloud project is unverified. Tell the user to set the video to Public in YouTube Studio.
   - **A scheduled YouTube video must go public now:** the uploader's login can't edit videos, and a second upload would leave a duplicate. Use YouTube Studio: the video's Visibility → Public → Save.

9. **Verify live, then report.** Open both posts in a browser: the Short plays and is public, and the Reel shows the right caption and its cover in the profile grid (not black). If a browser tool reports several connected browsers, ask the user which one to use before any action.

   **Report** in a few lines:
   - the YouTube and Instagram links with their schedule
   - the final script
   - the kit paths
   - the title and hashtags
   - the first-hour actions: reply to every comment and pin a question comment

## Growth and monetization rules

- **Retention decides reach** more than tags: a hook in the first second, a cut every 2–4 s, a loop at the end, and no dead air except deliberate pauses.
- **Originality protects monetization.** YouTube's Partner Program rejects mass-produced, repetitive ("inauthentic") content. Every video needs a new idea and script in the user's voice. Vary sets, poses and camera plans, and never re-upload or lightly re-edit an old video.
- **Partner Program bar:** 1,000 subscribers plus 10 million Shorts views in 90 days, or 4,000 watch hours. Never inflate expectations.
- **Disclosure:** a clearly cartoon character needs no altered-content disclosure. Never make videos that imitate real people.
- **Accounts:** never ask for or accept passwords. Logins are OAuth (YouTube) and a dashboard token (Instagram) that the user saves themselves.
