"""素材来源注册表：``video_source`` 取值与能力的唯一事实来源。

背景
----
``video_source`` 的取值此前在三个入口各自维护一份清单：

* ``webui/Main.py`` 的 ``VIDEO_SOURCE_GROUPS`` 与展示名映射（含分组顺序）；
* ``cli.py`` 的 ``_CLI_VIDEO_SOURCES``（``--video-source`` 的 choices）；
* 服务层的 ``material.download_videos`` 分发链与 ``task`` 的批量分配集合。

这类重复已经造成过真实缺陷：``cli.py`` 的注释记录了 ``openai_image`` 一度只在
某一个入口可用；批量分配集合也曾与素材源清单脱节，只能靠测试反查。集中声明
后，新增来源只需在这里增加一项，各入口通过筛选派生自己的视图，不再各写一份。

设计取舍
--------
本模块只保存 **来源身份与稳定能力**（获取方式、WebUI 分组、是否对 CLI 暴露），
不保存翻译文案，也不实现任何 API 请求：来源“是什么”由注册表维护，“怎么调用”
仍由 ``app/services/material.py`` 的分发表负责，二者由测试保证一致。

依赖方向
--------
本模块只依赖标准库；服务层与入口层单向依赖它，避免循环导入。
"""

from dataclasses import dataclass
from enum import Enum


class VideoSourceKind(str, Enum):
    """素材的获取方式，决定服务层走哪条编排路径。"""

    # 库存搜索：调用搜索接口取回候选集合，参与 24 小时搜索缓存。
    stock = "stock"
    # AI 按需生成：按量计费，逐段生成、凑够配音时长立即停止。
    generated = "generated"
    # 用户本地素材：不产生任何远端请求。
    local = "local"
    # 需要专用付费确认流程的托管生成，不走 material.download_videos 分发。
    managed = "managed"


# (分组 id, 默认展示名)。元组顺序就是 WebUI 下拉框的分组顺序；展示名同时是
# i18n 的 key，与 WebUI 里 ``tr("Pexels")`` 的用法保持一致。
VIDEO_SOURCE_GROUP_SPECS: tuple[tuple[str, str], ...] = (
    ("stock_video", "Stock Video"),
    ("ai_video", "AI Video"),
    ("ai_image", "AI Image"),
    ("local", "Local Material"),
)


@dataclass(frozen=True, slots=True)
class VideoSourceSpec:
    """单个素材来源的集中声明。

    与 ``LLMProviderSpec`` 保持同一约定：只描述跨 WebUI、CLI 和服务层都会
    使用的稳定元数据，不承载具体请求实现。
    """

    id: str
    kind: VideoSourceKind
    group: str
    default_label: str
    cli_exposed: bool = True

    @property
    def batch_allocatable(self) -> bool:
        """多视频批量生成时，是否按关键词分配互不重复的素材。

        库存搜索取回的是候选集合，复用不需要额外付费，本地素材同理；生成型
        按量计费，为一个关键词重复生成会重复扣费，因此必须排除。
        """
        return self.kind in (VideoSourceKind.stock, VideoSourceKind.local)

    @property
    def requires_search_terms(self) -> bool:
        """是否需要先用 LLM 把文案转成素材搜索关键词。"""
        return self.kind is not VideoSourceKind.local


# 元组顺序在同一分组内决定 WebUI 下拉框顺序。分组内维持“合作/付费服务优先”
# 的既有业务顺序，改动前请同步确认 webui 的展示顺序测试。
VIDEO_SOURCE_REGISTRY: tuple[VideoSourceSpec, ...] = (
    # 库存搜索型
    VideoSourceSpec("pexels", VideoSourceKind.stock, "stock_video", "Pexels"),
    VideoSourceSpec("pixabay", VideoSourceKind.stock, "stock_video", "Pixabay"),
    VideoSourceSpec("coverr", VideoSourceKind.stock, "stock_video", "Coverr"),
    # AI 视频生成型
    VideoSourceSpec(
        "metaso_minimax",
        VideoSourceKind.generated,
        "ai_video",
        "Metaso MiniMax H3",
    ),
    VideoSourceSpec("ofox", VideoSourceKind.generated, "ai_video", "OFox AI Video"),
    # 胜算云需要 WebUI 侧的付费报价确认，因此不对 CLI 暴露 --video-source
    # 取值，保持既有命令行契约不变。
    VideoSourceSpec(
        "loomloom",
        VideoSourceKind.managed,
        "ai_video",
        "Shengsuan Cloud AI Video",
        cli_exposed=False,
    ),
    VideoSourceSpec(
        "volcengine_seedance",
        VideoSourceKind.generated,
        "ai_video",
        "Volcano Engine Seedance",
    ),
    # WaveSpeed 与胜算云相同：历史上只由 WebUI 引导，因此不加入 CLI choices。
    VideoSourceSpec(
        "wavespeed",
        VideoSourceKind.generated,
        "ai_video",
        "WaveSpeed AI Video",
        cli_exposed=False,
    ),
    # AI 图片生成型（生成后渲染为片段）
    VideoSourceSpec(
        "openai_image",
        VideoSourceKind.generated,
        "ai_image",
        "OpenAI Compatible Text-to-Image",
    ),
    # 用户本地素材
    VideoSourceSpec("local", VideoSourceKind.local, "local", "Local file"),
)


DEFAULT_VIDEO_SOURCE = "pexels"

VIDEO_SOURCES: dict[str, VideoSourceSpec] = {
    spec.id: spec for spec in VIDEO_SOURCE_REGISTRY
}


def _validate_registry() -> None:
    """启动时校验注册表自身一致性，避免错误声明扩散到各入口。"""

    group_ids = {group_id for group_id, _ in VIDEO_SOURCE_GROUP_SPECS}
    seen: set[str] = set()
    for spec in VIDEO_SOURCE_REGISTRY:
        if spec.id in seen:
            raise ValueError(f"duplicate video source id in registry: {spec.id}")
        seen.add(spec.id)
        if spec.group not in group_ids:
            raise ValueError(
                f"video source {spec.id!r} references unknown group {spec.group!r}"
            )
    if DEFAULT_VIDEO_SOURCE not in VIDEO_SOURCES:
        raise ValueError(
            f"default video source {DEFAULT_VIDEO_SOURCE!r} is missing from registry"
        )


_validate_registry()


def get_video_source(source_id: str | None) -> VideoSourceSpec | None:
    """按 id 取出来源声明；未知或空值返回 ``None``。"""

    return VIDEO_SOURCES.get(str(source_id or ""))


def video_source_ids() -> tuple[str, ...]:
    return tuple(spec.id for spec in VIDEO_SOURCE_REGISTRY)


def cli_video_source_ids() -> tuple[str, ...]:
    """``--video-source`` 的可选值，按注册表顺序派生。"""

    return tuple(spec.id for spec in VIDEO_SOURCE_REGISTRY if spec.cli_exposed)


def video_source_groups() -> dict[str, tuple[str, ...]]:
    """WebUI 分组视图：分组按 ``VIDEO_SOURCE_GROUP_SPECS`` 顺序排列。"""

    groups: dict[str, list[str]] = {
        group_id: [] for group_id, _ in VIDEO_SOURCE_GROUP_SPECS
    }
    for spec in VIDEO_SOURCE_REGISTRY:
        groups[spec.group].append(spec.id)
    return {group_id: tuple(ids) for group_id, ids in groups.items()}


def video_source_labels() -> dict[str, str]:
    """来源 id 到默认展示名的映射，供 WebUI 走 i18n。"""

    return {spec.id: spec.default_label for spec in VIDEO_SOURCE_REGISTRY}


def batch_allocatable_video_source_ids() -> frozenset[str]:
    """多视频批量生成时可用“按关键词分配素材”的来源集合。"""

    return frozenset(
        spec.id for spec in VIDEO_SOURCE_REGISTRY if spec.batch_allocatable
    )
