"""Publish a Reel to the user's Instagram account from a public video URL (the `video_url` route).

Use this for videos longer than about 30 s: some apps get `ProcessingFailedError` from the direct
upload in upload.py above ~32 s (see SKILL.md). Meta downloads the file from the URL, so it
must be publicly reachable and fast (a Cloudflare quick tunnel works; the free localhost.run relay
is throttled and fails). Same token and account check as upload.py. Standard library only.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://graph.facebook.com"
TOKEN = Path.home() / ".instagram-upload" / "token.txt"


def call(method, path, tok, **params):
    data = urllib.parse.urlencode(params)
    url = f"{API}/{path}" + (f"?{data}" if method == "GET" and data else "")
    req = urllib.request.Request(url, data=None if method == "GET" else data.encode(), method=method,
                                 headers={"Authorization": f"OAuth {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:  # name only the step; the token travels in a header, never the URL
        raise RuntimeError(f"Instagram API error on {path}: {e.read().decode(errors='replace')}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video_url", help="public https URL of the mp4")
    p.add_argument("--account", required=True, help="expected Instagram username; stops if the token is for another account")
    p.add_argument("--caption-file")
    p.add_argument("--thumb-offset", type=int, help="cover frame, in milliseconds from the start")
    p.add_argument("--container", help="resume polling an existing container id instead of creating one")
    p.add_argument("--publish", action="store_true", help="publish once the video is processed (default: stop at READY)")
    a = p.parse_args()

    if not TOKEN.exists():
        raise RuntimeError(f"No token. Save the token from the Meta app dashboard to {TOKEN} (see the instagram-upload skill).")
    tok = TOKEN.read_text().strip()
    want = a.account.lstrip("@").lower()
    accounts = call("GET", "me/assigned_instagram_accounts", tok, fields="id,username").get("data", [])
    ig = next((x for x in accounts if x.get("username", "").lower() == want), None)
    if not ig:
        raise RuntimeError(f"Token has no access to @{want}. Not uploading.")

    if a.container:
        cid = a.container
    else:
        caption = Path(a.caption_file).read_text(encoding="utf-8").strip() if a.caption_file else ""
        extra = {"thumb_offset": a.thumb_offset} if a.thumb_offset is not None else {}
        cid = call("POST", f"{ig['id']}/media", tok, media_type="REELS", video_url=a.video_url, caption=caption,
                   share_to_feed="true", **extra)["id"]
    print("container", cid, flush=True)

    for i in range(40):  # Meta downloads and processes the video; about 100 s for 40 MB on a fast tunnel
        s = call("GET", cid, tok, fields="status_code,status")  # not video_status: video_url containers reject it (error 2207065)
        print(i, s["status_code"], flush=True)
        if s["status_code"] == "FINISHED":
            break
        if s["status_code"] in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram rejected the video: {s.get('status')}")
        time.sleep(10)
    else:
        raise RuntimeError("Instagram still processing after ~7 minutes; container " + cid)

    if not a.publish:
        print("READY (not published)")
        return
    m = call("POST", f"{ig['id']}/media_publish", tok, creation_id=cid)
    print("PUBLISHED", call("GET", m["id"], tok, fields="permalink").get("permalink", m["id"]))


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        sys.exit(str(e))
