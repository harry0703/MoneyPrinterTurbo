"""视频渲染后端接口。

任务编排只通过这里的两个方法和渲染实现交互。当前的默认实现直接调用
`app.services.video` 里的 MoviePy 代码，行为与改动前完全一致；后端发现、
按请求选择和第三方实现留给后续改动。
"""

from typing import Callable, Protocol

from app.models.schema import (
    VideoAspect,
    VideoConcatMode,
    VideoFitMode,
    VideoParams,
    VideoTransitionMode,
)
from app.services import video


class RenderBackend(Protocol):
    """`task.py` 依赖的渲染入口。

    实现必须保留进度回调、批量素材统计和 BGM 结果语义：`combine_videos`
    通过 `progress_callback` 汇报片段处理进度，并写入调用方传入的
    `source_usage` / `used_video_paths`；`generate_video` 的返回值只表示
    BGM 混合是否成功。
    """

    def combine_videos(
        self,
        combined_video_path: str,
        video_paths: list[str],
        audio_file: str,
        video_aspect: VideoAspect = VideoAspect.portrait,
        video_concat_mode: VideoConcatMode = VideoConcatMode.random,
        video_transition_mode: VideoTransitionMode = None,
        max_clip_duration: int = 5,
        threads: int = 2,
        clip_speed: float = 1.0,
        video_fit_mode: VideoFitMode = VideoFitMode.cover,
        source_usage: dict[str, int] | None = None,
        source_groups: dict[str, str] | None = None,
        used_video_paths: list[str] | None = None,
        progress_callback: Callable[[float], None] | None = None,
    ) -> str: ...

    def generate_video(
        self,
        video_path: str,
        audio_path: str,
        subtitle_path: str,
        output_file: str,
        params: VideoParams,
        bgm_file_override: str | None = None,
    ) -> bool: ...


class LocalMoviePyBackend:
    """默认实现：原样委托给现有的 MoviePy 渲染函数。

    这里刻意只做透传，调用方没有传的可选参数不会被补成默认值再交给
    `video`，因此参数组合和改动前完全一致。
    """

    def combine_videos(self, *args, **kwargs) -> str:
        return video.combine_videos(*args, **kwargs)

    def generate_video(self, *args, **kwargs) -> bool:
        return video.generate_video(*args, **kwargs)
