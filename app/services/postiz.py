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

    @staticmethod
    def _normalize_api_base(api_url: str) -> str:
        """Normalize *api_url* to the upstream author spec base ``/public/v1``.

        Pure function of its argument (no config reads) so a snapshot-frozen
        URL and the live config URL go through identical normalization.
        """
        base = (api_url or "").rstrip("/")
        if base.endswith("/api/public/v1"):
            return base[: -len("/api/public/v1")] + "/public/v1"
        if base.endswith("/public/v1"):
            return base
        return f"{base}/public/v1"

    def _api_base(self) -> str:
        """Build the Public API base URL.

        Strip trailing slashes, then normalize to the upstream author
        spec base ``/public/v1``: check the ``/api/public/v1`` case
        first and strip a trailing ``/api`` so the base is always
        ``<host>/public/v1``. A pasted URL ending in ``/api/public/v1``
        is normalized to ``/public/v1``; a URL already ending in
        ``/public/v1`` is returned unchanged; otherwise ``/public/v1``
        is appended. This function NEVER returns a base ending in
        ``/api/public/v1``. Delegates to :meth:`_normalize_api_base` so
        snapshot-frozen URLs normalize identically to live config.
        """
        return self._normalize_api_base(self.api_url)

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
        self,
        platform: str,
        title: str,
        *,
        youtube_privacy_status: Optional[str] = None,
        tiktok_auto_add_music: Any = None,
        reddit_subreddit: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return the provider-specific settings dict for *platform*.

        Snapshot overrides (from the queue-time publishing snapshot) take
        precedence over live config reads so background execution never
        observes a config change made after queue time.
        """
        if platform == "youtube":
            privacy = (
                youtube_privacy_status
                if youtube_privacy_status is not None
                else self.youtube_privacy_status
            )
            return self._settings_youtube(title, privacy)
        if platform == "instagram":
            return self._settings_instagram()
        if platform == "tiktok":
            if tiktok_auto_add_music is None:
                tiktok_auto_add_music = config.app.get(
                    "postiz_tiktok_auto_add_music", "no"
                )
            auto_add_music = self._coerce_auto_add_music(tiktok_auto_add_music)
            return self._settings_tiktok(title, auto_add_music)
        if platform == "x":
            return self._settings_x()
        if platform == "linkedin":
            return self._settings_linkedin()
        if platform == "reddit":
            subreddit = (
                reddit_subreddit
                if reddit_subreddit is not None
                else config.app.get("postiz_reddit_subreddit", "")
            )
            return self._settings_reddit(title, subreddit)
        # Fallback: bare type marker
        return {"__type": _POSTIZ_PLATFORM_MAP.get(platform, {}).get("__type", platform)}

    def snapshot_targets(self) -> Dict[str, Any]:
        """Capture queue-time publishing destinations + privacy settings.

        Called once at queue time by the task pipeline. The returned dict is
        JSON-serializable and passed into the background worker, which must
        use it exclusively instead of re-reading live config at execution.

        Frozen here: platforms, youtube_privacy_status, tiktok_auto_add_music,
        reddit_subreddit, per-platform integration IDs, AND the endpoint +
        credentials (``api_url`` + ``api_key``). Freezing endpoint/auth keeps
        every request of one publish operation on the same instance with the
        same identity: a config change mid-operation must not send the upload
        to instance A and the create-post (carrying A's media/integration
        IDs) to instance B.
        """
        platforms = list(self.platforms or [])
        integration_ids = {}
        for platform in platforms:
            try:
                integration_ids[platform] = self._get_integration_id(platform)
            except Exception as exc:
                logger.debug(
                    f"Postiz snapshot: coerce integration ID to empty string "
                    f"for platform={platform!r}: {exc}",
                    exc_info=True,
                )
                integration_ids[platform] = ""
        return {
            "provider": "postiz",
            "platforms": platforms,
            "youtube_privacy_status": self.youtube_privacy_status,
            "extra": {
                "tiktok_auto_add_music": config.app.get(
                    "postiz_tiktok_auto_add_music", "no"
                ),
                "reddit_subreddit": config.app.get("postiz_reddit_subreddit", ""),
                "integration_ids": integration_ids,
                # Endpoint + credentials frozen at queue time so one publish
                # operation stays on a single instance with a single identity.
                "api_url": self.api_url,
                "api_key": self.api_key,
            },
        }

    def upload_video(
        self,
        video_path: str,
        title: str,
        platforms: Optional[List[str]] = None,
        youtube_privacy_status: Optional[str] = None,
        tiktok_auto_add_music: Any = None,
        reddit_subreddit: Optional[str] = None,
        integration_ids: Optional[Dict[str, Optional[str]]] = None,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        # Endpoint + credentials are resolved ONCE here and reused for the
        # upload request and every create-post request below, so a config
        # change mid-operation cannot split one publish across instances.
        # Snapshot-provided values (queue-time) win when given; otherwise
        # fall back to live config for backward-compatible direct callers.
        resolved_api_url = self.api_url if api_url is None else api_url
        resolved_api_key = self.api_key if api_key is None else api_key
        api_base = self._normalize_api_base(resolved_api_url)
        auth_headers = {"Authorization": resolved_api_key}
        # Snapshot-provided integration IDs bypass the live config lookup so
        # execution uses queue-time destinations even if config changed.
        use_snapshot_integrations = integration_ids is not None
        if not use_snapshot_integrations and not self.is_configured():
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
                    f"{api_base}/upload",
                    headers=auth_headers,
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

            if use_snapshot_integrations:
                integration_id = (integration_ids or {}).get(platform)
            else:
                integration_id = self._get_integration_id(platform)
            if not integration_id:
                logger.warning(f"No Postiz integration ID configured for platform: {platform}")
                results.append({"platform": platform, "success": False, "error": f"No integration ID for {platform}"})
                continue

            # Reddit requires a non-empty subreddit
            if platform == "reddit":
                if reddit_subreddit is not None:
                    subreddit = reddit_subreddit
                else:
                    subreddit = config.app.get("postiz_reddit_subreddit", "")
                if not subreddit:
                    logger.warning("Postiz reddit_subreddit is empty, skipping Reddit")
                    results.append({"platform": platform, "success": False, "error": "No reddit subreddit configured"})
                    continue

            settings = self._build_platform_settings(
                platform,
                title,
                youtube_privacy_status=youtube_privacy_status,
                tiktok_auto_add_music=tiktok_auto_add_music,
                reddit_subreddit=reddit_subreddit,
            )

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
                    f"{api_base}/posts",
                    headers={**auth_headers, "Content-Type": "application/json"},
                    json=post_payload,
                    timeout=300,
                )
                post_resp.raise_for_status()
                post_json = post_resp.json()
                if isinstance(post_json, list) and len(post_json) > 0:
                    first = post_json[0] if isinstance(post_json[0], dict) else {}
                    post_id = first.get("postId", "")
                    if not post_id:
                        logger.warning(
                            f"Postiz returned an empty postId for {platform}: {post_json}"
                        )
                        results.append(
                            {
                                "platform": platform,
                                "success": False,
                                "error": "Postiz returned an empty postId",
                                "response": post_json,
                            }
                        )
                        continue
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

    def check_status(
        self,
        request_id: str,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Check status via GET /posts with required date range.

        ``api_url``/``api_key`` are optional queue-time snapshot overrides;
        when omitted the live config is used. Either way the endpoint + auth
        are resolved once and reused for the whole call.
        """
        resolved_api_url = self.api_url if api_url is None else api_url
        resolved_api_key = self.api_key if api_key is None else api_key
        api_base = self._normalize_api_base(resolved_api_url)
        auth_headers = {"Authorization": resolved_api_key}
        try:
            now = datetime.now(timezone.utc)
            params = {
                "startDate": (now - timedelta(days=7)).isoformat(),
                "endDate": now.isoformat(),
            }
            resp = requests.get(
                f"{api_base}/posts",
                headers=auth_headers,
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
                # Documented Postiz list-posts entries carry `state`
                # (e.g. "ERROR"); keep the `status` return key for API
                # compat but source its value state-first.
                status_value = matched.get("state", matched.get("status", "unknown"))
                return {
                    "success": True,
                    "request_id": request_id,
                    "status": status_value,
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
