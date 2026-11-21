"""Publish a Reel to the user's Instagram account through the Instagram API with Unified Login.

Unified Login needs no Facebook Page and accepts the local file through a direct upload (one request) to
rupload.facebook.com, so the video never goes to a third-party host.
Token: the user saves the system-user token generated in the Meta app dashboard to
~/.instagram-upload/token.txt once. If it expires, they generate a new one.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

API = "https://graph.facebook.com"
TOKEN = Path.home() / ".instagram-upload" / "token.txt"


def send(req, what):
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:  # name only the step, never the request: it carries the token
        raise RuntimeError(f"Instagram API error on {what}: {e.read().decode(errors='replace')}")


def call(method, path, tok, **params):
    data = urllib.parse.urlencode(params)
    url = f"{API}/{path}" + (f"?{data}" if method == "GET" and data else "")
    req = urllib.request.Request(url, data=None if method == "GET" else data.encode(), method=method,
                                 headers={"Authorization": f"OAuth {tok}"})
    return send(req, path)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video", nargs="?")
    p.add_argument("--account", required=True, help="expected Instagram username; stops if the token is for another account")
    p.add_argument("--caption-file")
    p.add_argument("--thumb-offset", type=int, help="cover frame, in milliseconds from the start")
    p.add_argument("--at", help="publish time, ISO with offset, e.g. 2026-11-14T18:30:00+05:30")
    p.add_argument("--check", action="store_true", help="only verify the login and account")
    a = p.parse_args()

    if not TOKEN.exists():
        raise RuntimeError(f"No token. Save the token from the Meta app dashboard to {TOKEN} (see the instagram-upload skill).")
    tok = TOKEN.read_text().strip()
    want = a.account.lstrip("@").lower()
    accounts = call("GET", "me/assigned_instagram_accounts", tok, fields="id,username").get("data", [])
    ig = next((x for x in accounts if x.get("username", "").lower() == want), None)
    print("Token can post to: " + (", ".join("@" + x.get("username", "?") for x in accounts) or "no accounts"))
    if not ig:
        raise RuntimeError(f"Token has no access to @{want}. Not uploading.")
    if a.check:
        return
    if not a.video:
        raise RuntimeError("No video given.")
    when = datetime.fromisoformat(a.at) if a.at else None  # parse before uploading, so a typo fails fast
    if when and (when - datetime.now(when.tzinfo)).total_seconds() > 24 * 3600:
        raise RuntimeError("--at must be within 24 hours: Instagram containers expire after that.")

    caption = Path(a.caption_file).read_text(encoding="utf-8").strip() if a.caption_file else ""
    extra = {"thumb_offset": a.thumb_offset} if a.thumb_offset is not None else {}
    c = call("POST", f"{ig['id']}/media", tok, media_type="REELS", upload_type="resumable", caption=caption,
             share_to_feed="true", **extra)
    body = Path(a.video).read_bytes()
    send(urllib.request.Request(c["uri"], data=body, method="POST", headers={
        "Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(len(body))}), "video upload")

    for _ in range(60):  # Instagram processes the video; usually under 2 minutes
        s = call("GET", c["id"], tok, fields="status_code,status")
        if s["status_code"] == "FINISHED":
            break
        if s["status_code"] in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram rejected the video: {s.get('status')}")
        time.sleep(10)
    else:
        raise RuntimeError("Instagram still processing after 10 minutes; container " + c["id"])

    if when:
        wait = (when - datetime.now(when.tzinfo)).total_seconds()
        if wait > 0:
            print(f"Ready. Waiting {wait / 60:.0f} min to publish at {a.at}", flush=True)
            time.sleep(wait)
    m = call("POST", f"{ig['id']}/media_publish", tok, creation_id=c["id"])
    link = call("GET", m["id"], tok, fields="permalink").get("permalink", m["id"])
    print(f"PUBLISHED {link}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        sys.exit(str(e))
