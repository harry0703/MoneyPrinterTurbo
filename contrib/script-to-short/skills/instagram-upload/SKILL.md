---
name: instagram-upload
description: Publish a local video as an Instagram Reel on the user's own Creator/Business account through the official Instagram API with Unified Login (system-user token from the Meta app dashboard, no password, no Facebook Page), with caption, hashtags, cover frame and an optional publish time. Use whenever the user wants to post, publish or upload a Reel or video to Instagram from this machine, instead of browser automation or password logins.
---

# Instagram upload

`scripts/upload.py` posts a Reel with the official API. It uses only the Python standard library. **Never ask for or accept an Instagram or Facebook password.** The login is a token the user generates in their own Meta app dashboard and saves to `~/.instagram-upload/token.txt` themselves.

```bash
IG="{{PY}} {{REPO}}/skills/instagram-upload/scripts/upload.py"
$IG --account <username> --check                          # verify login and account
$IG short.mp4 --account <username> --caption-file caption.txt --thumb-offset 52000 [--at 2026-11-14T18:30:00+05:30]
```

It prints `PUBLISHED https://www.instagram.com/reel/<code>/`.

## How it works
- **Login:** Unified Login, on host `graph.facebook.com`. No Facebook Page is needed, but Meta requires a business portfolio on the app.
- **Account check:** the Instagram account comes from `me/assigned_instagram_accounts`. It stops unless `--account` is in that list.
- **Upload:** the video goes straight from this PC to Meta in a single request to `rupload.facebook.com`. There's no third-party host on this route (see the `video_url` route below for long videos).
- **Processing:** it waits until Instagram reports the video `FINISHED` (up to 10 minutes), then publishes.
- **`--at`:** the API has no scheduling. It uploads now, sleeps until that time, then publishes. Run it in the background, and keep Claude Code open until then. The time must be within 24 hours, because containers expire after that.
- **Cover:** `--thumb-offset` picks the cover as a frame time in milliseconds.
- **Token:** its lifetime is set when it's generated in the dashboard. If a run fails with an expired token, the user generates a new one (setup step 4).
- **Limits:**
  - **Long videos can fail the direct upload.** On one app, anything over about 32 s was refused with `ProcessingFailedError` ("Request processing failed", `retriable: false`), whatever the size, codec or content. A 31 s clip passed and a 33 s one failed; a 0.68 MB, 60 s clip failed too. Meta's docs list longer Reel limits, so check yours with a >32 s test early; `--check` only proves the login, not uploads. If it happens, use the `video_url` route below.
  - **Diagnose a failed upload** with `GET /<container-id>?fields=status_code,video_status`: `bytes_transferred: 0` plus `FILE_NOT_FOUND` means Meta refused the file before storing it.
  - 100 API posts per 24 hours.
  - No trending audio, collaborators, drafts or deleting through the API.
  - A caption can be up to 2,200 characters with up to 30 hashtags (the user's rule is at most 5).

## Videos over ~30 s: the `video_url` route

`scripts/upload_url.py` gives Meta a public URL to download instead of uploading the bytes. It does the same account check, creates the Reel container, polls `status_code,status`, and publishes with `--publish`:

```bash
{{PY}} {{REPO}}/skills/instagram-upload/scripts/upload_url.py https://<public-host>/<file>.mp4   --account <username> --caption-file caption.txt --thumb-offset 42000 --publish
```

`--container <id>` resumes polling an existing container. Don't request `video_status` on these containers (error 2207065).

**A temporary public URL is a third-party relay. Ask the user before opening one, every time.** A Cloudflare quick tunnel works well; install `cloudflared` yourself from the official releases page (https://github.com/cloudflare/cloudflared/releases) and check its SHA-256 against the digest GitHub shows. Then:

1. Put ONE copy of the mp4, under a random filename, in a new empty folder with an empty `index.html` (hides the directory listing).
2. `python -m http.server <port> --bind 127.0.0.1` in that folder, in the background.
3. `cloudflared tunnel --no-autoupdate --url http://127.0.0.1:<port>` in the background; the `https://….trycloudflare.com` URL is in its log.
4. Test the speed first: `curl -s -o /dev/null -w "%{speed_download}" <url>/<file>`. Under about 300 KB/s, stop. The free localhost.run relay manages about 2 KB/s, and Meta then gives up with error 2207077.
5. Run `upload_url.py` as above. A 42 MB file took about 100 s for Meta to fetch over a fast tunnel.
6. **Tear down at once:** stop `cloudflared` and the http.server (on Windows, find the server by its command line, since a Git Bash `&` PID is not the Windows PID), delete the folder, and confirm the public URL now fails (HTTP 502).

The cover (`--thumb-offset`) picks a frame, so the frame must already contain any caption text you want on it.

**Never post a shrunken or lower-quality copy as a fallback** (for example through instagram.com with a file squeezed under a browser tool's upload cap). If no route can publish the full-quality file, stop and give the user the files to post from their phone.

## One-time setup (walk the user through it if `~/.instagram-upload/token.txt` is missing)
1. The Instagram account must be a **Creator or Business** account.
2. At developers.facebook.com, open the app with the use case **"Manage messaging & content on Instagram"**, then Use cases → Customize → **API setup with Unified login**.
3. Click **+ Business portfolio** and pick or create one. It's free and doesn't need a Facebook Page.
4. Add the Instagram account as an **Instagram Tester**, accept the invite in the Instagram app, then click **Generate token** in step 2 of that page. Choose the longest expiry offered.
5. The user saves it themselves. Don't paste it in chat:
   ```powershell
   notepad "$env:USERPROFILE\.instagram-upload\token.txt"
   ```
6. Run `$IG --account <username> --check`.
