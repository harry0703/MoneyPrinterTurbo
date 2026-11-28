---
name: youtube-upload
description: Upload a local video file to the user's YouTube channel (Shorts or regular) through the official YouTube Data API v3 with a one-time OAuth browser login, setting title, description, tags and privacy. Use whenever the user wants to publish, post or upload a video to YouTube or YouTube Shorts from this machine, instead of any YouTube MCP or browser automation.
---

# YouTube upload

`scripts/upload.py` uses OAuth. The user approves access in their browser once, and the refresh token is cached in `~/.youtube-upload/token.json`. **Never ask for or accept a YouTube or Google password.** OAuth is the only supported route, and a password in chat is a security risk.

```bash
UP="{{PY}} {{REPO}}/skills/youtube-upload/scripts/upload.py"
$UP --auth-only                                    # one-time browser login
$UP out/short.mp4 --channel @your_channel --title "Title #Shorts" --description "... #Shorts" --tags "a,b" --privacy private
```

It prints `UPLOADED https://youtube.com/shorts/<id> privacy=...`. `--channel` is required for an upload: it stops if the login is for a different channel.

## One-time setup (walk the user through it if `~/.youtube-upload/client_secret.json` is missing)
1. Go to console.cloud.google.com and create a project. Then open APIs & Services → Library and enable **YouTube Data API v3**.
2. Open the OAuth consent screen. Choose External, fill in the app name and email, and add the user's Google account under **Test users**.
3. Open Credentials → Create credentials → OAuth client ID → **Desktop app**. Download the JSON and save it as `~/.youtube-upload/client_secret.json`.
4. Run `$UP --auth-only` and pick the channel's account in the browser. The warning "Google hasn't verified this app" is expected for your own test app: click Continue.

## Know before publishing
- **Videos stay private.** Videos uploaded from an *unverified* Google Cloud project are locked to private by YouTube, whatever `--privacy` says. Either the user switches each video to Public in YouTube Studio (one click), or they pass Google's API audit (the YouTube API Services audit form) to unlock public uploads. Tell the user this once instead of letting it look like a bug.
- **Quota.** One upload costs about 1,600 of the default 10,000 daily units, so roughly 6 uploads a day.
- **Shorts.** A video of 3 minutes or less that is vertical counts as a Short. Adding `#Shorts` to the title or description helps.
- **Confirm before publishing.** Publishing is outward-facing, so confirm the final title and privacy with the user before uploading, unless they have already said to publish without asking.
