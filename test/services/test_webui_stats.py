import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PAGE = os.path.join(ROOT, "webui", "pages", "Stats.py")


def _tree():
    with open(PAGE, "r", encoding="utf-8") as handle:
        return ast.parse(handle.read(), PAGE)


def _source():
    with open(PAGE, "r", encoding="utf-8") as handle:
        return handle.read()


class StatsPageTest(unittest.TestCase):
    """
    这一页每渲染一次都可能打一次 Instagram，而 Streamlit 每次交互都会重跑
    整个脚本。缓存和调用形状因此不是优化，是这一页能不能安全存在的前提。
    """

    def test_the_page_parses(self):
        _tree()

    def test_the_fetch_is_cached(self):
        loader = next(
            node for node in _tree().body
            if isinstance(node, ast.FunctionDef) and node.name == "load_stats"
        )
        decorators = [ast.unparse(d) for d in loader.decorator_list]
        self.assertTrue(any("cache_data" in d for d in decorators), decorators)

    def test_the_cache_has_a_time_to_live(self):
        """没有 ttl 的缓存要么永不更新，要么每次交互都重新请求。"""
        loader = next(
            node for node in _tree().body
            if isinstance(node, ast.FunctionDef) and node.name == "load_stats"
        )
        self.assertIn("ttl", ast.unparse(loader.decorator_list[0]))

    def test_the_ttl_is_not_aggressive(self):
        namespace = {}
        for node in _tree().body:
            if isinstance(node, ast.Assign) and getattr(
                node.targets[0], "id", ""
            ) == "CACHE_SECONDS":
                exec(compile(ast.Module([node], []), PAGE, "exec"), namespace)
        self.assertGreaterEqual(namespace["CACHE_SECONDS"], 300)

    def test_refreshing_is_a_deliberate_action(self):
        """自动刷新会把一个开着的标签页变成一台稳定的轮询机器。"""
        source = _source()
        self.assertIn("st.button", source)
        self.assertIn("load_stats.clear()", source)

    def test_it_does_not_query_each_media_separately(self):
        """逐条查计数会把一次浏览变成十几个请求。"""
        self.assertNotIn("media_info", _source())

    def test_one_broken_account_does_not_blank_the_page(self):
        loader = next(
            node for node in _tree().body
            if isinstance(node, ast.FunctionDef) and node.name == "load_stats"
        )
        self.assertTrue(
            any(isinstance(node, ast.Try) for node in ast.walk(loader))
        )

    def test_a_dead_session_shows_the_recovery_command(self):
        self.assertIn("--import-session", _source())

    def test_it_never_publishes(self):
        for forbidden in ("publish_reel", "clip_upload", "import_session("):
            self.assertNotIn(forbidden, _source(), forbidden)


if __name__ == "__main__":
    unittest.main()
