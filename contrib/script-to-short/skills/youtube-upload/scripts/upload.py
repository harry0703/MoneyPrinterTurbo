"""Upload a video to YouTube via Data API v3 (OAuth installed-app flow, token cached locally).
Run with the repo's .venv python (install.py installs google-api-python-client, google-auth-oauthlib)."""
import argparse
import sys
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

HOME = Path.home() / ".youtube-upload"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]  # readonly: verify target channel


def creds():
    tok, secret = HOME / "token.json", HOME / "client_secret.json"
    c = Credentials.from_authorized_user_file(str(tok), SCOPES) if tok.exists() else None
    if c and not c.valid and c.refresh_token:
        try:
            c.refresh(Request())
        except RefreshError:
            c = None  # revoked/expired refresh token: log in again
    if not c or not c.valid:
        if not secret.exists():
            sys.exit(f"Missing {secret}. Follow the setup steps in the youtube-upload skill.")
        c = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES).run_local_server(port=0)
    tok.write_text(c.to_json())
    tok.chmod(0o600)  # holds a refresh token
    return c


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("file", nargs="?")
    p.add_argument("--title")
    p.add_argument("--description", default="")
    p.add_argument("--tags", default="", help="comma separated")
    p.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    p.add_argument("--category", default="22", help="22=People & Blogs, 24=Entertainment, 27=Education")
    p.add_argument("--publish-at", help="schedule: ISO 8601 time with offset, e.g. 2026-11-14T18:30:00+05:30 (uploads private, goes public then)")
    p.add_argument("--channel", help="expected channel handle, e.g. @your_channel; aborts if the login is a different channel")
    p.add_argument("--auth-only", action="store_true", help="just do the one-time browser login")
    a = p.parse_args()
    c = creds()
    yt = build("youtube", "v3", credentials=c)
    ch = yt.channels().list(part="snippet", mine=True).execute()["items"][0]["snippet"]
    handle = ch.get("customUrl", "")
    print(f"Logged in as channel: {ch['title']} ({handle})")
    if a.channel and handle.lower() != a.channel.lower():
        sys.exit(f"Wrong channel: expected {a.channel}. Delete {HOME / 'token.json'} and re-run --auth-only, picking that channel.")
    if a.auth_only:
        sys.exit(0)
    if not a.channel:
        sys.exit("--channel is required to upload, so a login for the wrong channel can't post.")
    if not (a.file and Path(a.file).is_file() and a.title):
        sys.exit("need an existing video file and --title")
    def clean(s):  # YouTube rejects angle brackets
        return s.replace("<", "").replace(">", "")
    body = {"snippet": {"title": clean(a.title)[:100], "description": clean(a.description)[:5000],
                        "tags": [t.strip() for t in a.tags.split(",") if t.strip()], "categoryId": a.category},
            "status": {"privacyStatus": "private" if a.publish_at else a.privacy, "selfDeclaredMadeForKids": False}}
    if a.publish_at:  # YouTube only schedules private videos
        body["status"]["publishAt"] = a.publish_at
    req = yt.videos().insert(
        part="snippet,status", body=body, media_body=MediaFileUpload(a.file, chunksize=-1, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    print(f"UPLOADED https://youtube.com/shorts/{resp['id']} privacy={resp['status']['privacyStatus']} publishAt={resp['status'].get('publishAt', 'now')}")
