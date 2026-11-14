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
- **Upload:** the video goes straight from this PC to Meta in a single request to `rupload.facebook.com`. There's no third-party host.
- **Processing:** it waits until Instagram reports the video `FINISHED` (up to 10 minutes), then publishes.
- **`--at`:** the API has no scheduling. It uploads now, sleeps until that time, then publishes. Run it in the background, and keep Claude Code open until then. The time must be within 24 hours, because containers expire after that.
- **Cover:** `--thumb-offset` picks the cover as a frame time in milliseconds.
- **Token:** its lifetime is set when it's generated in the dashboard. If a run fails with an expired token, the user generates a new one (setup step 4).
- **Limits:**
  - 100 API posts per 24 hours.
  - No trending audio, collaborators, drafts or deleting through the API.
  - A caption can be up to 2,200 characters with up to 30 hashtags (the user's rule is at most 5).

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
