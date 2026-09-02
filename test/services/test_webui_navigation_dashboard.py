import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest

from app.config import config
from app.models.schema import VideoParams
from app.services import series


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
WEBUI_CSS = ROOT_DIR / "webui" / "styles.css"


class TestWebUINavigationAndViews(unittest.TestCase):
    """验证 WebUI 侧边栏、控制台、创作工坊与设置视图的渲染与交互。"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_css_contains_sidebar_dashboard_and_status_styles(self):
        css = WEBUI_CSS.read_text(encoding="utf-8")
        assert ".mpt-sidebar-brand" in css
        assert ".mpt-sidebar-brand__title" in css
        assert ".mpt-sidebar-divider" in css
        assert ".mpt-sidebar-status" in css
        assert ".mpt-sidebar-status.active" in css
        assert ".mpt-sidebar-status.idle" in css
        assert ".mpt-status-dot" in css
        assert ".mpt-status-dot.pulse" in css
        assert "@keyframes mpt-pulse" in css

    def test_sidebar_navigation_options_defined(self):
        tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
        func = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_render_sidebar_navigation"
        )
        source = ast.get_source_segment(WEBUI_MAIN.read_text(encoding="utf-8"), func)
        assert '"dashboard"' in source or "'dashboard'" in source
        assert '"studio"' in source or "'studio'" in source
        assert '"trends"' in source or "'trends'" in source
        assert '"settings"' in source or "'settings'" in source

    def test_active_series_id_association_on_task_submit(self):
        tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
        func = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_render_generation_controls"
        )
        source = ast.get_source_segment(WEBUI_MAIN.read_text(encoding="utf-8"), func)
        assert "series_service.add_task_to_series" in source
        assert "active_series_id" in source

    def test_app_test_navigation_dashboard_view(self):
        app_config = dict(config.app)
        ui_config = dict(config.ui, language="en")

        with (
            patch.object(config, "app", app_config),
            patch.object(config, "ui", ui_config),
            patch.object(config, "try_save_config", return_value=True),
        ):
            app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
            app.session_state["ui_language"] = "en"
            app.session_state["nav_view"] = "dashboard"
            app.run()

            assert [str(item.value) for item in app.exception] == []
            # Verify Dashboard title is displayed
            assert any("Dashboard" in item.value for item in app.markdown)

    def test_app_test_navigation_settings_view(self):
        app_config = dict(config.app)
        ui_config = dict(config.ui, language="en")

        with (
            patch.object(config, "app", app_config),
            patch.object(config, "ui", ui_config),
            patch.object(config, "try_save_config", return_value=True),
        ):
            app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
            app.session_state["ui_language"] = "en"
            app.session_state["nav_view"] = "settings"
            app.run()

            assert [str(item.value) for item in app.exception] == []
            # Verify Settings title is displayed
            assert any("Settings" in title.value for title in app.title)
            # Verify tabs exist
            assert len(app.tabs) >= 5

    def test_app_test_navigation_studio_view_with_active_series(self):
        app_config = dict(config.app)
        ui_config = dict(config.ui, language="en")

        mock_series = {
            "id": "test-series-uuid",
            "name": "Test Science Series",
            "description": "Educational series",
            "tasks": [],
            "created_at": 1700000000,
        }

        with (
            patch.object(config, "app", app_config),
            patch.object(config, "ui", ui_config),
            patch.object(config, "try_save_config", return_value=True),
            patch("app.services.series.get_series", return_value=mock_series),
        ):
            app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
            app.session_state["ui_language"] = "en"
            app.session_state["nav_view"] = "studio"
            app.session_state["active_series_id"] = "test-series-uuid"
            app.run()

            assert [str(item.value) for item in app.exception] == []
            # Verify active series info banner is rendered
            assert any("Test Science Series" in item.value for item in app.markdown)
