import ast
import json
import re
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
I18N_DIR = ROOT_DIR / "webui" / "i18n"
LOCALES = ("de", "en", "es", "id", "pt", "ru", "tr", "vi", "zh")
LIBRARY_HELPERS = {"_parse_comma_separated_list"}
PHOTO_LIBRARY_KEYS = (
    "Photo Require",
    "Photo Require Help",
    "Photo Prefer Tags",
    "Photo Prefer Tags Help",
    "Photo Only Tags",
    "Photo Only Tags Help",
    "Photo Exclude Tags",
    "Photo Exclude Tags Help",
    "Photo Max Duration",
    "Photo Max Duration Help",
)


def _load_library_helpers():
    """
    从 WebUI 入口中隔离加载不依赖 Streamlit 的库设置纯函数。

    直接导入 Main.py 会执行整套页面渲染。测试只编译目标函数，既验证合并后的
    真实实现，也避免为了单元测试重新拆出一个只有少量函数的生产模块。
    """
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    selected_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in LIBRARY_HELPERS
    ]

    namespace = {"re": re}
    module = ast.fix_missing_locations(ast.Module(body=selected_nodes, type_ignores=[]))
    exec(compile(module, str(WEBUI_MAIN), "exec"), namespace)
    return namespace


LIBRARY_NAMESPACE = _load_library_helpers()
parse_comma_separated_list = LIBRARY_NAMESPACE["_parse_comma_separated_list"]


def _load_translation(locale):
    data = json.loads((I18N_DIR / f"{locale}.json").read_text(encoding="utf-8"))
    return data.get("Translation", {})


class TestParseCommaSeparatedList(unittest.TestCase):
    def test_empty_string_returns_empty_list(self):
        self.assertEqual(parse_comma_separated_list(""), [])

    def test_splits_on_ascii_comma_and_strips_items(self):
        self.assertEqual(
            parse_comma_separated_list("path:a.jpg, tag:cat ,tag:dog"),
            ["path:a.jpg", "tag:cat", "tag:dog"],
        )

    def test_splits_on_chinese_comma(self):
        self.assertEqual(
            parse_comma_separated_list("tag:cat，tag:dog"),
            ["tag:cat", "tag:dog"],
        )

    def test_drops_empty_segments(self):
        self.assertEqual(
            parse_comma_separated_list("tag:cat,, ,tag:dog"),
            ["tag:cat", "tag:dog"],
        )

    def test_preserves_order(self):
        self.assertEqual(
            parse_comma_separated_list("tag:third,tag:first,tag:second"),
            ["tag:third", "tag:first", "tag:second"],
        )


class TestPhotoLibraryI18nKeys(unittest.TestCase):
    def test_all_locales_define_photo_library_keys(self):
        for locale in LOCALES:
            translations = _load_translation(locale)
            with self.subTest(locale=locale):
                missing = [key for key in PHOTO_LIBRARY_KEYS if key not in translations]
                self.assertEqual(missing, [])

    def test_photo_library_translations_are_non_empty(self):
        for locale in LOCALES:
            translations = _load_translation(locale)
            with self.subTest(locale=locale):
                for key in PHOTO_LIBRARY_KEYS:
                    self.assertTrue(str(translations[key]).strip())

    def test_photo_library_render_function_uses_translated_keys(self):
        tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
        render_fn = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_render_photo_library_settings"
        )

        used_keys = {
            call.args[0].value
            for call in ast.walk(render_fn)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "tr"
            and call.args
            and isinstance(call.args[0], ast.Constant)
        }

        self.assertEqual(used_keys, set(PHOTO_LIBRARY_KEYS))


if __name__ == "__main__":
    unittest.main()
