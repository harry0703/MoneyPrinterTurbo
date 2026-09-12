from abc import ABC, abstractmethod
from typing import Dict, List, Any


class PublishingProvider(ABC):
    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if provider is ready (enabled and credentials present)."""
        raise NotImplementedError

    def snapshot_targets(self) -> Dict[str, Any] | None:
        """Capture queue-time publishing destinations + privacy settings.

        Contract: return a JSON-serializable dict with at least ``provider``,
        ``platforms`` (list copy), ``youtube_privacy_status``, and an
        ``extra`` dict for provider-specific values (e.g. Postiz integration
        IDs + api_url/api_key; upload_post privacy_level + username). Freeze
        destinations + privacy + IDs + endpoint/credentials: the task worker
        passes snapshot values back into ``upload_video`` as explicit kwargs
        so one publish operation keeps a single instance/identity even if
        live config changes mid-operation. Providers must accept those
        kwargs with a ``None`` default that falls back to live config for
        backward-compatible direct callers.

        The default implementation returns ``None`` for backward
        compatibility with legacy providers; the caller then uses a generic
        live-read fallback and logs a warning (fail-open, destinations may
        drift). New providers should override this method.
        """
        return None

    @abstractmethod
    def upload_video(self, video_path: str, title: str, platforms: List[str], **kwargs) -> Dict[str, Any]:
        """Upload a video file to the provider. Return a dict with at least a 'success' key."""
        raise NotImplementedError

    @abstractmethod
    def check_status(self, request_id: str) -> Dict[str, Any]:
        """Check status of a previously submitted post request."""
        raise NotImplementedError


PUBLISHING_PROVIDER_REGISTRY = {}
