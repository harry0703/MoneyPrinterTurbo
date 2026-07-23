import ast
import json
import re
import unittest
from pathlib import Path

from app.utils import utils


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
I18N_DIR = ROOT_DIR / "webui" / "i18n"
LLM_PROVIDER_TIPS_PREFIX = "llm_provider_tips."
TTS_PROVIDER_TIPS_PREFIX = "tts_provider_tips."
SECONDARY_LOCALES = ("de", "es", "id", "pt", "ru", "tr", "vi")
PROVIDER_TIPS_PREFIXES = (
    LLM_PROVIDER_TIPS_PREFIX,
    TTS_PROVIDER_TIPS_PREFIX,
)
FORMAT_PLACEHOLDER_PATTERN = re.compile(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})")
MARKDOWN_URL_PATTERN = re.compile(r"\[[^\]]+\]\((https?://[^)]+)\)")


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


def _required_translation_keys(translations):
    """返回二级语言必须维护的 key，Provider 长说明统一回退英文。"""
    return {key for key in translations if not key.startswith(PROVIDER_TIPS_PREFIXES)}


def _format_placeholders(value):
    """提取运行时格式化变量，防止翻译遗漏或误改变量名。"""
    return set(FORMAT_PLACEHOLDER_PATTERN.findall(value))


def _markdown_urls(value):
    """提取 Markdown 链接目标，允许翻译链接文字但不允许改坏地址。"""
    return set(MARKDOWN_URL_PATTERN.findall(value))


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

    def test_secondary_locales_cover_english_locale(self):
        en_translations = _load_translation("en")
        required_en_keys = _required_translation_keys(en_translations)

        for locale in SECONDARY_LOCALES:
            with self.subTest(locale=locale):
                locale_keys = set(_load_translation(locale))
                self.assertEqual(sorted(required_en_keys - locale_keys), [])

    def test_secondary_locales_do_not_duplicate_provider_tips(self):
        # Provider 配置长说明只维护中英文，其它语言运行时回退英文。
        # 禁止复制这些 key，避免出现不会持续维护的半翻译内容。
        for locale in SECONDARY_LOCALES:
            with self.subTest(locale=locale):
                locale_keys = set(_load_translation(locale))
                duplicated_keys = sorted(
                    key for key in locale_keys if key.startswith(PROVIDER_TIPS_PREFIXES)
                )
                self.assertEqual(duplicated_keys, [])

    def test_secondary_locales_cover_static_webui_labels(self):
        tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
        visitor = _TrKeyVisitor()
        visitor.visit(tree)

        for locale in SECONDARY_LOCALES:
            with self.subTest(locale=locale):
                locale_keys = set(_load_translation(locale))
                self.assertEqual(sorted(visitor.keys - locale_keys), [])

    def test_secondary_locales_preserve_format_placeholders(self):
        en_translations = _load_translation("en")

        for locale in SECONDARY_LOCALES:
            locale_translations = _load_translation(locale)
            for key in _required_translation_keys(en_translations):
                with self.subTest(locale=locale, key=key):
                    self.assertEqual(
                        _format_placeholders(locale_translations[key]),
                        _format_placeholders(en_translations[key]),
                    )

    def test_secondary_locales_preserve_markdown_urls(self):
        en_translations = _load_translation("en")

        for locale in SECONDARY_LOCALES:
            locale_translations = _load_translation(locale)
            for key in _required_translation_keys(en_translations):
                with self.subTest(locale=locale, key=key):
                    self.assertEqual(
                        _markdown_urls(locale_translations[key]),
                        _markdown_urls(en_translations[key]),
                    )

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

    def test_aimlapi_oauth_copy_and_form_order_match_settings_design(self):
        translations = _load_translation("en")
        self.assertEqual(
            translations["llm_provider_label.aimlapi"],
            "aimlapi.com (Recommended)",
        )
        self.assertEqual(
            translations["llm_provider_label.moonshot"],
            "Kimi / Moonshot AI (Recommended)",
        )
        self.assertEqual(translations["AIMLAPI Get API Key"], "Get API Key")
        self.assertEqual(
            translations["AIMLAPI Key Added"],
            "Your key has already been generated and added above.",
        )
        self.assertEqual(
            translations["AIMLAPI Sign In Failed"],
            "Sign in failed, please try again.",
        )

        source = WEBUI_MAIN.read_text(encoding="utf-8")
        function_start = source.index("def _render_aimlapi_api_key_controls")
        function_end = source.index("\ndef get_tts_provider_tips", function_start)
        function_source = source[function_start:function_end]
        self.assertLess(
            function_source.index('key="aimlapi_api_key_input"'),
            function_source.index('key="aimlapi_get_api_key_button"'),
        )
        self.assertIn("aimlapi_auth.start_authorization()", function_source)
        self.assertIn("aimlapi_auth.poll_authorization(authorization)", function_source)
