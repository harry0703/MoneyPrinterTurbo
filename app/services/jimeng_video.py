from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from loguru import logger

from app.config import jimeng
from app.jimeng_video_handler import JiMengVideoHandler, JiMengVideoAPIException


@dataclass(slots=True)
class JiMengVideoService:
    """Service for generating videos using JiMeng Video API."""

    api_key: str = field(init=False)
    model: str = field(init=False)
    region: str = field(init=False)
    handler: JiMengVideoHandler | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.api_key = jimeng.get("api_key", "")
        self.model = jimeng.get("model", "")
        self.region = jimeng.get("region", "cn-north-1")

        if not self.api_key:
            logger.warning(
                "JiMeng Video API credentials not configured. Video generation will not work."
            )
            return

        try:
            self.handler = JiMengVideoHandler(
                api_key=self.api_key,
                model=self.model
            )
        except JiMengVideoAPIException as exc:
            logger.warning(f"JiMeng SDK initialization failed: {exc}")
            self.handler = None

    async def generate_video(
        self,
        prompt: str,
        seed: int = -1,
        frames: int = 121,
        aspect_ratio: str = "16:9",
        poll_interval: int = 3,
        timeout: int = 600,
        req_json: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate a video using JiMeng Video API.

        :param prompt: Text prompt for video generation
        :param seed: Random seed (-1 for random)
        :param frames: Number of frames (121 for 5s, 241 for 10s)
        :param aspect_ratio: Aspect ratio ("16:9", "4:3", etc.)
        :param poll_interval: Polling interval in seconds
        :param timeout: Timeout in seconds
        :param req_json: Additional options JSON
        :return: Video URL if successful, None otherwise
        """
        if not self.handler:
            raise ValueError("JiMeng Video API credentials not configured")

        try:
            logger.info(f"Starting video generation with prompt: {prompt}")
            video_url = await self.handler.generate_video(
                prompt=prompt,
                seed=seed,
                frames=frames,
                aspect_ratio=aspect_ratio,
                poll_interval=poll_interval,
                timeout=timeout,
                req_json=req_json
            )
            logger.info(f"Video generated successfully: {video_url}")
            return video_url
        except JiMengVideoAPIException as e:
            logger.error(f"JiMeng Video API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in video generation: {e}")
            raise


# Global service instance
jimeng_video_service = JiMengVideoService()
