"""
Postiz API integration for cross-posting videos to YouTube (and potentially other platforms).

Docs: (Assumed) http://localhost:4007 or configured via config.app.
"""
import os
from typing import Optional, List, Dict, Any
import requests
from loguru import logger
from app.config import config
from .publishing_base import PublishingProvider, PUBLISHING_PROVIDER_REGISTRY


class PostizService(PublishingProvider):
    """Service wrapper for Postiz API.

    Mirrors the structure of :class:`UploadPostService` but uses the Postiz endpoints.
    """

    @property
    def api_url(self) -> str:
        """Base URL for the Postiz API.

        Config key: ``postiz_api_url`` – defaults to ``http://localhost:4007``.
        """
        return config.app.get("postiz_api_url", "http://localhost:4007")

    @property
    def api_key(self) -> str:
        """Bearer token for authentication.

        Config key: ``postiz_api_key``.
        """
        return config.app.get("postiz_api_key", "")

    @property
    def enabled(self) -> bool:
        """Whether Postiz integration is enabled.

        Config key: ``postiz_enabled`` – defaults to ``False``.
        """
        return config.app.get("postiz_enabled", False)

    @property
    def platforms(self) -> List[str]:
        """Supported platforms for cross‑posting.

        Config key: ``postiz_platforms`` – defaults to ``["youtube"]``.
        """
        return config.app.get("postiz_platforms", ["youtube"])

    @property
    def auto_upload(self) -> bool:
        """Whether videos should be auto‑uploaded after generation.

        Config key: ``postiz_auto_upload`` – defaults to ``False``.
        """
        return config.app.get("postiz_auto_upload", False)

    @property
    def youtube_privacy_status(self) -> str:
        """YouTube privacy status for posts.

        Config key: ``postiz_youtube_privacy_status`` – defaults to ``"public"``.
        """
        return config.app.get("postiz_youtube_privacy_status", "public")

    @property
    def max_pending_tasks(self) -> int:
        """Maximum number of pending Postiz tasks.

        Config key: ``postiz_max_pending_tasks`` – defaults to ``5``.
        """
        return config.app.get("postiz_max_pending_tasks", 5)

    # ---------------------------------------------------------------------
    # Helper methods
    # ---------------------------------------------------------------------
    def _auth_headers(self) -> Dict[str, str]:
        """Return the Authorization header for the API.

        Postiz expects a ``Bearer`` token.
        """
        return {"Authorization": f"Bearer {self.api_key}"}

    # ---------------------------------------------------------------------
    # PublishingProvider interface
    # ---------------------------------------------------------------------
    def is_configured(self) -> bool:
        """Return ``True`` when the service is enabled and an API key is present."""
        return bool(self.enabled and self.api_key)

    def upload_video(
        self,
        video_path: str,
        title: str,
        platforms: Optional[List[str]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Upload a video to Postiz and create a post.

        Args:
            video_path: Path to the local video file.
            title: Title for the post (max 2200 characters as per YouTube limit).
            platforms: Optional list of target platforms – currently only ``youtube`` is used.
            **kwargs: Additional keyword arguments – ignored for now but kept for API compatibility.

        Returns:
            A ``dict`` with at least ``success`` (bool). On success the dict contains ``post_id``.
        """
        if not self.is_configured():
            logger.warning("Postiz is not configured. Skipping cross‑post.")
            return {"success": False, "error": "Postiz not configured"}

        if platforms is None:
            platforms = self.platforms

        if not os.path.exists(video_path):
            logger.error(f"Video file not found: {video_path}")
            return {"success": False, "error": f"Video file not found: {video_path}"}

        logger.info(f"Uploading video to Postiz (platforms: {', '.join(platforms)}) …")

        # -------------------------------------------------------------
        # 1. Upload media to /media endpoint
        # -------------------------------------------------------------
        try:
            with open(video_path, "rb") as video_file:
                files = {"file": video_file}
                media_resp = requests.post(
                    f"{self.api_url}/media",
                    headers=self._auth_headers(),
                    files=files,
                    timeout=300,
                )
                media_resp.raise_for_status()
                media_json = media_resp.json()
                media_id = media_json.get("id")
                if not media_id:
                    raise ValueError("Missing 'id' in /media response")
        except Exception as e:
            logger.error(f"Failed to upload media to Postiz: {e}")
            return {"success": False, "error": str(e)}

        # -------------------------------------------------------------
        # 2. Create a post using the uploaded media ID
        # -------------------------------------------------------------
        post_payload: Dict[str, Any] = {
            "provider": "youtube",
            "media_ids": [media_id],
            "title": title[:2200],
            "content_posting_method": "DIRECT_POST",
            "privacy_status": self.youtube_privacy_status,
        }
        # ``platforms`` is kept for future extensions – for now we only support youtube.
        try:
            post_resp = requests.post(
                f"{self.api_url}/posts",
                headers={**self._auth_headers(), "Content-Type": "application/json"},
                json=post_payload,
                timeout=300,
            )
            post_resp.raise_for_status()
            post_json = post_resp.json()
            # Expected to contain an identifier for the created post – assume ``id``.
            post_id = post_json.get("id") or post_json.get("request_id")
            if post_id:
                logger.info(f"✅ Video posted successfully! Post ID: {post_id}")
                return {"success": True, "post_id": post_id, "media_id": media_id}
            else:
                logger.warning("Postiz responded without a post identifier.")
                return {"success": False, "error": "Missing post identifier in response", "response": post_json}
        except Exception as e:
            logger.error(f"Failed to create Postiz post: {e}")
            return {"success": False, "error": str(e)}

    def check_status(self, request_id: str) -> Dict[str, Any]:
        """Check the status of a previously submitted post.

        Args:
            request_id: The identifier returned by ``upload_video`` (``post_id``).

        Returns:
            JSON response from the GET ``/posts/<id>`` endpoint.
        """
        try:
            resp = requests.get(
                f"{self.api_url}/posts/{request_id}",
                headers=self._auth_headers(),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to query Postiz status for {request_id}: {e}")
            return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------
# Singleton instance and helper function
# ---------------------------------------------------------------------
postiz_service = PostizService()
PUBLISHING_PROVIDER_REGISTRY["postiz"] = postiz_service


def cross_post_video(
    video_path: str,
    title: str,
    platforms: Optional[List[str]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Convenient wrapper mirroring :func:`upload_post.cross_post_video`.

    Delegates to ``postiz_service.upload_video``.
    """
    return postiz_service.upload_video(video_path, title, platforms, **kwargs)
