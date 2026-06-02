"""Render backend interface.

Lets the render step (combine clips, mix audio, burn captions, encode) run in
different places without changing the rest of the app. Local keeps today's
behavior; another backend can run it elsewhere, such as a remote service.

To add one: subclass RenderBackend, implement render(), and register it in
app/services/render/__init__.py.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List

from app.models.schema import VideoParams


@dataclass
class RenderContext:
    """Everything a backend needs to render one final video, all already computed
    by the pipeline: the clips, the voiceover, the subtitle file, output paths and
    the user's params."""

    params: VideoParams
    video_paths: List[str]          # downloaded clip files, in order
    audio_file: str                 # voiceover audio
    subtitle_path: str              # SRT produced earlier in the pipeline
    combined_video_path: str        # intermediate, silent, normalized resolution
    final_video_path: str           # the finished video to produce
    video_concat_mode: Any
    video_transition_mode: Any


class RenderBackend(ABC):
    """A render backend. Implementations must produce ctx.final_video_path."""

    name: str = "base"

    @abstractmethod
    def render(self, ctx: RenderContext) -> None:
        """Produce ctx.final_video_path. Raise on failure so the caller can react."""
        raise NotImplementedError
