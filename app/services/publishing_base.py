from abc import ABC, abstractmethod
from typing import Dict, List, Any


class PublishingProvider(ABC):
    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if provider is ready (enabled and credentials present)."""
        raise NotImplementedError

    @abstractmethod
    def upload_video(self, video_path: str, title: str, platforms: List[str], **kwargs) -> Dict[str, Any]:
        """Upload a video file to the provider. Return a dict with at least a 'success' key."""
        raise NotImplementedError

    @abstractmethod
    def check_status(self, request_id: str) -> Dict[str, Any]:
        """Check status of a previously submitted post request."""
        raise NotImplementedError


PUBLISHING_PROVIDER_REGISTRY = {}
