"""Run with ARCMIRA_API_KEY set: uv run python -m scripts.check_arcmira_live."""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from moviepy import VideoFileClip

from app.config import config
from app.models.schema import VideoAspect, VideoParams
from app.services import arcmira, task
from app.utils import utils


def main():
    key = os.environ.get("ARCMIRA_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set ARCMIRA_API_KEY before running this check.")

    task_id = "arcmira-check-" + uuid4().hex
    calls = []
    original_get = arcmira.requests.get
    original_config = dict(config.app)

    def observed_get(url, *args, **kwargs):
        response = original_get(url, *args, **kwargs)
        if url == arcmira.API_URL:
            payload = response.json()
            meta = payload.get("meta") or {}
            calls.append(
                {
                    "status": response.status_code,
                    "query": kwargs.get("params"),
                    "request_id": response.headers.get("x-request-id")
                    or payload.get("request_id")
                    or meta.get("request_id"),
                    "moments": [
                        {
                            "video_id": c.get("video_id"),
                            "start_seconds": c.get("start_seconds"),
                            "channel": c.get("channel_name"),
                        }
                        for c in payload.get("chunks", [])
                    ],
                }
            )
        return response

    config.app.update(
        arcmira_api_key=key, material_directory="task", subtitle_provider="edge"
    )
    arcmira.requests.get = observed_get
    try:
        result = task.start(
            task_id,
            VideoParams(
                video_subject="Vibe coding",
                video_script="Vibe coding helps business leaders build software.",
                video_terms=["vibe coding"],
                video_source="arcmira",
                video_aspect=VideoAspect.landscape,
                video_clip_duration=5,
                match_materials_to_script=True,
                voice_name="en-US-AriaNeural-Female",
                bgm_type="",
                bgm_volume=0,
                subtitle_enabled=True,
                n_threads=2,
            ),
        )
        if not isinstance(result, dict) or not result.get("videos"):
            raise SystemExit("The live check did not produce a final video.")
        output = Path(result["videos"][0])
        folder = Path(utils.task_dir(task_id))
        with VideoFileClip(str(output)) as video:
            output_info = {
                "file": output.name,
                "duration": video.duration,
                "width": video.w,
                "height": video.h,
                "audio_present": video.audio is not None,
            }
        data = json.loads((folder / "script.json").read_text())
        allowed = {
            "provider",
            "video_id",
            "start_seconds",
            "end_seconds",
            "channel",
            "published_at",
            "search_term",
            "source_page",
        }
        evidence = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "requests": calls,
            "output": output_info,
            "subtitle_present": bool(list(folder.glob("*.srt"))),
            "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "sources": [
                {k: v for k, v in s.items() if k in allowed}
                for s in data.get("material_sources", [])
            ],
        }
        (folder / "arcmira-verification.json").write_text(
            json.dumps(evidence, indent=2) + "\n"
        )
        print(json.dumps(evidence, indent=2))
    finally:
        arcmira.requests.get = original_get
        config.app.clear()
        config.app.update(original_config)


if __name__ == "__main__":
    main()
