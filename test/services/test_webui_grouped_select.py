from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import llm, voice


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


class _GroupedSelectHarness:
    """只替换视频来源组件，保留页面中其它 Components v2 的真实实现。"""

    def __init__(self):
        self.selected = None
        self.calls = []
        self.declaration = None
        self._original_component = st.components.v2.component

    def declare(self, name, *args, **kwargs):
        # 新手引导等第三方组件同样使用 Components v2。透传这些声明可以避免
        # 测试桩改变页面其它功能，只控制本用例关心的视频来源选择结果。
        if name != "mpt_grouped_select":
            return self._original_component(name, *args, **kwargs)

        self.declaration = kwargs

        def render(**render_kwargs):
            self.calls.append(render_kwargs)
            return SimpleNamespace(selected=self.selected)

        return render


@contextmanager
def _running_app(harness, *, saved_video_source="pexels"):
    """在整个用例期间保持组件、配置和外部音色查询隔离。"""
    test_app_config = dict(
        config.app, video_source=saved_video_source, script_generation_backend="local"
    )
    test_ui_config = dict(config.ui, language="en")
    with (
        patch(
            "streamlit.components.v2.component",
            side_effect=harness.declare,
        ),
        patch.object(config, "app", test_app_config),
        patch.object(config, "ui", test_ui_config),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(
            voice,
            "get_all_azure_voices",
            return_value=["en-US-JennyNeural-Female"],
        ),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.run()
        assert [str(item.value) for item in app.exception] == []
        yield app


def test_grouped_video_source_applies_first_change_and_allows_switching_back():
    """一次 change 事件就应更新业务状态，不能要求用户重复选择。"""
    harness = _GroupedSelectHarness()
    with _running_app(harness) as app:
        assert app.session_state["video_source_select_en"] == "pexels"
        assert harness.calls[-1]["data"]["value"] == "pexels"

        harness.selected = "pixabay"
        app.run()
        assert [str(item.value) for item in app.exception] == []
        assert app.session_state["video_source_select_en"] == "pixabay"
        # grouped_selectbox 会在事件轮次主动 rerun；最后一次渲染必须把新值
        # 回传给前端，否则组件仍可能被旧 data 覆盖。
        assert harness.calls[-1]["data"]["value"] == "pixabay"

        harness.selected = "pexels"
        app.run()
        assert [str(item.value) for item in app.exception] == []
        assert app.session_state["video_source_select_en"] == "pexels"
        assert harness.calls[-1]["data"]["value"] == "pexels"


def test_grouped_video_source_ignores_unknown_event_and_repairs_saved_value():
    """过期配置和伪造事件都不能让页面进入未知素材来源状态。"""
    harness = _GroupedSelectHarness()
    with _running_app(harness, saved_video_source="removed-provider") as app:
        assert app.session_state["video_source_select_en"] == "pexels"
        assert harness.calls[-1]["data"]["value"] == "pexels"

        harness.selected = "unknown-provider"
        app.run()
        assert [str(item.value) for item in app.exception] == []
        assert app.session_state["video_source_select_en"] == "pexels"
        assert harness.calls[-1]["data"]["value"] == "pexels"


def test_aigei_regenerates_existing_english_keywords_only_on_request():
    harness = _GroupedSelectHarness()
    original_script = "通勤使用车载导航，医生查看 X 光片。"
    original_terms = "car navigation, medical imaging"
    regenerate_key = "aigei_regenerate_chinese_keywords"
    responses = [
        '["car navigation", "medical imaging"]',
        "Error: unavailable",
        '["car navigation", "医生查看X光片"]',
        '["车载导航", "医生查看X光片"]',
    ]
    with (
        _running_app(harness) as app,
        patch.object(llm, "generate_script", return_value=original_script),
        patch.object(llm, "_generate_response", side_effect=responses) as model,
    ):
        app.text_area(key="video_subject").set_value("生活中的人工智能").run()
        app.button(key="auto_generate_script").click().run()
        assert app.text_area(key="video_terms").value == original_terms
        assert all(button.key != regenerate_key for button in app.button)

        harness.selected = "aigei"
        app.run()
        assert app.text_area(key="video_terms").value == original_terms
        assert any(
            item.value.startswith("Current keywords are in English.")
            and "more relevant footage" in item.value
            for item in app.caption
        )
        assert model.call_count == 1

        app.button(key=regenerate_key).click().run()
        assert app.text_area(key="video_terms").value == original_terms
        assert any("generate" in item.value for item in app.error)

        app.button(key=regenerate_key).click().run()
        assert app.text_area(key="video_terms").value == "车载导航, 医生查看X光片"
        assert app.text_area(key="video_script").value == original_script
        assert all(button.key != regenerate_key for button in app.button)
        assert model.call_count == 4
        assert "reply with english search terms only" in model.call_args_list[0].args[0]
        assert "简体中文" in model.call_args.args[0]

        for terms in ("", "4K 以外", "AI ナビ", "123", "AI 医疗, car navigation"):
            app.text_area(key="video_terms").set_value(terms).run()
            assert all(button.key != regenerate_key for button in app.button)
        harness.selected = "pexels"
        app.run()
        assert app.text_area(key="video_terms").value == "AI 医疗, car navigation"
        assert model.call_count == 4
        assert not app.exception


def test_aigei_requires_narration_before_regenerating_keywords():
    harness = _GroupedSelectHarness()
    with (
        _running_app(harness, saved_video_source="aigei") as app,
        patch.object(llm, "_generate_response", return_value='["城市街景"]') as model,
    ):
        app.text_area(key="video_terms").set_value("city streets").run()
        app.text_area(key="video_script").set_value("[停顿: 2秒] (pause: 1s)").run()

        button = app.button(key="aigei_regenerate_chinese_keywords")
        if not button.disabled:
            button.click().run()

        assert app.text_area(key="video_terms").value == "city streets"
        assert not model.called
        assert button.disabled


def test_grouped_video_source_keeps_groups_and_accessible_label_binding():
    """组件数据应保持分组顺序，并为可见标签提供稳定控件 ID。"""
    harness = _GroupedSelectHarness()
    with _running_app(harness):
        data = harness.calls[-1]["data"]
        assert data["controlId"] == "video_source_select_en_control"
        assert [group["label"] for group in data["groups"]] == [
            "Stock Video",
            "AI Video",
            "AI Image",
            "Local Files",
        ]
        assert [
            option["value"] for group in data["groups"] for option in group["options"]
        ] == [
            "pexels",
            "pixabay",
            "coverr",
            "aigei",
            "metaso_minimax",
            "ofox",
            "loomloom",
            "volcengine_seedance",
            "infistar",
            "jalapeno",
            "wavespeed",
            "muapi",
            "useapi",
            "openai_image",
            "codex_image",
            "useapi_image",
            "local",
        ]

        # AppTest 当前不会暴露 Components v2 的内部 DOM，因此同时校验组件声明
        # 确实使用 controlId 关联 label/select，并允许窄屏下标签行自然换行。
        assert "label.htmlFor = data.controlId" in harness.declaration["js"]
        assert "select.id = data.controlId" in harness.declaration["js"]
        assert "flex-wrap: wrap" in harness.declaration["css"]


def test_stock_concurrency_only_appears_for_stock_sources():
    """库存并发仅对库存素材显示，切换来源时保留显式设置。"""
    harness = _GroupedSelectHarness()
    with _running_app(harness) as app:
        stock = next(
            item for item in app.selectbox
            if item.key.startswith("material_concurrency_select_")
        )
        clip = next(
            item for item in app.selectbox
            if item.key.startswith("clip_rendering_concurrency_select_")
        )
        assert stock.value == 1
        assert clip.value == 1

        stock.set_value(4).run()
        clip = next(
            item for item in app.selectbox
            if item.key.startswith("clip_rendering_concurrency_select_")
        )
        clip.set_value(2).run()
        assert config.app["material_concurrency"] == 4
        assert config.app["video_clip_concurrency"] == 2

        for source, show_stock in (
            ("pixabay", True),
            ("coverr", True),
            ("aigei", True),
            ("wavespeed", False),
            ("local", False),
            ("pexels", True),
        ):
            harness.selected = source
            app.run()
            assert [str(item.value) for item in app.exception] == []
            stock_widgets = [
                item for item in app.selectbox
                if item.key.startswith("material_concurrency_select_")
            ]
            assert bool(stock_widgets) is show_stock
            if show_stock:
                assert stock_widgets[0].value == 4
            assert next(
                item for item in app.selectbox
                if item.key.startswith("clip_rendering_concurrency_select_")
            ).value == 2
            assert config.app["material_concurrency"] == 4
