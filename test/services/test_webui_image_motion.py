"""用真实 Streamlit 控件验证图片效果选择、恢复与语言切换。"""

from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config
from app.models.schema import VideoParams
from app.services import state as sm, version_checker


WEBUI_MAIN = Path(__file__).resolve().parents[2] / "webui" / "Main.py"


def _select(app, key):
    return next(v for v in app.selectbox if v.key == key or str(v.key).startswith(key + "_"))


def test_motion_widget_persists_and_restores_old_and_new_tasks(tmp_path):
    with (
        patch.object(config, "app", {"video_source": "local", "llm_provider": "openai"}),
        patch.object(config, "ui", {"language": "zh", "voice_mode": "none"}),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(sm.state, "get_all_tasks", return_value=([], 0)),
        patch.object(version_checker, "poll_available_update", return_value=version_checker.UpdateCheckSnapshot(complete=True)),
        patch("app.utils.utils.task_dir", return_value=str(tmp_path)),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.session_state["ui_language"] = "zh"
        app.run()
        assert not app.exception
        widget = _select(app, "image_motion_select")
        assert widget.label == "图片动态效果"
        assert widget.value == "zoom"
        assert widget.options == ["静止", "缓慢放大"]
        widget.select("static").run()
        assert not app.exception
        assert config.ui["image_motion"] == "static"
        app.session_state["video_source_select_zh"] = "pexels"
        app.run()
        assert not app.exception
        assert not any(str(v.key).startswith("image_motion_select") for v in app.selectbox)
        app.session_state["video_source_select_zh"] = "openai_image"
        app.run()
        assert not app.exception
        assert _select(app, "image_motion_select").value == "static"

        # 模拟任务恢复：新增字段必须恢复，旧任务缺失字段必须回到原来的放大效果。
        params = VideoParams(video_subject="restore", video_source="local", image_motion="static").model_dump(mode="json")
        for expected in ("static", "zoom"):
            if expected == "zoom":
                params.pop("image_motion")
            app.session_state["task_restore_payload"] = {"params": params, "task_id": "motion-test"}
            app.run()
            assert not app.exception
            assert _select(app, "image_motion_select").value == expected

        _select(app, "top_language_code_selector").select("en").run()
        assert not app.exception
        assert _select(app, "image_motion_select").label == "Image Motion"


@pytest.mark.parametrize("rebuild", ["language", "source"])
def test_motion_selection_survives_rebuild_while_generation_holds_config(tmp_path, rebuild):
    import threading

    locked = threading.Event()
    release = threading.Event()

    def active_generation():
        with config.runtime_config_lock():
            locked.set()
            assert release.wait(30)

    with (
        patch.object(config, "app", {"video_source": "local", "llm_provider": "openai"}),
        patch.object(config, "ui", {"language": "zh", "voice_mode": "none"}),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(config, "save_config"),
        patch.object(sm.state, "get_all_tasks", return_value=([], 0)),
        patch.object(version_checker, "poll_available_update", return_value=version_checker.UpdateCheckSnapshot(complete=True)),
        patch("app.utils.utils.task_dir", return_value=str(tmp_path)),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.session_state["ui_language"] = "zh"
        app.run()
        assert not app.exception
        worker = threading.Thread(target=active_generation)
        worker.start()
        try:
            assert locked.wait(5)
            _select(app, "image_motion_select").select("static").run()
            assert not app.exception
            assert _select(app, "image_motion_select").value == "static"
            assert config.ui["image_motion"] == "zoom"
            assert config.snapshot_config_with_pending(config.ui)["image_motion"] == "static"
            if rebuild == "language":
                _select(app, "top_language_code_selector").select("en").run()
            else:
                app.session_state["video_source_select_zh"] = "pexels"
                app.run()
                assert not app.exception
                app.session_state["video_source_select_zh"] = "local"
                app.run()
            assert not app.exception
            assert _select(app, "image_motion_select").value == "static"
            assert config.snapshot_config_with_pending(config.ui)["image_motion"] == "static"
        finally:
            release.set()
            worker.join(5)
        assert config.ui["image_motion"] == "static"
