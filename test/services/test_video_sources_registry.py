"""校验素材来源注册表是各入口清单的唯一事实来源。

历史缺陷：``openai_image`` 一度只在 CLI 的单任务入口可用（批量入口漏改），
批量素材分配集合也曾与素材源清单脱节。这里把注册表与各消费者的对应关系
固化成断言：新增来源时只要漏改任何一处（CLI choices、WebUI 分组、material
分发链、批量分配），测试都会直接失败。
"""

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import cli
from app.models import video_sources
from app.services import material


ROOT = Path(__file__).resolve().parents[2]
WEBUI = ROOT / "webui" / "Main.py"

STOCK_SOURCE_IDS = {"pexels", "pixabay", "coverr"}
# 历史上对 CLI 暴露的来源集合，属于对外契约，不能随意收缩或扩张。
CLI_SOURCE_IDS = {
    "pexels",
    "pixabay",
    "coverr",
    "volcengine_seedance",
    "ofox",
    "metaso_minimax",
    "openai_image",
    "local",
}


def test_registry_ids_are_unique_and_fully_grouped():
    ids = video_sources.video_source_ids()
    assert len(ids) == len(set(ids))

    groups = video_sources.video_source_groups()
    grouped = [source_id for members in groups.values() for source_id in members]
    assert sorted(grouped) == sorted(ids)


def test_registry_keeps_expected_ui_order():
    # 顺序是 WebUI 下拉框的展示契约，AI 视频组按合作服务商优先排列。
    groups = video_sources.video_source_groups()
    assert groups["stock_video"] == ("pexels", "pixabay", "coverr")
    assert groups["ai_video"] == (
        "metaso_minimax",
        "ofox",
        "loomloom",
        "volcengine_seedance",
        "wavespeed",
    )
    assert groups["ai_image"] == ("openai_image",)
    assert groups["local"] == ("local",)


def test_stock_sources_match_search_dispatch_table():
    assert set(material._STOCK_SEARCHERS) == STOCK_SOURCE_IDS


def test_generated_sources_match_generated_dispatch_table():
    generated_ids = {
        spec.id
        for spec in video_sources.VIDEO_SOURCE_REGISTRY
        if spec.kind is video_sources.VideoSourceKind.generated
    }
    # managed（胜算云）走 task 层的专用付费确认编排，不由 material 分发，
    # 因此只要求生成型一一对应。
    assert set(material._GENERATED_DOWNLOADERS) == generated_ids


def test_non_stock_sources_have_no_stock_searcher():
    for spec in video_sources.VIDEO_SOURCE_REGISTRY:
        if spec.kind is not video_sources.VideoSourceKind.stock:
            assert spec.id not in material._STOCK_SEARCHERS


def test_batch_allocation_only_covers_allocatable_kinds():
    assert video_sources.batch_allocatable_video_source_ids() == {
        "pexels",
        "pixabay",
        "coverr",
        "local",
    }
    # 生成型与托管型按量计费，参与批量分配会为同一关键词重复下单。
    for spec in video_sources.VIDEO_SOURCE_REGISTRY:
        if spec.kind in (
            video_sources.VideoSourceKind.generated,
            video_sources.VideoSourceKind.managed,
        ):
            assert spec.batch_allocatable is False


def test_cli_choices_come_from_registry():
    assert cli._CLI_VIDEO_SOURCES == video_sources.cli_video_source_ids()
    assert set(cli._CLI_VIDEO_SOURCES) == CLI_SOURCE_IDS


def test_requires_search_terms_skips_local_materials_only():
    for spec in video_sources.VIDEO_SOURCE_REGISTRY:
        assert spec.requires_search_terms == (spec.id != "local")


def test_get_video_source_handles_unknown_and_empty_values():
    assert video_sources.get_video_source("pexels") is not None
    assert video_sources.get_video_source("not-a-source") is None
    assert video_sources.get_video_source("") is None
    assert video_sources.get_video_source(None) is None


def test_webui_video_source_constants_are_derived_from_registry():
    """防止有人把来源清单字面量再抄回 WebUI。

    WebUI 是独立入口，导入它会执行整个 Streamlit 脚本，因此这里用 AST 检查
    两个展示常量的取值表达式必须是 ``video_sources.<helper>()``。
    """

    expected_helpers = {
        "VIDEO_SOURCE_GROUPS": "video_source_groups",
        "VIDEO_SOURCE_LABELS": "video_source_labels",
    }

    tree = ast.parse(WEBUI.read_text(encoding="utf-8"))
    assignments = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in expected_helpers:
                assignments[target.id] = node.value

    assert set(assignments) == set(expected_helpers)
    for name, helper in expected_helpers.items():
        call = assignments[name]
        assert isinstance(call.func, ast.Attribute), name
        assert call.func.attr == helper, name
        assert isinstance(call.func.value, ast.Name), name
        assert call.func.value.id == "video_sources", name


def test_generated_source_without_downloader_fails_fast(monkeypatch):
    """注册表声明为生成型却没有分发实现时必须显式失败。

    静默退化成库存搜索会为一个付费来源返回无关素材，比直接报错更难定位。
    """

    monkeypatch.setitem(material._GENERATED_DOWNLOADERS, "metaso_minimax", None)

    with pytest.raises(ValueError, match="has no downloader registered"):
        material.download_videos(
            task_id="registry-test",
            search_terms=["keyword"],
            source="metaso_minimax",
        )
