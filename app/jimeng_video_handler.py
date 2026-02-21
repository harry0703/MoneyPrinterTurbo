"""
Handler for JiMeng Video API (VolcEngine).
Supports asynchronous video generation using text-to-video API.
"""
import asyncio
import json
import time
from typing import Optional, Dict, Any
from urllib.parse import urlencode
import hashlib
import hmac
import datetime
import requests


class JiMengVideoAPIException(Exception):
    """Custom exception for JiMeng Video API errors."""
    pass


class JiMengVideoHandler:
    """
    Handler for JiMeng Video API (VolcEngine)
    Supports submitting and querying video generation tasks.
    """

    def __init__(self, access_key_id: str, secret_access_key: str, region: str = "cn-north-1"):
        """
        Initialize the JiMeng Video handler
        
        :param access_key_id: Access key ID for VolcEngine account
        :param secret_access_key: Secret access key for VolcEngine account
        :param region: Region for the service (default: cn-north-1)
        """
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.region = region
        self.service = "cv"
        self.host = "visual.volcengineapi.com"
        self.base_url = f"https://{self.host}"

    def _sign(self, key: bytes, msg: str) -> str:
        """Generate HMAC-SHA256 signature."""
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).hexdigest()

    def _get_signature_key(self, key: str, date_stamp: str, region_name: str, service_name: str) -> bytes:
        """Generate signature key."""
        k_date = hmac.new(("VC" + key).encode("utf-8"), date_stamp.encode("utf-8"), hashlib.sha256).digest()
        k_region = hmac.new(k_date, region_name.encode("utf-8"), hashlib.sha256).digest()
        k_service = hmac.new(k_region, service_name.encode("utf-8"), hashlib.sha256).digest()
        k_signing = hmac.new(k_service, b"request", hashlib.sha256).digest()
        return k_signing

    def _make_request(self, action: str, version: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make a request to the JiMeng Video API.
        """
        # Prepare query parameters
        params = {
            "Action": action,
            "Version": version
        }
        query_string = urlencode(params)

        # Current timestamp
        now = datetime.datetime.utcnow()
        timestamp = now.strftime('%Y-%m-%dT%H:%M:%SZ')
        date_stamp = now.strftime('%Y%m%d')

        # Prepare headers
        headers = {
            "Host": self.host,
            "Content-Type": "application/json; charset=utf-8",
            "X-Content-Sha256": hashlib.sha256(json.dumps(payload, separators=(',', ':')).encode()).hexdigest(),
            "X-Date": timestamp,
        }

        # Create canonical request
        http_method = "POST"
        canonical_uri = "/"
        canonical_querystring = query_string
        canonical_headers = (
            f"content-type:{headers['Content-Type']}\n"
            f"host:{self.host}\n"
            f"x-content-sha256:{headers['X-Content-Sha256']}\n"
            f"x-date:{headers['X-Date']}\n"
        )
        signed_headers = "content-type;host;x-content-sha256;x-date"
        payload_hash = headers["X-Content-Sha256"]

        canonical_request = f"{http_method}\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"

        # Create string to sign
        algorithm = "VC1-HMAC-SHA256"
        credential_scope = f"{date_stamp}/{self.region}/{self.service}/request"
        string_to_sign = f"{algorithm}\n{timestamp}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}"

        # Calculate signature
        signing_key = self._get_signature_key(self.secret_access_key, date_stamp, self.region, self.service)
        signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()

        # Create authorization header
        auth_header = f"{algorithm} Credential={self.access_key_id}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"

        # Add auth header to request headers
        headers["Authorization"] = auth_header

        # Make the request
        url = f"{self.base_url}/?{query_string}"
        response = requests.post(url, headers=headers, data=json.dumps(payload, separators=(',', ':')))

        if response.status_code != 200:
            raise JiMengVideoAPIException(f"Request failed with status {response.status_code}: {response.text}")

        try:
            return response.json()
        except json.JSONDecodeError:
            raise JiMengVideoAPIException(f"Failed to parse response as JSON: {response.text}")

    def submit_task(
        self,
        prompt: str,
        seed: int = -1,
        frames: int = 121,
        aspect_ratio: str = "16:9"
    ) -> Dict[str, Any]:
        """
        Submit a video generation task to JiMeng API.
        
        :param prompt: Prompt for video generation (Chinese or English, max 800 chars)
        :param seed: Random seed for generation (-1 for random)
        :param frames: Total frames (121 for 5s, 241 for 10s)
        :param aspect_ratio: Aspect ratio ("16:9", "4:3", "1:1", "3:4", "9:16", "21:9")
        :return: Response containing task_id
        """
        payload = {
            "req_key": "jimeng_t2v_v30",
            "prompt": prompt,
            "seed": seed,
            "frames": frames,
            "aspect_ratio": aspect_ratio
        }

        return self._make_request("CVSync2AsyncSubmitTask", "2022-08-31", payload)

    async def submit_task_async(
        self,
        prompt: str,
        seed: int = -1,
        frames: int = 121,
        aspect_ratio: str = "16:9"
    ) -> Dict[str, Any]:
        """
        Asynchronously submit a video generation task to JiMeng API.
        
        :param prompt: Prompt for video generation (Chinese or English, max 800 chars)
        :param seed: Random seed for generation (-1 for random)
        :param frames: Total frames (121 for 5s, 241 for 10s)
        :param aspect_ratio: Aspect ratio ("16:9", "4:3", "1:1", "3:4", "9:16", "21:9")
        :return: Response containing task_id
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, 
            self.submit_task, 
            prompt, 
            seed, 
            frames, 
            aspect_ratio
        )

    def query_task(
        self,
        task_id: str,
        req_json: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Query the status of a submitted video generation task.
        
        :param task_id: Task ID returned from submit_task
        :param req_json: JSON string for additional options like watermarking
        :return: Response containing video_url, status, etc.
        """
        payload = {
            "req_key": "jimeng_t2v_v30",
            "task_id": task_id
        }
        
        if req_json:
            payload["req_json"] = req_json

        return self._make_request("CVSync2AsyncGetResult", "2022-08-31", payload)

    async def query_task_async(
        self,
        task_id: str,
        req_json: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Asynchronously query the status of a submitted video generation task.
        
        :param task_id: Task ID returned from submit_task
        :param req_json: JSON string for additional options like watermarking
        :return: Response containing video_url, status, etc.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.query_task,
            task_id,
            req_json
        )

    async def generate_video_with_status_check(
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
        Submit a video generation task and continuously check its status until completion.
        
        :param prompt: Prompt for video generation (Chinese or English, max 800 chars)
        :param seed: Random seed for generation (-1 for random)
        :param frames: Total frames (121 for 5s, 241 for 10s)
        :param aspect_ratio: Aspect ratio ("16:9", "4:3", "1:1", "3:4", "9:16", "21:9")
        :param poll_interval: Time interval (seconds) between status checks
        :param timeout: Maximum time (seconds) to wait for completion
        :param req_json: JSON string for additional options like watermarking
        :return: Video URL if successful, None otherwise
        """
        # Submit the task
        submit_response = await self.submit_task_async(prompt, seed, frames, aspect_ratio)
        
        if "data" not in submit_response or "task_id" not in submit_response["data"]:
            error_msg = submit_response.get('message', 'Unknown error')
            code = submit_response.get('code', 'Unknown')
            raise JiMengVideoAPIException(
                f"Failed to submit task (code {code}): {error_msg}"
            )
        
        task_id = submit_response["data"]["task_id"]
        print(f"Submitted task with ID: {task_id}")
        
        # Poll for completion
        start_time = time.time()
        while time.time() - start_time < timeout:
            query_response = await self.query_task_async(task_id, req_json)
            
            if "data" not in query_response:
                error_msg = query_response.get('message', 'Unknown error')
                code = query_response.get('code', 'Unknown')
                raise JiMengVideoAPIException(
                    f"Error querying task (code {code}): {error_msg}"
                )
                
            status = query_response["data"].get("status", "unknown")
            print(f"Task status: {status}")
            
            if status == "done":
                video_url = query_response["data"].get("video_url")
                if video_url:
                    return video_url
                else:
                    raise JiMengVideoAPIException("Task completed but no video URL returned")
                    
            elif status == "not_found":
                raise JiMengVideoAPIException("Task not found - may have expired or invalid ID")
                
            elif status == "expired":
                raise JiMengVideoAPIException("Task has expired")
                
            # Wait before next poll
            await asyncio.sleep(poll_interval)
        
        raise JiMengVideoAPIException(f"Timeout waiting for task completion after {timeout} seconds")


# Example usage
async def main():
    # Example values - replace with actual credentials
    access_key = "your_access_key_here"
    secret_key = "your_secret_key_here"
    
    handler = JiMengVideoHandler(access_key, secret_key)
    
    try:
        # Generate a video with continuous status checking
        video_url = await handler.generate_video_with_status_check(
            prompt="一只可爱的小猫在花园里玩耍",
            seed=-1,
            frames=121,  # 5 seconds
            aspect_ratio="16:9",
            poll_interval=10,
            timeout=600  # 10 minutes
        )
        
        print(f"Generated video URL: {video_url}")
    except JiMengVideoAPIException as e:
        print(f"Error generating video: {e}")


if __name__ == "__main__":
    # Run the example
    # asyncio.run(main())
    pass