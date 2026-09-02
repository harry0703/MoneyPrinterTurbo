import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import state as sm
from app.utils import utils

ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


@pytest.fixture
def headless_task_app(tmp_path, monkeypatch):
    # 使用独立任务目录避免读取或修改开发者的真实生成记录。测试文件只需要被
    # Streamlit 注册为媒体资源，不参与视频解码，因此无需在单元测试中调用
    # FFmpeg 生成素材，能够稳定覆盖无桌面服务器的 UI 分支。
    tasks_dir = tmp_path / "storage" / "tasks"
    task_dir = tasks_dir / "headless-test"
    task_dir.mkdir(parents=True)
    video_file = task_dir / "final-1.mp4"
    video_file.write_bytes(b"test video payload")

    monkeypatch.setattr(utils, "task_dir", lambda: str(tasks_dir))
    monkeypatch.setattr(sm.state, "get_all_tasks", lambda *_args, **_kwargs: ([], 0))
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    # AppTest 会多次重新执行页面脚本；配置保存必须在整个测试生命周期内保持
    # 隔离，防止控件初始化意外写入开发者的 config.toml。
    with patch.object(config, "try_save_config", return_value=True):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.run()
        yield app, video_file


def _button_by_key_prefix(app, key_prefix):
    return next(button for button in app.button if str(button.key).startswith(key_prefix))


def test_headless_play_renders_and_closes_browser_preview(headless_task_app):
    app, video_file = headless_task_app

    _button_by_key_prefix(app, "play_task_all_headless-test").click()
    app.run()

    assert not app.exception
    assert app.session_state["task_preview_video_file"] == str(video_file.resolve())
    assert len(app.get("video")) == 1

    _button_by_key_prefix(app, "close_task_video_preview").click()
    app.run()

    assert "task_preview_video_file" not in app.session_state
    assert len(app.get("video")) == 0


def test_headless_open_folder_shows_host_mapped_path(headless_task_app):
    app, _ = headless_task_app

    _button_by_key_prefix(app, "open_task_all_headless-test").click()
    app.run()

    assert not app.exception
    assert any(
        "./storage/tasks/headless-test" in toast.value for toast in app.get("toast")
    )
