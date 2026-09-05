"""
Postiz API integration for cross-posting videos via the Postiz Public API.

Docs: https://docs.postiz.com/public-api/introduction
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

import requests
from loguru import logger
from app.config import config
from app.services.publishing_base import PublishingProvider, PUBLISHING_PROVIDER_REGISTRY

# Maps MPT platform names to Postiz __type values and integration config keys.
_POSTIZ_PLATFORM_MAP: Dict[str, Dict[str, str]] = {
    "youtube": {
        "__type": "youtube",
        "integration_key": "postiz_youtube_integration_id",
    },
    "instagram": {
        "__type": "instagram",
        "integration_key": "postiz_instagram_integration_id",
    },
    "tiktok": {
        "__type": "tiktok",
        "integration_key": "postiz_tiktok_integration_id",
    },
    "x": {
        "__type": "x",
        "integration_key": "postiz_x_integration_id",
    },
    "linkedin": {
        "__type": "linkedin",
        "integration_key": "postiz_linkedin_integration_id",
    },
    "reddit": {
        "__type": "reddit",
        "integration_key": "postiz_reddit_integration_id",
    },
}


def _summarize_platform_failures(results: List[Dict[str, Any]]) -> str:
    """Build a top-level error naming every failed platform and why."""
    failed = [
        item
        for item in results
        if isinstance(item, dict) and not item.get("success")
    ]
    if not failed:
        return "No platforms processed"
    return "; ".join(
        f"{item.get('platform', 'unknown')}: {item.get('error', 'unknown error')}"
        for item in failed
    )


class PostizService(PublishingProvider):
    """Service wrapper for the Postiz Public API.

    Uses the official endpoints:
      - POST {api_url}/public/v1/upload  (multipart file upload)
      - POST {api_url}/public/v1/posts   (create / schedule post)
      - GET  {api_url}/public/v1/posts   (list posts)

    Authentication uses the raw API key in the Authorization header
    (no Bearer prefix), per the official docs.
    """

    @property
    def api_url(self) -> str:
        return config.app.get("postiz_api_url", "http://localhost:8004")

    @property
    def api_key(self) -> str:
        return config.app.get("postiz_api_key", "")

    @property
    def enabled(self) -> bool:
        return config.app.get("postiz_enabled", False)

    @property
    def platforms(self) -> List[str]:
        return config.app.get("postiz_platforms", ["youtube"])

    @property
    def auto_upload(self) -> bool:
        return config.app.get("postiz_auto_upload", False)

    @property
    def youtube_privacy_status(self) -> str:
        return config.app.get("postiz_youtube_privacy_status", "public")

    @property
    def max_pending_tasks(self) -> int:
        return config.app.get("postiz_max_pending_tasks", 5)

    def _auth_headers(self) -> Dict[str, str]:
        """Return headers with raw API key (no Bearer prefix)."""
        return {"Authorization": self.api_key}

    def _api_base(self) -> str:
        """Build the Public API base URL.

        Strip trailing slashes only. If the URL already ends with
        ``/public/v1`` (hosted ``.../public/v1`` or self-hosted
        ``.../api/public/v1``), return it unchanged so a pasted full
        Public API URL keeps its ``/api`` prefix. Otherwise append
        ``/public/v1`` — never ``/api/public/v1``.
        """
        base = self.api_url.rstrip("/")
        if base.endswith("/public/v1"):
            return base
        return f"{base}/public/v1"

    def _get_integration_id(self, platform: str) -> Optional[str]:
        platform_info = _POSTIZ_PLATFORM_MAP.get(platform)
        if not platform_info:
            return None
        return config.app.get(platform_info["integration_key"], "")

    def is_configured(self) -> bool:
        if not (self.enabled and self.api_key):
            return False
        for platform in self.platforms:
            if self._get_integration_id(platform):
                return True
        return False

    # ------------------------------------------------------------------
    # Per-platform settings builders
    # ------------------------------------------------------------------

    @staticmethod
    def _settings_youtube(title: str, youtube_privacy_status: str) -> Dict[str, Any]:
        return {
            "__type": "youtube",
            "title": title[:100],
            "type": youtube_privacy_status,
            "selfDeclaredMadeForKids": "no",
            "tags": [],
        }

    @staticmethod
    def _settings_instagram() -> Dict[str, Any]:
        # Postiz InstagramDto.post_type only allows "post" | "story".
        # Video attachments are published as feed posts; "reels" is not a valid value.
        return {
            "__type": "instagram",
            "post_type": "post",
        }

    @staticmethod
    def _coerce_auto_add_music(value: Any) -> str:
        """TikTok autoAddMusic must be the string ``yes`` or ``no``."""
        if isinstance(value, bool):
            return "yes" if value else "no"
        text = str(value).strip().lower()
        if text in {"yes", "true", "1"}:
            return "yes"
        return "no"

    @staticmethod
    def _settings_tiktok(title: str, auto_add_music: str) -> Dict[str, Any]:
        return {
            "__type": "tiktok",
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "duet": True,
            "stitch": True,
            "comment": True,
            "autoAddMusic": auto_add_music,
            "brand_content_toggle": False,
            "brand_organic_toggle": False,
            "content_posting_method": "DIRECT_POST",
            "title": title[:90],
            "video_made_with_ai": False,
        }

    @staticmethod
    def _settings_x() -> Dict[str, Any]:
        return {
            "__type": "x",
            "who_can_reply_post": "everyone",
        }

    @staticmethod
    def _settings_linkedin() -> Dict[str, Any]:
        return {
            "__type": "linkedin",
            "post_as_images_carousel": False,
        }

    @staticmethod
    def _settings_reddit(title: str, subreddit: str) -> Dict[str, Any]:
        return {
            "__type": "reddit",
            "subreddit": [
                {
                    "value": {
                        "subreddit": subreddit,
                        "title": title[:90],
                        "type": "self",
                        "url": "",
                        "is_flair_required": False,
                        "flair": None,
                    }
                }
            ],
        }

    def _build_platform_settings(
        self, platform: str, title: str
    ) -> Dict[str, Any]:
        """Return the provider-specific settings dict for *platform*."""
        if platform == "youtube":
            return self._settings_youtube(title, self.youtube_privacy_status)
        if platform == "instagram":
            return self._settings_instagram()
        if platform == "tiktok":
            auto_add_music = self._coerce_auto_add_music(
                config.app.get("postiz_tiktok_auto_add_music", "no")
            )
            return self._settings_tiktok(title, auto_add_music)
        if platform == "x":
            return self._settings_x()
        if platform == "linkedin":
            return self._settings_linkedin()
        if platform == "reddit":
            subreddit = config.app.get("postiz_reddit_subreddit", "")
            return self._settings_reddit(title, subreddit)
        # Fallback: bare type marker
        return {"__type": _POSTIZ_PLATFORM_MAP.get(platform, {}).get("__type", platform)}

    def upload_video(
        self,
        video_path: str,
        title: str,
        platforms: Optional[List[str]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        if not self.is_configured():
            logger.warning("Postiz is not configured. Skipping cross-post.")
            return {"success": False, "error": "Postiz not configured"}

        if platforms is None:
            platforms = self.platforms

        if not os.path.exists(video_path):
            logger.error(f"Video file not found: {video_path}")
            return {"success": False, "error": f"Video file not found: {video_path}"}

        logger.info(f"Uploading video to Postiz (platforms: {', '.join(platforms)})...")

        # 1. Upload the video file
        try:
            with open(video_path, "rb") as video_file:
                files = {"file": video_file}
                upload_resp = requests.post(
                    f"{self._api_base()}/upload",
                    headers=self._auth_headers(),
                    files=files,
                    timeout=300,
                )
                upload_resp.raise_for_status()
                upload_json = upload_resp.json()
                media_id = upload_json.get("id")
                media_path = upload_json.get("path")
                if not media_id or not media_path:
                    raise ValueError(f"Missing id or path in upload response: {upload_json}")
        except Exception as e:
            logger.error(f"Failed to upload media to Postiz: {e}")
            return {"success": False, "error": str(e)}

        logger.info(f"Media uploaded to Postiz: id={media_id}, path={media_path}")

        # 2. Create a post for each platform with a configured integration ID
        results: List[Dict[str, Any]] = []

        for platform in platforms:
            platform_info = _POSTIZ_PLATFORM_MAP.get(platform)
            if not platform_info:
                logger.warning(f"Unsupported Postiz platform: {platform}")
                results.append({"platform": platform, "success": False, "error": f"Unsupported platform: {platform}"})
                continue

            integration_id = self._get_integration_id(platform)
            if not integration_id:
                logger.warning(f"No Postiz integration ID configured for platform: {platform}")
                results.append({"platform": platform, "success": False, "error": f"No integration ID for {platform}"})
                continue

            # Reddit requires a non-empty subreddit
            if platform == "reddit":
                subreddit = config.app.get("postiz_reddit_subreddit", "")
                if not subreddit:
                    logger.warning("Postiz reddit_subreddit is empty, skipping Reddit")
                    results.append({"platform": platform, "success": False, "error": "No reddit subreddit configured"})
                    continue

            settings = self._build_platform_settings(platform, title)

            post_payload: Dict[str, Any] = {
                "type": "now",
                "date": datetime.now(timezone.utc).isoformat(),
                "shortLink": False,
                "tags": [],
                "posts": [
                    {
                        "integration": {"id": integration_id},
                        "value": [
                            {
                                "content": title[:2200],
                                "image": [{"id": media_id, "path": media_path}],
                            }
                        ],
                        "settings": settings,
                    }
                ],
            }

            try:
                post_resp = requests.post(
                    f"{self._api_base()}/posts",
                    headers={**self._auth_headers(), "Content-Type": "application/json"},
                    json=post_payload,
                    timeout=300,
                )
                post_resp.raise_for_status()
                post_json = post_resp.json()
                if isinstance(post_json, list) and len(post_json) > 0:
                    post_id = post_json[0].get("postId", "")
                    logger.info(f"Postiz post created for {platform}: postId={post_id}")
                    results.append({"platform": platform, "success": True, "post_id": post_id})
                else:
                    logger.warning(f"Unexpected Postiz response for {platform}: {post_json}")
                    results.append({"platform": platform, "success": False, "error": "Unexpected response format", "response": post_json})
            except Exception as e:
                logger.error(f"Failed to create Postiz post for {platform}: {e}")
                results.append({"platform": platform, "success": False, "error": str(e)})

        # Overall success is True only if every requested platform succeeded
        success = bool(results) and all(r["success"] for r in results)
        payload: Dict[str, Any] = {
            "success": success,
            "results": results,
            "media_id": media_id,
        }
        if not success:
            payload["error"] = _summarize_platform_failures(results)
        return payload

    def check_status(self, request_id: str) -> Dict[str, Any]:
        """Check status via GET /posts with required date range."""
        try:
            now = datetime.now(timezone.utc)
            params = {
                "startDate": (now - timedelta(days=7)).isoformat(),
                "endDate": now.isoformat(),
            }
            resp = requests.get(
                f"{self._api_base()}/posts",
                headers=self._auth_headers(),
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            raw = resp.json()
            # API may return {"posts": [...]} or a bare list
            if isinstance(raw, dict):
                posts_list = raw.get("posts", [])
            else:
                posts_list = raw if isinstance(raw, list) else []
            # Locate the entry matching request_id
            matched = None
            for entry in posts_list:
                if entry.get("id") == request_id or entry.get("postId") == request_id:
                    matched = entry
                    break
            if matched is not None:
                return {
                    "success": True,
                    "request_id": request_id,
                    "status": matched.get("status", "..."),
                    "posts": [matched],
                }
            return {
                "success": True,
                "request_id": request_id,
                "status": "not_found",
                "posts": posts_list,
            }
        except Exception as e:
            logger.error(f"Failed to query Postiz status for {request_id}: {e}")
            return {"success": False, "error": str(e)}


postiz_service = PostizService()
PUBLISHING_PROVIDER_REGISTRY["postiz"] = postiz_service


def cross_post_video(
    video_path: str,
    title: str,
    platforms: Optional[List[str]] = None,
    **kwargs,
) -> Dict[str, Any]:
    return postiz_service.upload_video(video_path, title, platforms, **kwargs)
