"""Local render backend: the default.

This wraps the existing render path (video.combine_videos + video.generate_video)
behind the RenderBackend interface. The behavior is unchanged. This is what runs
unless the user explicitly selects a different backend.
"""

import os

from loguru import logger

from app.services import video
from app.services.render.base import RenderBackend, RenderContext


def _ensure_local(path):
    # Local rendering needs the clip on disk. The Rendobar backend skips the
    # download and keeps the source URL, so fetch it here when falling back to
    # local. Plain local paths pass through.
    source_url = getattr(path, "source_url", "")
    if source_url and not os.path.isfile(str(path)):
        try:
            from app.services.material import save_video
            local = save_video(video_url=source_url, save_dir="")
            if local:
                return local
            logger.warning(f"could not download {source_url}")
        except Exception as e:
            logger.warning(f"download error for {source_url}: {e}")
    return path


class LocalRenderBackend(RenderBackend):
    name = "local"

    def render(self, ctx: RenderContext) -> None:
        video_paths = [_ensure_local(p) for p in ctx.video_paths]
        video.combine_videos(
            combined_video_path=ctx.combined_video_path,
            video_paths=video_paths,
            audio_file=ctx.audio_file,
            video_aspect=ctx.params.video_aspect,
            video_concat_mode=ctx.video_concat_mode,
            video_transition_mode=ctx.video_transition_mode,
            max_clip_duration=ctx.params.video_clip_duration,
            threads=ctx.params.n_threads,
        )
        video.generate_video(
            video_path=ctx.combined_video_path,
            audio_path=ctx.audio_file,
            subtitle_path=ctx.subtitle_path,
            output_file=ctx.final_video_path,
            params=ctx.params,
        )
