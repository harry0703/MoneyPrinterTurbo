"""
Handler for JiMeng Video API (VolcEngine).
Supports asynchronous video generation using text-to-video API.
"""
import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Literal
from urllib.parse import urlencode
import hashlib
import hmac
import datetime
import requests

from volcenginesdkarkruntime import Ark
from volcenginesdkarkruntime.types.content_generation.content_generation_task import ContentGenerationTask
from volcenginesdkarkruntime.types.content_generation.content_generation_task_id import ContentGenerationTaskID

class JiMengVideoAPIException(Exception):
    """Custom exception for JiMeng Video API errors."""
    pass


class JiMengVideoHandler:

    def __init__(
        self,
        api_key: str,
        model: str = "doubao-seedance-1-5-pro-251215"
    ) -> None:
        """
        Args:
            api_key: 即梦提供的API Key。
            model:  模型ID。
        """
        
        self.api_key = api_key
        self.model = model

        self.client = Ark(
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key=api_key,
        )
    
    async def generate_video(
        self,
        prompt: str,
        seed: int = -1,
        frames: Optional[int] = None,
        aspect_ratio: Literal["16:9", "4:3", "1:1", "3:4", "9:16"] = "9:16",
        camera_fixed: bool = False,
        poll_interval: int = 3,
        timeout: int = 600,
        watermark: bool = True,
        req_json: Optional[str] = None
    ) -> Optional[str]:
        """
        用于生成视频流的内容……参数什么的不想多说了，气死我了。
        """
        
        # 创建内容
        create_result: ContentGenerationTaskID = self.client.content_generation.tasks.create(
            model=self.model,
            content=[
                {
                    "type": "text",
                    "text": prompt,
                },
            ],
            frames=frames if self.model != "doubao-seedance-1-5-pro-251215" else None,
            ratio=aspect_ratio,
            camera_fixed=camera_fixed,
            watermark=watermark,
            timeout=timeout,
            seed=seed,
        )
        
        # 保存一份任务ID
        task_id: str = create_result.id

        # 然后轮询内容，直到出结果为止
        while True: 
            get_result: ContentGenerationTask = self.client.content_generation.tasks.get(task_id=task_id)
            status = get_result.status
            if status == "succeeded":
                print("----- task succeeded -----")
                print(get_result)
                return get_result.content.video_url

            elif status == "failed":
                print("----- task failed -----")
                print(f"Error: {get_result.error}")
                return get_result.content.video_url
            
            else:
                await asyncio.sleep(poll_interval)

# Example usage
async def main() -> None:
    # Example values - replace with actual credentials   
    
    key: str = "YOUR_KEY_HERE"  # 自己搞一个key，记得在使用之前先去官网激活模型。
    handler = JiMengVideoHandler(api_key=key)
    
    try:
        # Generate a video with continuous status checking
        video_url = await handler.generate_video(
            prompt="技术革命在消灭旧岗位的同时，也会催生新的职业类别和需求",
            timeout=600,
            watermark=False
        )
        
        print(f"Generated video URL: {video_url}")
    except JiMengVideoAPIException as e:
        print(f"Error generating video: {e}")


if __name__ == "__main__":
    # Run the example
    asyncio.run(main())
    pass
