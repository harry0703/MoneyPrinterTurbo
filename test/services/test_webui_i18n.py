import ast
import json
from pathlib import Path
import unittest

from app.utils import utils


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
I18N_DIR = ROOT_DIR / "webui" / "i18n"
LLM_PROVIDER_TIPS_PREFIX = "llm_provider_tips."
TTS_PROVIDER_TIPS_PREFIX = "tts_provider_tips."


class _TrKeyVisitor(ast.NodeVisitor):
    def __init__(self):
        self.keys = set()

    def visit_Call(self, node):
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "tr"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            self.keys.add(node.args[0].value)
        self.generic_visit(node)


def _load_translation(locale):
    data = json.loads((I18N_DIR / f"{locale}.json").read_text(encoding="utf-8"))
    return data.get("Translation", {})


class TestWebuiI18n(unittest.TestCase):
    def test_saved_ui_language_takes_priority_over_browser_locale(self):
        language = utils.resolve_ui_language(
            saved_language="de",
            browser_locale="zh-CN",
            supported_languages=["zh", "en", "de"],
        )

        self.assertEqual(language, "de")

    def test_browser_locale_is_normalized_to_supported_base_language(self):
        self.assertEqual(
            utils.resolve_ui_language("", "zh-CN", ["zh", "en"]),
            "zh",
        )
        self.assertEqual(
            utils.resolve_ui_language(None, "pt_BR", ["en", "pt"]),
            "pt",
        )

    def test_unsupported_browser_locale_falls_back_to_english(self):
        language = utils.resolve_ui_language(
            saved_language="",
            browser_locale="fr-FR",
            supported_languages=["zh", "en"],
        )

        self.assertEqual(language, "en")

    def test_english_locale_covers_static_webui_labels(self):
        tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
        visitor = _TrKeyVisitor()
        visitor.visit(tree)

        en_keys = set(_load_translation("en"))

        self.assertEqual(sorted(visitor.keys - en_keys), [])

    def test_russian_locale_covers_english_locale(self):
        en_keys = set(_load_translation("en"))
        ru_keys = set(_load_translation("ru"))
        # Provider 配置说明只维护中英文，俄语及其它 locale 运行时统一回退英文。
        # 这里排除动态 tips key，避免继续复制一整套不会被读取的英文文案。
        required_en_keys = {
            key
            for key in en_keys
            if not key.startswith(
                (LLM_PROVIDER_TIPS_PREFIX, TTS_PROVIDER_TIPS_PREFIX)
            )
        }

        self.assertEqual(sorted(required_en_keys - ru_keys), [])

    def test_russian_locale_only_contains_required_codex_oauth_provider_tip(self):
        ru_keys = set(_load_translation("ru"))

        self.assertEqual(
            sorted(
                key for key in ru_keys if key.startswith(LLM_PROVIDER_TIPS_PREFIX)
            ),
            ["llm_provider_tips.codex_oauth"],
        )

        self.assertEqual(
            sorted(
                key for key in ru_keys if key.startswith(TTS_PROVIDER_TIPS_PREFIX)
            ),
            [],
        )

    def test_russian_locale_covers_static_webui_labels(self):
        tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
        visitor = _TrKeyVisitor()
        visitor.visit(tree)

        ru_keys = set(_load_translation("ru"))

        self.assertEqual(sorted(visitor.keys - ru_keys), [])

    def test_script_language_options_include_russian(self):
        tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
        support_locales = None

        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if any(
                isinstance(target, ast.Name) and target.id == "support_locales"
                for target in node.targets
            ):
                support_locales = ast.literal_eval(node.value)
                break

        self.assertIsNotNone(support_locales)
        self.assertIn("ru-RU", support_locales)
