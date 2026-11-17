"""Upload videos to YouTube with the official YouTube Data API v3."""
from __future__ import annotations

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


class YouTubeAuthError(RuntimeError):
    pass


def _save_token(path: Path, creds: Credentials) -> None:
    path.write_text(creds.to_json())
    os.chmod(path, 0o600)


def get_credentials(secrets_dir: Path, interactive: bool = False) -> Credentials:
    token_path = secrets_dir / "youtube_token.json"
    client_path = secrets_dir / "client_secret.json"
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(token_path, creds)
        except Exception as exc:  # refresh token revoked or expired
            if not interactive:
                raise YouTubeAuthError(
                    f"YouTube token refresh failed ({exc}); run: agent.py youtube-auth"
                ) from exc
            creds = None
    if creds and creds.valid:
        return creds
    if not interactive:
        raise YouTubeAuthError("YouTube is not authorized; run: agent.py youtube-auth")
    if not client_path.exists():
        raise YouTubeAuthError(f"Missing OAuth client file: {client_path}")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    _save_token(token_path, creds)
    return creds


def channel_title(creds: Credentials) -> str:
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    items = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
    return items[0]["snippet"]["title"] if items else "(no channel on this account)"


def upload(
    creds: Credentials,
    video_path: str,
    title: str,
    description: str,
    tags: list[str],
    category_id: str = "28",
    privacy: str = "public",
    made_for_kids: bool = False,
) -> dict:
    clean_title = title.replace("<", "").replace(">", "").strip()[:100]
    body = {
        "snippet": {
            "title": clean_title,
            "description": description.replace("<", "").replace(">", "")[:4900],
            "tags": tags[:15],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    media = MediaFileUpload(video_path, mimetype="video/mp4", chunksize=-1, resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = request.next_chunk()
    video_id = response["id"]
    return {
        "id": video_id,
        "url": f"https://youtube.com/shorts/{video_id}",
        "privacy": response.get("status", {}).get("privacyStatus"),
        "requested_privacy": privacy,
    }
