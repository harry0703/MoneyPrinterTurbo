from unittest.mock import patch
from pathlib import Path
from streamlit.testing.v1 import AppTest

from app.config import config

ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"

def _widget_by_key(elements, key):
    return next(
        item
        for item in elements
        if str(getattr(item, "key", "")) == key
        or str(getattr(item, "key", "")).startswith(f"{key}_")
    )


def test_webui_upload_post_setup_guide_links_to_required_pages():
    # 首次使用自动发布时，API Key 和发布用户需要在 Upload-Post 的不同页面
    # 分别配置。这里锁定两个精确入口，避免后续文案调整后再次退化成无法点击的
    # 泛化提示，导致用户误把登录邮箱当作发布用户名称。
    with patch.object(config, "try_save_config", return_value=True):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.run()
        app.session_state["settings_dialog_open"] = True
        app.run()

        setup_guide = next(
            item
            for item in app.info
            if "https://app.upload-post.com/api-keys" in item.value
        )
        assert "https://app.upload-post.com/manage-users" in setup_guide.value


def test_webui_upload_post_checkboxes_stay_decoupled():
    # enabled=True / auto_upload=False is a deliberate split: an external
    # pipeline may call Upload-Post while auto-publish stays off. Opening the
    # settings dialog must not rewrite either key, and each checkbox must
    # reflect and write only its own key.
    test_app_config = dict(
        config.app,
        upload_post_enabled=True,
        upload_post_auto_upload=False
    )

    with (
        patch.object(config, "app", test_app_config),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.run()
        app.session_state["settings_dialog_open"] = True
        app.run()

        enabled_box = _widget_by_key(app.checkbox, "upload_post_enabled_checkbox")
        auto_box = _widget_by_key(app.checkbox, "upload_post_auto_upload_checkbox")
        assert enabled_box.value is True
        assert auto_box.value is False

        # Merely rendering the dialog must not have rewritten the split config
        assert config.app["upload_post_enabled"] is True
        assert config.app["upload_post_auto_upload"] is False

        # Toggling auto_upload on must leave enabled untouched
        auto_box.set_value(True)
        app.run()
        assert config.app["upload_post_enabled"] is True
        assert config.app["upload_post_auto_upload"] is True

def test_webui_upload_post_youtube_privacy_fallback_to_public():
    # If the config somehow contains an invalid YouTube privacy value (e.g. "draft"),
    # it should not crash the UI and should silently fallback to "public".
    test_app_config = dict(
        config.app,
        upload_post_platforms=["youtube"],
        upload_post_youtube_privacy_status="draft"
    )

    with (
        patch.object(config, "app", test_app_config),
        patch.object(config, "try_save_config", return_value=True),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.run()
        app.session_state["settings_dialog_open"] = True
        app.run()

        # The selectbox should be rendered and its value should fallback to "public"
        yt_privacy_selectbox = _widget_by_key(app.selectbox, "upload_post_youtube_privacy_status_selectbox")
        assert yt_privacy_selectbox.value == "public"
