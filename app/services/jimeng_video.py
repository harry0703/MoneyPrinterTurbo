import asyncio
import os
from typing import Optional, Dict, Any
from loguru import logger

from app.config import jimeng
from app.jimeng_video_handler import JiMengVideoHandler, JiMengVideoAPIException


class JiMengVideoService:
    """Service for generating videos using JiMeng Video API."""

    def __init__(self):
        self.access_key_id = jimeng.get("access_key_id", "")
        self.secret_access_key = jimeng.get("secret_access_key", "")
        self.region = jimeng.get("region", "cn-north-1")

        if not self.access_key_id or not self.secret_access_key:
            logger.warning("JiMeng Video API credentials not configured. Video generation will not work.")

        self.handler = None
        if self.access_key_id and self.secret_access_key:
            self.handler = JiMengVideoHandler(
                access_key_id=self.access_key_id,
                secret_access_key=self.secret_access_key,
                region=self.region
            )

    async def generate_video(
        self,
        prompt: str,
        seed: int = -1,
        frames: int = 121,
        aspect_ratio: str = "16:9",
        poll_interval: int = 10,
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
            video_url = await self.handler.generate_video_with_status_check(
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

    async def submit_task(
        self,
        prompt: str,
        seed: int = -1,
        frames: int = 121,
        aspect_ratio: str = "16:9"
    ) -> Dict[str, Any]:
        """
        Submit a video generation task.

        :param prompt: Text prompt
        :param seed: Random seed
        :param frames: Number of frames
        :param aspect_ratio: Aspect ratio
        :return: Task submission response
        """
        if not self.handler:
            raise ValueError("JiMeng Video API credentials not configured")

        try:
            return await self.handler.submit_task_async(prompt, seed, frames, aspect_ratio)
        except JiMengVideoAPIException as e:
            logger.error(f"JiMeng Video API error: {e}")
            raise

    async def query_task(self, task_id: str, req_json: Optional[str] = None) -> Dict[str, Any]:
        """
        Query task status.

        :param task_id: Task ID
        :param req_json: Additional options
        :return: Task status response
        """
        if not self.handler:
            raise ValueError("JiMeng Video API credentials not configured")

        try:
            return await self.handler.query_task_async(task_id, req_json)
        except JiMengVideoAPIException as e:
            logger.error(f"JiMeng Video API error: {e}")
            raise


# Global service instance
jimeng_video_service = JiMengVideoService()