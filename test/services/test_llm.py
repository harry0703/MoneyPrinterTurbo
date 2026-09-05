import json
import os
import sys
import tempfile
import tomllib
import types
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.models.llm_provider import (
    DEFAULT_LLM_PROVIDER_ID,
    LLM_PROVIDER_REGISTRY,
    LLM_PROVIDERS,
    get_llm_provider,
    normalize_provider_override,
)
from app.models.schema import VideoScriptRequest, VideoSocialMetadataRequest
from app.services import llm

RUN_INTEGRATION_TESTS = os.environ.get("MPT_RUN_INTEGRATION_TESTS", "").lower() in {
    "1",
    "true",
    "yes",
}


class TestScriptPromptOptions(unittest.TestCase):
    def test_normalize_text_response_preserves_internal_newlines(self):
        """
        归一化只清理首尾空白，不能删除正文内部的换行。双换行用于区分脚本
        段落，单换行也可能是模型按语义返回的字幕行。
        """
        result = llm._normalize_text_response(
            "\n  第一行\n第二行\n\n第三段  \n",
            "openai",
        )

        self.assertEqual(result, "第一行\n第二行\n\n第三段")

    def test_normalize_text_response_removes_think_blocks(self):
        """
        reasoning 模型可能返回 `<think>...</think>`。脚本生成链路必须只保留
        最终正文，避免思考过程进入字幕和配音。
        """
        result = llm._normalize_text_response(
            "<think>\nI should reason here.\n</think>\n测试成功",
            "minimax",
        )

        self.assertEqual(result, "测试成功")

    def test_normalize_text_response_rejects_think_only_response(self):
        """
        如果模型只返回思考块而没有最终答案，应视为空内容，触发重试或明确错误。
        """
        with self.assertRaises(ValueError):
            llm._normalize_text_response("<think>hidden reasoning</think>", "minimax")

    def test_normalize_text_response_removes_unclosed_think_block(self):
        """
        某些网关可能因为截断只返回未闭合的 `<think>`。这种内容同样不能
        进入最终脚本；如果清理后没有正文，就应该按空响应处理。
        """
        with self.assertRaises(ValueError):
            llm._normalize_text_response("<think>hidden reasoning", "minimax")

    def test_build_script_prompt_appends_advanced_requirements(self):
        """
        高级文案要求只作为附加约束，不替换默认系统提示词。
        这样普通用户不配置时仍然走稳定默认规则，高级用户也能细化风格。
        """
        prompt = llm.build_script_prompt(
            video_subject="咖啡",
            language="zh-CN",
            paragraph_number=3,
            video_script_prompt="语气轻松，面向程序员",
        )

        self.assertIn("# Role: Video Script Generator", prompt)
        self.assertIn("- video subject: 咖啡", prompt)
        self.assertIn("- number of paragraphs: 3", prompt)
        self.assertIn("- language: zh-CN", prompt)
        self.assertIn("# Additional User Requirements:", prompt)
        self.assertIn("语气轻松，面向程序员", prompt)

    def test_custom_system_prompt_keeps_runtime_context(self):
        """
        自定义 system prompt 会替换默认脚本规则，但视频主题、语言、段落数
        仍由服务层统一追加，避免高级用户漏写必要上下文。
        """
        prompt = llm.build_script_prompt(
            video_subject="露营",
            language="en",
            paragraph_number=2,
            custom_system_prompt="Only write cinematic narration.",
        )

        self.assertNotIn("# Role: Video Script Generator", prompt)
        self.assertIn("Only write cinematic narration.", prompt)
        self.assertIn("- video subject: 露营", prompt)
        self.assertIn("- number of paragraphs: 2", prompt)
        self.assertIn("- language: en", prompt)

    def test_generate_script_sends_custom_prompt_to_llm(self):
        captured = {}

        def fake_generate_response(prompt):
            captured["prompt"] = prompt
            return "第一段。\n\n第二段。"

        with patch.object(
            llm, "_generate_response", side_effect=fake_generate_response
        ):
            result = llm.generate_script(
                video_subject="咖啡",
                language="zh-CN",
                paragraph_number=2,
                video_script_prompt="开头更有悬念",
            )

        self.assertEqual(result, "第一段。\n\n第二段。")
        self.assertIn("- number of paragraphs: 2", captured["prompt"])
        self.assertIn("开头更有悬念", captured["prompt"])

    def test_generate_script_reuses_submitted_config_snapshot(self):
        """WebUI 后台任务结束后应用新配置，不能改变正在重试的模型请求。"""
        captured = {}
        app_config = {
            "llm_provider": "openai",
            "openai_api_key": "snapshot-key",
            "openai_model_name": "snapshot-model",
        }

        def fake_generate_response(prompt, app_config=None):
            captured["prompt"] = prompt
            captured["app_config"] = app_config
            return "Snapshot response"

        with patch.object(
            llm, "_generate_response", side_effect=fake_generate_response
        ):
            result = llm.generate_script(
                video_subject="Snapshot test",
                app_config=app_config,
            )

        self.assertEqual(result, "Snapshot response")
        self.assertIs(captured["app_config"], app_config)
        self.assertEqual(captured["app_config"]["openai_api_key"], "snapshot-key")

    def test_generate_script_strips_each_bracket_group_independently(self):
        """
        format_response must remove each [bracket] and (paren) group in
        isolation.  The greedy form [.*] matches from the first opener to
        the *last* closer on the line, silently deleting all text in between.

        Example – greedy bug:
            "[Intro] Great content [end]"  →  "."     (all inner text lost)
        Expected with non-greedy fix:
            "[Intro] Great content [end]"  →  " Great content "
        """

        def fake_generate_response(prompt):
            # Two bracket groups and two paren groups on the same line.
            return (
                "[Scene: Beach] A beautiful day at the [location: ocean].\n\n"
                "Save (at least) 10% of your income (monthly)."
            )

        with patch.object(
            llm, "_generate_response", side_effect=fake_generate_response
        ):
            result = llm.generate_script(video_subject="savings tips", language="en-US")

        # Each bracket / paren group should be gone, but the surrounding words
        # must survive.
        self.assertNotIn("[", result)
        self.assertNotIn("]", result)
        self.assertNotIn("(", result)
        self.assertNotIn(")", result)
        self.assertIn("A beautiful day at the", result)
        self.assertIn("10% of your income", result)

    def test_generate_terms_can_request_script_ordered_keywords(self):
        """
        按文案顺序匹配素材依赖 LLM 返回有序关键词。这里不调用真实模型，
        只验证服务层会把“按脚本叙事顺序输出”的约束写入 prompt，避免
        后续素材下载虽然顺序化，但关键词仍然是全局无序主题词。
        """
        captured = {}

        def fake_generate_response(prompt):
            captured["prompt"] = prompt
            return '["opening city", "middle office", "final sunset"]'

        with patch.object(
            llm, "_generate_response", side_effect=fake_generate_response
        ):
            result = llm.generate_terms(
                video_subject="startup story",
                video_script="First city. Then office. Finally sunset.",
                amount=3,
                match_script_order=True,
            )

        self.assertEqual(result, ["opening city", "middle office", "final sunset"])
        self.assertIn("chronological stock-video search terms", captured["prompt"])
        self.assertIn("same order as the script narration", captured["prompt"])

    def test_generate_terms_returns_empty_list_on_provider_error(self):
        """
        Provider 错误必须保持 generate_terms 的 List[str] 返回契约。

        非空的 ``Error: ...`` 字符串在 Python 中是真值；如果直接返回，任务层
        会把它当成有效关键词，素材下载层随后还可能逐字符发起搜索请求。
        """
        with patch.object(
            llm,
            "_generate_response",
            return_value="Error: invalid API key",
        ):
            result = llm.generate_terms(
                video_subject="startup story",
                video_script="A short startup story.",
            )

        self.assertEqual(result, [])
        self.assertIsInstance(result, list)

    def test_video_script_request_rejects_invalid_advanced_options(self):
        """
        API 请求模型需要限制高级 prompt 参数，避免外部调用绕过 WebUI
        传入异常段落数或超长提示词，导致模型成本和结果不可控。
        """
        with self.assertRaises(ValidationError):
            VideoScriptRequest(video_subject="咖啡", paragraph_number=0)

        with self.assertRaises(ValidationError):
            VideoScriptRequest(
                video_subject="咖啡",
                video_script_prompt="x" * (llm.MAX_SCRIPT_PROMPT_LENGTH + 1),
            )


class TestLLMConnection(unittest.TestCase):
    def test_connection_sends_one_minimal_request(self):
        """连接测试只发送一次固定最小请求，不触发脚本生成重试。"""
        with (
            patch.object(llm, "_generate_response", return_value="OK") as generate,
            patch.object(llm, "perf_counter", side_effect=[10.0, 10.25]),
        ):
            result = llm.test_connection()

        generate.assert_called_once_with(prompt="Reply with exactly: OK")
        self.assertEqual(result, (True, "", 0.25))

    def test_connection_returns_provider_error(self):
        """Provider 返回错误时应保留可诊断信息，并报告本次请求耗时。"""
        with (
            patch.object(
                llm,
                "_generate_response",
                return_value="Error: invalid API key",
            ),
            patch.object(llm, "perf_counter", side_effect=[20.0, 20.5]),
        ):
            result = llm.test_connection()

        self.assertEqual(result, (False, "invalid API key", 0.5))

    def test_connection_rejects_empty_response(self):
        """极端情况下的空响应应显示明确错误，而不是误报连接成功。"""
        with (
            patch.object(llm, "_generate_response", return_value=""),
            patch.object(llm, "perf_counter", side_effect=[30.0, 31.0]),
        ):
            result = llm.test_connection()

        self.assertEqual(result, (False, "LLM returned an empty response", 1.0))


class TestLiteLLMProvider(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def test_current_default_model_names(self):
        """WebUI 与服务层必须共享同一组默认模型，避免展示值和请求值漂移。"""
        self.assertEqual(get_llm_provider("openai").default_model, "gpt-5.5")
        anthropic = get_llm_provider("anthropic")
        self.assertEqual(anthropic.default_model, "claude-sonnet-5")
        self.assertEqual(anthropic.default_base_url, "https://api.anthropic.com/v1/")
        self.assertEqual(anthropic.adapter, "openai_compatible")
        self.assertTrue(anthropic.requires_api_key)
        self.assertEqual(get_llm_provider("aimlapi").default_model, "openai/gpt-5-5")
        self.assertEqual(get_llm_provider("deepseek").default_model, "deepseek-v4-pro")
        self.assertEqual(
            get_llm_provider("modelscope").default_model, "ZhipuAI/GLM-5.2"
        )
        self.assertEqual(
            get_llm_provider("gemini").default_model, "gemini-3.1-pro-preview"
        )
        openrouter = get_llm_provider("openrouter")
        self.assertEqual(openrouter.default_model, "minimax/minimax-m3:free")
        self.assertEqual(openrouter.default_base_url, "https://openrouter.ai/api/v1")
        self.assertEqual(openrouter.adapter, "openai_compatible")
        self.assertTrue(openrouter.requires_api_key)
        pollinations = get_llm_provider("pollinations")
        self.assertEqual(pollinations.default_model, "openai-fast")
        self.assertEqual(
            pollinations.default_base_url,
            "https://gen.pollinations.ai/v1",
        )
        self.assertTrue(pollinations.requires_api_key)
        self.assertEqual(pollinations.adapter, "openai_compatible")

    def test_provider_defaults_are_not_persisted_as_user_overrides(self):
        """默认值只用于运行和展示，只有不同值才应写入用户配置。"""
        self.assertEqual(
            normalize_provider_override("gpt-5.5", "gpt-5.5"),
            "",
        )
        self.assertEqual(
            normalize_provider_override("  gpt-5.5  ", "gpt-5.5"),
            "",
        )
        self.assertEqual(
            normalize_provider_override("gpt-5.6-custom", "gpt-5.5"),
            "gpt-5.6-custom",
        )

    def test_provider_registry_has_unique_stable_ids(self):
        """Registry 是 Provider 列表的唯一数据源，ID 必须唯一且默认项存在。"""
        provider_ids = [provider.provider_id for provider in LLM_PROVIDER_REGISTRY]

        self.assertEqual(len(provider_ids), len(set(provider_ids)))
        self.assertEqual(len(provider_ids), len(LLM_PROVIDERS))
        self.assertIn(DEFAULT_LLM_PROVIDER_ID, LLM_PROVIDERS)

    def test_provider_registry_preserves_product_group_order(self):
        """下拉顺序按推荐、原厂、聚合平台、本地部署和其它服务排列。"""
        self.assertEqual(
            [provider.provider_id for provider in LLM_PROVIDER_REGISTRY],
            [
                "moonshot",
                "openai",
                "anthropic",
                "gemini",
                "deepseek",
                "qwen",
                "azure",
                "volcengine",
                "grok",
                "minimax",
                "mimo",
                "shengsuanyun",
                "apimart",
                "cloudflare",
                "modelscope",
                "aihubmix",
                "aimlapi",
                "evolink",
                "openrouter",
                "ollama",
                "claude_code",
                "oneapi",
                "litellm",
                "groq",
                "pollinations",
            ],
        )
        self.assertEqual(
            get_llm_provider("gemini").default_label,
            "Google Gemini",
        )
        self.assertEqual(
            get_llm_provider("azure").default_label,
            "Microsoft Azure OpenAI",
        )
        shengsuanyun = get_llm_provider("shengsuanyun")
        self.assertEqual(
            shengsuanyun.api_key_url,
            "https://www.shengsuanyun.com/?from=CH_XUQ4OTSK",
        )
        self.assertEqual(
            shengsuanyun.default_model,
            "deepseek/deepseek-v4-flash",
        )
        apimart = get_llm_provider("apimart")
        self.assertEqual(
            apimart.api_key_url,
            "https://go.apimart.ai/gh-moneyprinterturbo",
        )
        self.assertEqual(apimart.default_model, "gpt-5.6-terra")
        self.assertEqual(apimart.default_base_url, "https://api.apimart.ai/v1")
        openrouter = get_llm_provider("openrouter")
        self.assertEqual(
            openrouter.api_key_url,
            "https://openrouter.ai/settings/keys",
        )
        self.assertEqual(openrouter.default_model, "minimax/minimax-m3:free")
        self.assertEqual(openrouter.default_base_url, "https://openrouter.ai/api/v1")

    def test_provider_registry_uses_conventional_locale_and_config_keys(self):
        """统一命名规则可避免 WebUI 为每个 Provider 增加硬编码映射。"""
        for provider in LLM_PROVIDER_REGISTRY:
            self.assertEqual(
                provider.label_key,
                f"llm_provider_label.{provider.provider_id}",
            )
            self.assertEqual(
                provider.tips_key,
                f"llm_provider_tips.{provider.provider_id}",
            )
            self.assertEqual(
                provider.config_key("api_key"),
                f"{provider.provider_id}_api_key",
            )

    def test_registry_replaces_deprecated_provider_models(self):
        """历史默认模型应自动迁移，避免升级后继续使用已移除的接入语义。"""
        cloudflare = get_llm_provider("cloudflare")
        gemini = get_llm_provider("gemini")

        self.assertEqual(
            cloudflare.resolve_model_name("@cf/meta/llama-3.1-8b-instruct"),
            "openai/gpt-4.1-mini",
        )
        self.assertEqual(
            gemini.resolve_model_name("gemini-pro"),
            "gemini-3.1-pro-preview",
        )
        self.assertEqual(
            cloudflare.resolve_model_name("anthropic/claude-sonnet-4-5"),
            "anthropic/claude-sonnet-4-5",
        )

        pollinations = get_llm_provider("pollinations")
        self.assertEqual(
            pollinations.resolve_model_name("default"),
            "openai-fast",
        )
        self.assertEqual(
            pollinations.resolve_base_url("https://text.pollinations.ai/openai"),
            "https://gen.pollinations.ai/v1",
        )
        self.assertEqual(
            pollinations.resolve_base_url("https://example.com/v1"),
            "https://example.com/v1",
        )

    def test_provider_tip_templates_accept_registry_defaults(self):
        """所有语言的 Provider 提示模板都必须能安全注入 Registry 默认值。"""
        i18n_dir = Path(__file__).parent.parent.parent / "webui" / "i18n"
        for locale_file in i18n_dir.glob("*.json"):
            translations = json.loads(locale_file.read_text(encoding="utf-8"))[
                "Translation"
            ]
            for provider in LLM_PROVIDER_REGISTRY:
                tips = translations.get(provider.tips_key, "")
                if not tips:
                    continue
                default_endpoint = provider.default_service_endpoint
                rendered = tips.format(
                    api_key_url=provider.effective_api_key_url(),
                    default_model=provider.default_model,
                    default_base_url=provider.effective_default_base_url,
                    model_docs_url=(
                        default_endpoint.model_docs_url if default_endpoint else ""
                    ),
                    docker_hint="",
                    **{
                        f"default_{field.config_suffix}": field.default_value
                        for field in provider.extra_fields
                    },
                )
                self.assertNotIn("{default_model}", rendered)
                self.assertNotIn("{default_base_url}", rendered)

    def test_primary_provider_tips_use_consistent_structure(self):
        """中英文配置说明统一展示 API Key、Base URL 和模型名称。"""
        i18n_dir = Path(__file__).parent.parent.parent / "webui" / "i18n"
        for language in ("zh", "en"):
            translations = json.loads(
                (i18n_dir / f"{language}.json").read_text(encoding="utf-8")
            )["Translation"]
            for provider in LLM_PROVIDER_REGISTRY:
                tips = translations[provider.tips_key]
                self.assertTrue(tips.startswith("##### "), provider.provider_id)
                self.assertIn("**API Key**", tips, provider.provider_id)
                self.assertIn("**Base Url**", tips, provider.provider_id)
                self.assertIn("**Model Name**", tips, provider.provider_id)

        zh_kimi_tips = json.loads((i18n_dir / "zh.json").read_text(encoding="utf-8"))[
            "Translation"
        ]["llm_provider_tips.moonshot"]
        self.assertIn("推荐理由：", zh_kimi_tips)
        self.assertIn("视频创作链路匹配", zh_kimi_tips)

    def test_required_api_key_providers_have_clickable_entry_points(self):
        """需要密钥的 Provider 必须提供统一申请入口，避免 WebUI 只给出文字。"""
        i18n_dir = Path(__file__).parent.parent.parent / "webui" / "i18n"
        locale_translations = {
            locale_file.stem: json.loads(locale_file.read_text(encoding="utf-8"))[
                "Translation"
            ]
            for locale_file in i18n_dir.glob("*.json")
        }

        for provider in LLM_PROVIDER_REGISTRY:
            if provider.requires_api_key:
                api_key_url = provider.effective_api_key_url()
                self.assertTrue(api_key_url, provider.provider_id)
                self.assertTrue(
                    api_key_url.startswith("https://"),
                    provider.provider_id,
                )
                for language, translations in locale_translations.items():
                    tips_template = translations.get(provider.tips_key, "")
                    if not tips_template:
                        continue
                    default_endpoint = provider.default_service_endpoint
                    tips = tips_template.format(
                        api_key_url=api_key_url,
                        default_model=provider.default_model,
                        default_base_url=provider.effective_default_base_url,
                        model_docs_url=(
                            default_endpoint.model_docs_url if default_endpoint else ""
                        ),
                        docker_hint="",
                        **{
                            f"default_{field.config_suffix}": field.default_value
                            for field in provider.extra_fields
                        },
                    )
                    api_key_line = next(
                        line for line in tips.splitlines() if "**API Key**" in line
                    )
                    self.assertIn("](", api_key_line, provider.provider_id)
                    self.assertIn(
                        f"]({api_key_url})",
                        api_key_line,
                        f"{language}: {provider.provider_id}",
                    )

    def test_service_endpoint_registry_references_valid_stable_ids(self):
        """服务区域必须通过唯一稳定 ID 关联，不能依赖链接或展示文案。"""
        for provider in LLM_PROVIDER_REGISTRY:
            endpoint_ids = [
                endpoint.endpoint_id for endpoint in provider.service_endpoints
            ]
            self.assertEqual(
                len(endpoint_ids),
                len(set(endpoint_ids)),
                provider.provider_id,
            )
            if not endpoint_ids:
                self.assertFalse(provider.default_service_endpoint_id)
                self.assertFalse(provider.international_service_endpoint_id)
                continue

            self.assertIn(provider.default_service_endpoint_id, endpoint_ids)
            if provider.international_service_endpoint_id:
                self.assertIn(provider.international_service_endpoint_id, endpoint_ids)

    def test_kimi_service_endpoint_selection_preserves_existing_configs(self):
        """已有 Kimi 配置不能因界面语言变化而被静默切换到另一套账号体系。"""
        provider = get_llm_provider("moonshot")

        china = provider.select_service_endpoint(
            "",
            has_api_key=True,
            prefer_international=True,
        )
        global_endpoint = provider.select_service_endpoint(
            "https://api.moonshot.ai/v1/",
            has_api_key=True,
            prefer_international=False,
        )

        self.assertEqual(china.endpoint_id, "china")
        self.assertEqual(global_endpoint.endpoint_id, "global")
        self.assertIsNone(
            provider.select_service_endpoint(
                "https://gateway.example.com/v1",
                has_api_key=True,
                prefer_international=True,
            )
        )

    def test_kimi_fresh_config_uses_interface_region(self):
        """新配置按界面语言推荐站点，但仍由用户在 WebUI 中明确选择。"""
        provider = get_llm_provider("moonshot")

        china = provider.select_service_endpoint(
            "",
            has_api_key=False,
            prefer_international=False,
        )
        global_endpoint = provider.select_service_endpoint(
            "",
            has_api_key=False,
            prefer_international=True,
        )

        self.assertEqual(china.base_url, "https://api.moonshot.cn/v1")
        self.assertEqual(global_endpoint.base_url, "https://api.moonshot.ai/v1")
        self.assertIn("platform.kimi.ai", global_endpoint.api_key_url)

    def test_kimi_endpoint_selection_does_not_depend_on_marketing_url(self):
        """更新推广参数不能改变国际站的业务选择结果。"""
        provider = get_llm_provider("moonshot")
        global_endpoint = replace(
            provider.international_service_endpoint,
            api_key_url="https://platform.kimi.ai/?new-tracking=1",
        )
        updated_provider = replace(
            provider,
            service_endpoints=tuple(
                global_endpoint if endpoint.endpoint_id == "global" else endpoint
                for endpoint in provider.service_endpoints
            ),
        )

        selected = updated_provider.select_service_endpoint(
            "",
            has_api_key=False,
            prefer_international=True,
        )

        self.assertEqual(selected.endpoint_id, "global")
        self.assertEqual(selected.api_key_url, global_endpoint.api_key_url)

    def test_example_config_does_not_duplicate_registry_defaults(self):
        """示例配置只保存用户覆盖值，默认模型和地址由 Registry 唯一维护。"""
        config_path = Path(__file__).parent.parent.parent / "config.example.toml"
        app_config = tomllib.loads(config_path.read_text(encoding="utf-8"))["app"]

        for provider in LLM_PROVIDER_REGISTRY:
            if provider.default_model:
                self.assertEqual(
                    app_config.get(provider.config_key("model_name"), ""),
                    "",
                    provider.provider_id,
                )
            if provider.effective_default_base_url:
                self.assertEqual(
                    app_config.get(provider.config_key("base_url"), ""),
                    "",
                    provider.provider_id,
                )
            for field in provider.extra_fields:
                if field.default_value:
                    self.assertEqual(
                        app_config.get(provider.config_key(field.config_suffix), ""),
                        "",
                        provider.provider_id,
                    )

    def test_removed_ernie_provider_is_unsupported(self):
        """移除 ERNIE 后，遗留配置应返回明确错误，不再发起旧 OAuth 请求。"""
        config.app["llm_provider"] = "ernie"

        with patch.object(llm, "OpenAI") as openai_client:
            result = llm._generate_response("test")

        openai_client.assert_not_called()
        self.assertIn("unsupported llm provider", result)

    def test_pollinations_requires_api_key_before_request(self):
        """新统一 API 要求鉴权，缺少 Key 时不得发送匿名生成请求。"""
        config.app.update(
            {
                "llm_provider": "pollinations",
                "pollinations_api_key": "",
                "pollinations_base_url": "",
                "pollinations_model_name": "",
            }
        )

        with patch.object(llm, "OpenAI") as openai_client:
            result = llm._generate_response("test")

        openai_client.assert_not_called()
        self.assertIn("api_key is not set", result)

    def test_pollinations_uses_unified_openai_compatible_api(self):
        """历史地址和模型名应自动迁移，并通过统一 Chat Completions API 调用。"""
        config.app.update(
            {
                "llm_provider": "pollinations",
                "pollinations_api_key": "pollinations-test-key",
                "pollinations_base_url": "https://text.pollinations.ai/openai/",
                "pollinations_model_name": "default",
            }
        )

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\npollinations")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="pollinations-test-key",
            base_url="https://gen.pollinations.ai/v1",
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "openai-fast",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\npollinations")

    def test_anthropic_uses_openai_compatible_chat_completions(self):
        """Claude 走 Anthropic 的 OpenAI 兼容端点，不需要额外适配器分支。"""
        config.app.update(
            {
                "llm_provider": "anthropic",
                "anthropic_api_key": "anthropic-test-key",
                "anthropic_base_url": "",
                "anthropic_model_name": "",
            }
        )

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\nclaude")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="anthropic-test-key",
            base_url="https://api.anthropic.com/v1/",
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "claude-sonnet-5",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\nclaude")

    def test_gemini_uses_google_genai_client(self):
        """Gemini 适配器应通过新版 SDK 的统一 Client 发起内容生成请求。"""
        config.app.update(
            {
                "llm_provider": "gemini",
                "gemini_api_key": "gemini-test-key",
                "gemini_base_url": "",
                "gemini_model_name": "gemini-test-model",
            }
        )
        captured = {}

        class FakeModels:
            def generate_content(self, **kwargs):
                captured.update(kwargs)
                return types.SimpleNamespace(text="hello\ngemini")

        class FakeClient:
            def __init__(self, **kwargs):
                captured["client_kwargs"] = kwargs
                self.models = FakeModels()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                captured["closed"] = True

        with patch("google.genai.Client", FakeClient):
            result = llm._generate_response("Say hello")

        self.assertEqual(result, "hello\ngemini")
        self.assertEqual(
            captured["client_kwargs"],
            {"api_key": "gemini-test-key", "http_options": None},
        )
        self.assertEqual(captured["model"], "gemini-test-model")
        self.assertEqual(captured["contents"], "Say hello")
        self.assertEqual(captured["config"].max_output_tokens, 2048)
        self.assertTrue(captured["closed"])

    def test_cloudflare_requires_account_id_before_request(self):
        """Cloudflare 缺少 Account ID 时应在本地失败，不发送无效请求。"""
        config.app.update(
            {
                "llm_provider": "cloudflare",
                "cloudflare_api_key": "test-token",
                "cloudflare_account_id": "",
                "cloudflare_model_name": "",
            }
        )

        with patch.object(llm, "OpenAI") as openai_client:
            result = llm._generate_response("test")

        openai_client.assert_not_called()
        self.assertIn("account_id is not set", result)

    def test_cloudflare_uses_ai_gateway_openai_endpoint(self):
        """Cloudflare Provider 必须走 AI Gateway，不再调用 Workers AI 接口。"""
        config.app.update(
            {
                "llm_provider": "cloudflare",
                "cloudflare_api_key": "cloudflare-token",
                "cloudflare_account_id": "account-123",
                "cloudflare_gateway_id": "",
                "cloudflare_model_name": "",
            }
        )

        fake_response = types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content="gateway\nresponse")
                )
            ]
        )

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return fake_response

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="cloudflare-token",
            base_url=(
                "https://api.cloudflare.com/client/v4/accounts/account-123/ai/v1"
            ),
            default_headers={"cf-aig-gateway-id": "default"},
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "openai/gpt-4.1-mini",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "gateway\nresponse")

    def _use_litellm_provider(self, model_name="openai/gpt-4o-mini"):
        config.app["llm_provider"] = "litellm"
        config.app["litellm_model_name"] = model_name

    def test_litellm_provider_returns_normalized_text(self):
        """
        验证 LiteLLM provider 的主路径不依赖真实网络和私有 API key。

        这里用 fake module 注入 `sys.modules`，直接覆盖动态 import 的
        `litellm.completion()`，确保测试稳定覆盖 `_generate_response()` 里的
        litellm 分支。
        """
        self._use_litellm_provider()

        fake_litellm = types.SimpleNamespace()

        def _completion(**kwargs):
            self.assertEqual(kwargs["model"], "openai/gpt-4o-mini")
            self.assertEqual(
                kwargs["messages"], [{"role": "user", "content": "Say hello"}]
            )
            self.assertTrue(kwargs["drop_params"])
            message = types.SimpleNamespace(content="hello\nworld")
            choice = types.SimpleNamespace(message=message)
            return types.SimpleNamespace(choices=[choice])

        fake_litellm.completion = _completion

        with patch.dict(sys.modules, {"litellm": fake_litellm}):
            result = llm._generate_response("Say hello")

        self.assertEqual(result, "hello\nworld")

    def test_litellm_provider_uses_registry_default_model(self):
        self._use_litellm_provider(model_name="")

        fake_litellm = types.SimpleNamespace()

        def _completion(**kwargs):
            self.assertEqual(kwargs["model"], "openai/gpt-4o-mini")
            message = types.SimpleNamespace(content="default model")
            choice = types.SimpleNamespace(message=message)
            return types.SimpleNamespace(choices=[choice])

        fake_litellm.completion = _completion

        with patch.dict(sys.modules, {"litellm": fake_litellm}):
            result = llm._generate_response("test")

        self.assertEqual(result, "default model")

    def test_litellm_provider_handles_empty_response(self):
        self._use_litellm_provider()

        fake_litellm = types.SimpleNamespace(
            completion=lambda **kwargs: types.SimpleNamespace(choices=[])
        )

        with patch.dict(sys.modules, {"litellm": fake_litellm}):
            result = llm._generate_response("test")

        self.assertIn("Error:", result)
        self.assertIn("returned empty response", result)

    def test_litellm_provider_handles_empty_message(self):
        """
        某些 OpenAI-compatible 网关在内容过滤或安全拦截时会返回
        HTTP 200，但 `choices[0].message` 为 None。这里必须返回
        可诊断的错误，而不是抛出 AttributeError。
        """
        self._use_litellm_provider()

        fake_litellm = types.SimpleNamespace(
            completion=lambda **kwargs: types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=None)]
            )
        )

        with patch.dict(sys.modules, {"litellm": fake_litellm}):
            result = llm._generate_response("test")

        self.assertIn("Error:", result)
        self.assertIn("returned empty message", result)

    def test_sanitize_error_message_redacts_url_credentials_and_query_tokens(self):
        message = (
            "request failed for "
            "https://myuser:mypassword@proxy.example.com/v1/chat"
            "?api_key=secret-key&token=secret-token&safe=value"
        )

        result = llm._sanitize_error_message(message)

        self.assertIn("https://***:***@proxy.example.com", result)
        self.assertIn("api_key=***", result)
        self.assertIn("token=***", result)
        self.assertIn("safe=value", result)
        self.assertNotIn("myuser", result)
        self.assertNotIn("mypassword", result)
        self.assertNotIn("secret-key", result)
        self.assertNotIn("secret-token", result)

    def test_openai_provider_error_redacts_embedded_base_url_credentials(self):
        """
        自定义 OpenAI-compatible base_url 可能包含代理网关的 user:pass。
        SDK 抛错时常会把 URL 带回异常信息，这里验证最终返回给 WebUI/API 的
        `Error:` 文案不会泄露这些凭据。
        """
        config.app["llm_provider"] = "groq"
        config.app["groq_api_key"] = "groq-key"
        config.app["groq_model_name"] = "llama-3.3-70b-versatile"
        config.app["groq_base_url"] = (
            "https://myuser:mypassword@proxy.example.com/openai/v1"
        )

        class FakeCompletions:
            def create(self, **kwargs):
                raise RuntimeError(
                    "connection failed: "
                    "https://myuser:mypassword@proxy.example.com/openai/v1"
                    "?access_token=secret-token"
                )

        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=FakeCompletions())
        )

        with patch.object(llm, "OpenAI", return_value=fake_client):
            result = llm._generate_response("test")

        self.assertIn("Error:", result)
        self.assertIn("https://***:***@proxy.example.com", result)
        self.assertIn("access_token=***", result)
        self.assertNotIn("myuser", result)
        self.assertNotIn("mypassword", result)
        self.assertNotIn("secret-token", result)

    def test_openai_provider_still_uses_existing_path(self):
        config.app["llm_provider"] = "openai"
        config.app["openai_api_key"] = ""
        config.app["openai_base_url"] = "https://api.openai.com/v1"
        config.app["openai_model_name"] = "gpt-4o-mini"

        result = llm._generate_response("test")

        self.assertIn("Error:", result)
        self.assertIn("api_key is not set", result)
        self.assertNotIn("litellm", result.lower())

    def _use_qwen_provider(self):
        config.app["llm_provider"] = "qwen"
        config.app["qwen_api_key"] = "qwen-key"
        config.app["qwen_model_name"] = "qwen-max"

    def _patch_dashscope_generation(self, response):
        class FakeGenerationResponse(dict):
            pass

        fake_response = FakeGenerationResponse(response)
        fake_response.status_code = response.get("status_code", 200)
        fake_dashscope = types.SimpleNamespace(
            api_key="",
            Generation=types.SimpleNamespace(call=lambda **kwargs: fake_response),
        )
        fake_dashscope_response = types.SimpleNamespace(
            GenerationResponse=FakeGenerationResponse
        )

        return patch.dict(
            sys.modules,
            {
                "dashscope": fake_dashscope,
                "dashscope.api_entities": types.SimpleNamespace(),
                "dashscope.api_entities.dashscope_response": fake_dashscope_response,
            },
        )

    def test_qwen_provider_reads_chat_choices_content(self):
        """
        DashScope chat 模式会把文本放在 `output.choices[0].message.content`。
        这里覆盖 issue #966 报告的 `output.text is None` 场景，避免再次触发
        `'NoneType' object has no attribute 'replace'`。
        """
        self._use_qwen_provider()
        response = {
            "output": {
                "text": None,
                "choices": [{"message": {"content": "你好\n世界"}}],
            }
        }

        with self._patch_dashscope_generation(response):
            result = llm._generate_response("Say hello")

        self.assertEqual(result, "你好\n世界")

    def test_qwen_provider_falls_back_to_output_text(self):
        """保留旧 DashScope completion 响应结构的兼容路径。"""
        self._use_qwen_provider()
        response = {"output": {"text": "旧格式\n响应"}}

        with self._patch_dashscope_generation(response):
            result = llm._generate_response("Say hello")

        self.assertEqual(result, "旧格式\n响应")

    def test_qwen_provider_reports_empty_text(self):
        """Qwen 空响应应返回可诊断错误，而不是底层 AttributeError。"""
        self._use_qwen_provider()
        response = {
            "output": {"text": None, "choices": [{"message": {"content": None}}]}
        }

        with self._patch_dashscope_generation(response):
            result = llm._generate_response("Say hello")

        self.assertIn("Error:", result)
        self.assertIn("returned empty text content", result)
        self.assertNotIn("NoneType", result)

    def test_qwen_provider_reports_empty_choices(self):
        """Qwen chat 响应 choices 为空时应返回明确错误。"""
        self._use_qwen_provider()
        response = {"output": {"text": None, "choices": []}}

        with self._patch_dashscope_generation(response):
            result = llm._generate_response("Say hello")

        self.assertIn("Error:", result)
        self.assertIn("returned empty choices", result)
        self.assertNotIn("NoneType", result)

    def test_apimart_provider_uses_unwrapped_openai_compatible_endpoint(self):
        """
        APIMart 文档同时展示 `/api/v1` 和 `/v1` 两组入口。前者的示例响应
        带有 code/data 外层包装，OpenAI SDK 无法直接从顶层读取 choices；
        LLM Provider 必须使用标准 `/v1` 地址，才能复用现有响应解析链路。
        """
        config.app["llm_provider"] = "apimart"
        config.app["apimart_api_key"] = "apimart-key"
        config.app["apimart_base_url"] = ""
        config.app["apimart_model_name"] = ""

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\napimart")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="apimart-key",
            base_url="https://api.apimart.ai/v1",
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "gpt-5.6-terra",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\napimart")

    def test_aihubmix_provider_uses_openai_compatible_client(self):
        """
        AIHubMix 是 OpenAI-compatible 网关。这里用 fake OpenAI client
        验证独立 Provider 会使用 Registry 中的默认地址和模型，避免真实网络
        或私有 API Key 影响测试稳定性。
        """
        config.app["llm_provider"] = "aihubmix"
        config.app["aihubmix_api_key"] = "aihubmix-key"
        config.app["aihubmix_base_url"] = ""
        config.app["aihubmix_model_name"] = ""

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\naihubmix")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="aihubmix-key",
            base_url="https://aihubmix.com/v1",
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "gpt-5.4-mini",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\naihubmix")

    def test_aimlapi_provider_uses_openai_compatible_client(self):
        config.app["llm_provider"] = "aimlapi"
        config.app["aimlapi_api_key"] = "aimlapi-key"
        config.app["aimlapi_base_url"] = ""
        config.app["aimlapi_model_name"] = ""

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\naimlapi")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="aimlapi-key",
            base_url="https://api.aimlapi.com/v1",
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "openai/gpt-5-5",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\naimlapi")

    def test_evolink_provider_uses_openai_compatible_client(self):
        """
        EvoLink exposes OpenAI-compatible Chat Completions at direct.evolink.ai.
        The provider should keep its own default endpoint and model instead of
        requiring users to overload the generic OpenAI settings.
        """
        config.app["llm_provider"] = "evolink"
        config.app["evolink_api_key"] = "evolink-key"
        config.app["evolink_base_url"] = ""
        config.app["evolink_model_name"] = ""

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\nevolink")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="evolink-key",
            base_url="https://direct.evolink.ai/v1",
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "gpt-5.5",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\nevolink")

    def test_openrouter_provider_uses_openai_compatible_client(self):
        """
        OpenRouter exposes OpenAI-compatible Chat Completions through one
        unified endpoint. The default model stays on a currently free text model
        suitable for script and keyword generation.
        """
        config.app["llm_provider"] = "openrouter"
        config.app["openrouter_api_key"] = "openrouter-key"
        config.app["openrouter_base_url"] = ""
        config.app["openrouter_model_name"] = ""

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\nopenrouter")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="openrouter-key",
            base_url="https://openrouter.ai/api/v1",
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "minimax/minimax-m3:free",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\nopenrouter")

    def test_volcengine_provider_uses_openai_compatible_client(self):
        """
        VolcEngine Ark 暴露 OpenAI-compatible Chat Completions。
        这里用 fake OpenAI client 覆盖 provider 默认地址和默认模型，
        避免真实网络或私有 API key 影响测试稳定性。
        """
        config.app["llm_provider"] = "volcengine"
        config.app["volcengine_api_key"] = "volcengine-key"
        config.app["volcengine_base_url"] = ""
        config.app["volcengine_model_name"] = ""

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\nvolcengine")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="volcengine-key",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "doubao-seed-2-1-turbo-260628",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\nvolcengine")

    def test_grok_provider_still_uses_existing_path(self):
        config.app["llm_provider"] = "grok"
        config.app["grok_api_key"] = ""
        config.app["grok_base_url"] = "https://api.x.ai/v1"
        config.app["grok_model_name"] = "grok-4.3"

        result = llm._generate_response("test")

        self.assertIn("Error:", result)
        self.assertIn("api_key is not set", result)
        self.assertNotIn("litellm", result.lower())

    def test_groq_provider_requires_api_key(self):
        config.app["llm_provider"] = "groq"
        config.app["groq_api_key"] = ""
        config.app["groq_base_url"] = "https://api.groq.com/openai/v1"
        config.app["groq_model_name"] = "llama-3.3-70b-versatile"

        result = llm._generate_response("test")

        self.assertIn("Error:", result)
        self.assertIn("api_key is not set", result)
        self.assertNotIn("litellm", result.lower())

    def test_groq_provider_uses_default_base_url(self):
        config.app["llm_provider"] = "groq"
        config.app["groq_api_key"] = "groq-test-key"
        config.app["groq_base_url"] = ""
        config.app["groq_model_name"] = "llama-3.3-70b-versatile"

        fake_response = types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content="hello\ngroq")
                )
            ]
        )
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=types.SimpleNamespace(create=lambda **kwargs: fake_response)
            )
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="groq-test-key",
            base_url="https://api.groq.com/openai/v1",
        )
        self.assertEqual(result, "hello\ngroq")

    def _use_ollama_provider(self, base_url=""):
        config.app["llm_provider"] = "ollama"
        config.app["ollama_api_key"] = ""
        config.app["ollama_base_url"] = base_url
        config.app["ollama_model_name"] = "llama3"

    def _assert_ollama_base_url(self, expected_base_url: str):
        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\nollama")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="ollama",
            base_url=expected_base_url,
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "llama3",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\nollama")

    def test_ollama_default_base_url_uses_localhost_outside_container(self):
        """
        普通本机运行时，Ollama 默认仍然使用 localhost，避免影响已有用户。
        """
        self._use_ollama_provider()

        with patch.object(config, "is_running_in_container", return_value=False):
            self._assert_ollama_base_url("http://localhost:11434/v1")

    def test_ollama_default_base_url_uses_host_gateway_inside_container(self):
        """
        容器内运行时，localhost 指向容器自身；默认改为 host.docker.internal，
        方便 Docker Desktop 用户访问宿主机上的 Ollama。
        """
        self._use_ollama_provider()

        with (
            patch.object(config, "is_running_in_container", return_value=True),
            patch.object(config, "_can_resolve_hostname", return_value=True),
        ):
            self._assert_ollama_base_url("http://host.docker.internal:11434/v1")

    def test_ollama_default_base_url_falls_back_to_container_gateway(self):
        """
        原生 Linux Docker 里不一定能解析 host.docker.internal。此时使用容器
        默认网关作为兜底地址，比直接返回不可解析的 hostname 更稳。
        """
        self._use_ollama_provider()

        with (
            patch.object(config, "is_running_in_container", return_value=True),
            patch.object(config, "_can_resolve_hostname", return_value=False),
            patch.object(
                config, "get_container_default_gateway_ip", return_value="172.17.0.1"
            ),
        ):
            self._assert_ollama_base_url("http://172.17.0.1:11434/v1")

    def test_ollama_explicit_base_url_takes_precedence(self):
        """
        用户手动配置的 ollama_base_url 优先级最高，不受容器检测影响。
        """
        self._use_ollama_provider(base_url="http://ollama:11434/v1")

        with patch.object(config, "is_running_in_container", return_value=True):
            self._assert_ollama_base_url("http://ollama:11434/v1")

    def test_mimo_provider_uses_openai_compatible_client(self):
        """
        MiMo 官方接口兼容 OpenAI Chat Completions 协议。这里用 fake OpenAI
        client 验证 provider 会使用 MiMo 独立配置和默认 base_url，不依赖
        真实网络或私有 API Key。
        """
        config.app["llm_provider"] = "mimo"
        config.app["mimo_api_key"] = "mimo-key"
        config.app["mimo_base_url"] = ""
        config.app["mimo_model_name"] = ""

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\nmimo")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "OpenAI", return_value=fake_client) as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        openai_client.assert_called_once_with(
            api_key="mimo-key",
            base_url="https://api.xiaomimimo.com/v1",
        )
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "mimo-v2.5-pro",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\nmimo")

    def test_azure_provider_uses_azure_client_directly(self):
        """
        Azure OpenAI 的鉴权、endpoint 和 api-version 都由 AzureOpenAI 客户端处理。
        这个测试覆盖 issue #892：azure 分支必须直接调用 AzureOpenAI 创建的客户端，
        不能继续落入普通 OpenAI-compatible 分支，否则会丢失 Azure 专用请求配置。
        """
        config.app["llm_provider"] = "azure"
        config.app["azure_api_key"] = "azure-key"
        config.app["azure_base_url"] = "https://example.openai.azure.com"
        config.app["azure_model_name"] = "gpt-4o-mini"
        config.app["azure_api_version"] = "2024-02-15-preview"

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content="hello\nazure")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        fake_completions = FakeCompletions()
        fake_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=fake_completions)
        )

        with (
            patch.object(llm, "AzureOpenAI", return_value=fake_client) as azure_client,
            patch.object(llm, "OpenAI") as openai_client,
            patch.object(llm, "ChatCompletion", types.SimpleNamespace),
        ):
            result = llm._generate_response("Say hello")

        azure_client.assert_called_once_with(
            api_key="azure-key",
            api_version="2024-02-15-preview",
            azure_endpoint="https://example.openai.azure.com",
        )
        openai_client.assert_not_called()
        self.assertEqual(
            fake_completions.kwargs,
            {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Say hello"}],
            },
        )
        self.assertEqual(result, "hello\nazure")

    def test_unsupported_provider_returns_clear_error(self):
        config.app["llm_provider"] = "g" + "4f"

        result = llm._generate_response("test")

        self.assertIn("Error:", result)
        self.assertIn("unsupported llm provider", result)


class TestClaudeCodeProvider(unittest.TestCase):
    """claude_code Provider 通过本机 claude CLI 调用订阅账号，不走 HTTP API。"""

    def setUp(self):
        self.original_app_config = dict(config.app)
        config.app["llm_provider"] = "claude_code"
        config.app["claude_code_model_name"] = ""
        config.app["claude_code_cli_path"] = ""
        config.app["claude_code_timeout"] = ""

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    @staticmethod
    def _completed(stdout="", stderr="", returncode=0):
        return types.SimpleNamespace(
            stdout=stdout, stderr=stderr, returncode=returncode
        )

    @staticmethod
    def _cli_payload(result, is_error=False):
        return json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": is_error,
                "result": result,
            }
        )

    # ------------------------------------------------------------- success
    def test_successful_generation_returns_cli_result_text(self):
        """CLI 返回的 JSON 中只有 result 是正文，其余字段不应泄漏到脚本里。"""
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess,
                "run",
                return_value=self._completed(stdout=self._cli_payload("Hello world")),
            ) as run,
        ):
            self.assertEqual(llm._generate_response("write something"), "Hello world")

        command = run.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/claude")
        self.assertIn("-p", command)
        self.assertEqual(
            run.call_args.kwargs["timeout"], llm.CLAUDE_CODE_DEFAULT_TIMEOUT
        )

    def test_generation_disables_tools_and_user_customizations(self):
        """纯文本生成必须关闭全部工具和用户级定制，避免读写文件或加载 skills。"""
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess,
                "run",
                return_value=self._completed(stdout=self._cli_payload("ok")),
            ) as run,
        ):
            llm._generate_response("write something")

        command = run.call_args.args[0]
        self.assertIn("--tools", command)
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertIn("--safe-mode", command)
        self.assertIn("--system-prompt", command)
        self.assertEqual(
            command[command.index("--system-prompt") + 1],
            llm.CLAUDE_CODE_SYSTEM_PROMPT,
        )

    def test_model_name_is_only_passed_when_configured(self):
        """模型名留空时应沿用 CLI 默认模型，而不是硬编码一个可能失效的 ID。"""
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess,
                "run",
                return_value=self._completed(stdout=self._cli_payload("ok")),
            ) as run,
        ):
            llm._generate_response("write something")
            self.assertNotIn("--model", run.call_args.args[0])

            config.app["claude_code_model_name"] = "claude-opus-5"
            llm._generate_response("write something")
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--model") + 1], "claude-opus-5")

    # ------------------------------------------------- credential isolation
    def test_conflicting_credentials_are_removed_from_subprocess_env(self):
        """环境里的 API Key 会让 CLI 绕过订阅登录并产生 API 计费，必须剔除。"""
        polluted = {
            "PATH": "/usr/bin",
            "ANTHROPIC_API_KEY": "sk-ant-api03-should-not-be-used",
            "ANTHROPIC_BASE_URL": "https://proxy.example.com",
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-subscription",
        }
        env, removed = llm.build_claude_code_env(polluted)

        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertNotIn("CLAUDE_CODE_USE_BEDROCK", env)
        # 订阅令牌是容器内唯一的鉴权方式，必须保留。
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], "sk-ant-oat01-subscription")
        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertCountEqual(
            removed,
            ["ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK"],
        )

    def test_every_cloud_provider_switch_is_removed(self):
        """Bedrock / Vertex / Foundry / Mantle / Gateway 等开关都会改走云厂商计费。"""
        switches = {
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "CLAUDE_CODE_USE_VERTEX": "1",
            "CLAUDE_CODE_USE_FOUNDRY": "1",
            "CLAUDE_CODE_USE_MANTLE": "1",
            "CLAUDE_CODE_USE_GATEWAY": "1",
            "CLAUDE_CODE_USE_ANTHROPIC_AWS": "1",
            "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD": "1",
        }
        env, removed = llm.build_claude_code_env({"PATH": "/usr/bin", **switches})

        self.assertEqual(env, {"PATH": "/usr/bin"})
        self.assertCountEqual(removed, list(switches))

    def test_foundry_credentials_are_removed(self):
        """Foundry 凭证会让 CLI 走 Azure 计费，凭证和开关都必须剔除。"""
        foundry = {
            "CLAUDE_CODE_USE_FOUNDRY": "1",
            "ANTHROPIC_FOUNDRY_API_KEY": "foundry-key",
            "ANTHROPIC_FOUNDRY_AUTH_TOKEN": "foundry-token",
            "ANTHROPIC_FOUNDRY_BASE_URL": "https://example.openai.azure.com",
            "ANTHROPIC_FOUNDRY_RESOURCE": "my-resource",
            "CLAUDE_CODE_SKIP_FOUNDRY_AUTH": "1",
        }
        env, removed = llm.build_claude_code_env(
            {"PATH": "/usr/bin", "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01", **foundry}
        )

        for name in foundry:
            self.assertNotIn(name, env, name)
        self.assertCountEqual(removed, list(foundry))
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], "sk-ant-oat01")

    def test_auth_bypass_switches_are_removed(self):
        """CLAUDE_CODE_SKIP_*_AUTH 会跳过供应商鉴权，同样不能带进子进程。"""
        bypasses = {
            "CLAUDE_CODE_SKIP_BEDROCK_AUTH": "1",
            "CLAUDE_CODE_SKIP_VERTEX_AUTH": "1",
            "CLAUDE_CODE_SKIP_MANTLE_AUTH": "1",
            "CLAUDE_CODE_SKIP_ANTHROPIC_AWS_AUTH": "1",
        }
        env, removed = llm.build_claude_code_env({"PATH": "/usr/bin", **bypasses})
        self.assertEqual(env, {"PATH": "/usr/bin"})
        self.assertCountEqual(removed, list(bypasses))

    def test_credential_location_variables_are_preserved(self):
        """*_CONFIG_DIR 只指明凭证位置，剔除反而会让已登录的订阅失效。"""
        preserved = {
            "ANTHROPIC_CONFIG_DIR": "/home/user/.config/anthropic",
            "CLAUDE_CONFIG_DIR": "/home/user/.claude",
            "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01",
        }
        env, removed = llm.build_claude_code_env(dict(preserved))
        self.assertEqual(env, preserved)
        self.assertEqual(removed, [])

    def test_unrelated_variables_are_never_removed(self):
        """过滤只针对鉴权和供应商开关，不应影响 PATH、代理等常规变量。"""
        env, removed = llm.build_claude_code_env(
            {"PATH": "/usr/bin", "HTTPS_PROXY": "http://proxy:3128", "HOME": "/root"}
        )
        self.assertEqual(
            env,
            {"PATH": "/usr/bin", "HTTPS_PROXY": "http://proxy:3128", "HOME": "/root"},
        )
        self.assertEqual(removed, [])

    def test_clean_environment_is_left_unchanged(self):
        env, removed = llm.build_claude_code_env({"PATH": "/usr/bin"})
        self.assertEqual(env, {"PATH": "/usr/bin"})
        self.assertEqual(removed, [])

    def test_subprocess_receives_sanitized_environment(self):
        """适配器必须真的把清理后的环境传给子进程，而不只是计算一遍。"""
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.dict(
                os.environ, {"ANTHROPIC_API_KEY": "sk-ant-api03-x"}, clear=False
            ),
            patch.object(
                llm.subprocess,
                "run",
                return_value=self._completed(stdout=self._cli_payload("ok")),
            ) as run,
        ):
            llm._generate_response("write something")

        self.assertNotIn("ANTHROPIC_API_KEY", run.call_args.kwargs["env"])

    # ------------------------------------------------------- timeout config
    def test_timeout_accepts_numeric_and_string_values(self):
        """TOML 里 300 是 int，"300" 是 str，两种写法都必须支持。"""
        self.assertEqual(llm.coerce_claude_code_timeout(300), 300.0)
        self.assertEqual(llm.coerce_claude_code_timeout(300.5), 300.5)
        self.assertEqual(llm.coerce_claude_code_timeout("300"), 300.0)
        self.assertEqual(llm.coerce_claude_code_timeout("  300  "), 300.0)
        self.assertEqual(
            llm.coerce_claude_code_timeout(""), llm.CLAUDE_CODE_DEFAULT_TIMEOUT
        )
        self.assertEqual(
            llm.coerce_claude_code_timeout(None), llm.CLAUDE_CODE_DEFAULT_TIMEOUT
        )

    def test_timeout_rejects_non_finite_and_invalid_values(self):
        """nan / inf 会让 subprocess 永久阻塞，必须在配置阶段就拒绝。"""
        for invalid in (
            float("nan"),
            float("inf"),
            float("-inf"),
            "nan",
            "inf",
            "-inf",
            0,
            -5,
            "abc",
            True,
            [300],
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    llm.coerce_claude_code_timeout(invalid)

    def test_integer_timeout_in_config_is_accepted(self):
        """回归测试：int 超时曾触发 'int' object has no attribute 'strip'。"""
        config.app["claude_code_timeout"] = 30
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess,
                "run",
                return_value=self._completed(stdout=self._cli_payload("ok")),
            ) as run,
        ):
            self.assertEqual(llm._generate_response("write something"), "ok")
        self.assertEqual(run.call_args.kwargs["timeout"], 30.0)

    def test_zero_and_false_timeouts_are_rejected_not_defaulted(self):
        """0 / false 是无效取值，必须报错，而不是被默认值悄悄替换成 300 秒。"""
        for invalid in (0, False, "0", 0.0):
            with self.subTest(invalid=invalid):
                config.app["claude_code_timeout"] = invalid
                with patch.object(llm.shutil, "which", return_value="/usr/bin/claude"):
                    response = llm._generate_response("write something")
                self.assertTrue(response.startswith("Error:"), response)
                self.assertIn("claude_code_timeout", response)

    def test_field_default_applies_only_to_empty_values(self):
        """Registry 默认值只在未配置时生效，合法的假值要原样进入校验。"""
        self.assertEqual(llm._resolve_provider_field_value(None, "300"), "300")
        self.assertEqual(llm._resolve_provider_field_value("", "300"), "300")
        self.assertEqual(llm._resolve_provider_field_value("   ", "300"), "300")
        self.assertEqual(llm._resolve_provider_field_value(0, "300"), 0)
        self.assertEqual(llm._resolve_provider_field_value(False, "300"), False)
        self.assertEqual(llm._resolve_provider_field_value("60", "300"), "60")

    def test_invalid_timeout_reports_configuration_error(self):
        config.app["claude_code_timeout"] = "soon"
        with patch.object(llm.shutil, "which", return_value="/usr/bin/claude"):
            response = llm._generate_response("write something")
        self.assertIn("claude_code_timeout", response)
        self.assertTrue(response.startswith("Error:"), response)

    # -------------------------------------------------------- failure modes
    def test_missing_cli_reports_actionable_error(self):
        with (
            patch.object(llm.shutil, "which", return_value=None),
            patch.object(llm.os.path, "isfile", return_value=False),
        ):
            response = llm._generate_response("write something")
        self.assertIn("claude CLI not found", response)

    def test_missing_login_reports_setup_token_hint(self):
        """容器内无法执行交互式 /login，错误提示必须给出可用的替代方式。"""
        payload = self._cli_payload("Not logged in · Please run /login", is_error=True)
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess,
                "run",
                return_value=self._completed(stdout=payload, returncode=1),
            ),
        ):
            response = llm._generate_response("write something")
        self.assertIn("Not logged in", response)
        self.assertIn("setup-token", response)
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", response)

    def test_exhausted_quota_surfaces_cli_message(self):
        """用量耗尽同样是 is_error + 非零退出码，需要原样透出可读原因。"""
        payload = self._cli_payload(
            "Claude usage limit reached. Your limit will reset at 5pm.", is_error=True
        )
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess,
                "run",
                return_value=self._completed(stdout=payload, returncode=1),
            ),
        ):
            response = llm._generate_response("write something")
        self.assertIn("usage limit reached", response)

    def test_timeout_is_reported_with_configured_seconds(self):
        config.app["claude_code_timeout"] = 12
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess,
                "run",
                side_effect=llm.subprocess.TimeoutExpired(cmd="claude", timeout=12),
            ),
        ):
            response = llm._generate_response("write something")
        self.assertIn("timed out after 12s", response)

    def test_malformed_output_is_reported_instead_of_crashing(self):
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess,
                "run",
                return_value=self._completed(stdout="not json at all"),
            ),
        ):
            response = llm._generate_response("write something")
        self.assertIn("invalid response", response)

    def test_empty_output_is_reported(self):
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess, "run", return_value=self._completed(stdout="   ")
            ),
        ):
            response = llm._generate_response("write something")
        self.assertTrue(response.startswith("Error:"), response)

    def test_unsupported_cli_version_reports_upgrade_hint(self):
        """旧版 CLI 没有 --tools / --safe-mode，应提示升级而不是丢出裸 stderr。"""
        with (
            patch.object(llm.shutil, "which", return_value="/usr/bin/claude"),
            patch.object(
                llm.subprocess,
                "run",
                return_value=self._completed(
                    stderr="error: unknown option '--safe-mode'", returncode=1
                ),
            ),
        ):
            response = llm._generate_response("write something")
        self.assertIn("upgrade", response.lower())
        self.assertIn(llm.CLAUDE_CODE_MIN_CLI_VERSION, response)


class TestRuntimeEnvironmentDetection(unittest.TestCase):
    def test_container_detection_ignores_plain_linux_cgroup_file(self):
        """
        普通 Linux 也有 /proc/1/cgroup，不能因为文件存在就判定为容器。
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            cgroup_path = Path(tmp_dir) / "cgroup"
            cgroup_path.write_text("0::/init.scope\n", encoding="utf-8")

            self.assertFalse(
                config.is_running_in_container(
                    dockerenv_path=str(Path(tmp_dir) / "missing-dockerenv"),
                    containerenv_path=str(Path(tmp_dir) / "missing-containerenv"),
                    cgroup_path=str(cgroup_path),
                )
            )

    def test_container_detection_accepts_dockerenv_marker(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dockerenv_path = Path(tmp_dir) / ".dockerenv"
            dockerenv_path.write_text("", encoding="utf-8")

            self.assertTrue(
                config.is_running_in_container(
                    dockerenv_path=str(dockerenv_path),
                    containerenv_path=str(Path(tmp_dir) / "missing-containerenv"),
                    cgroup_path=str(Path(tmp_dir) / "missing-cgroup"),
                )
            )

    def test_container_detection_accepts_cgroup_container_marker(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cgroup_path = Path(tmp_dir) / "cgroup"
            cgroup_path.write_text(
                "0::/system.slice/docker-abcdef.scope\n",
                encoding="utf-8",
            )

            self.assertTrue(
                config.is_running_in_container(
                    dockerenv_path=str(Path(tmp_dir) / "missing-dockerenv"),
                    containerenv_path=str(Path(tmp_dir) / "missing-containerenv"),
                    cgroup_path=str(cgroup_path),
                )
            )

    def test_container_gateway_ip_decodes_default_route(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            route_path = Path(tmp_dir) / "route"
            route_path.write_text(
                "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
                "eth0\t00000000\t010011AC\t0003\t0\t0\t0\t00000000\t0\t0\t0\n",
                encoding="utf-8",
            )

            self.assertEqual(
                config.get_container_default_gateway_ip(str(route_path)),
                "172.17.0.1",
            )

    def test_container_gateway_ip_ignores_missing_default_route(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            route_path = Path(tmp_dir) / "route"
            route_path.write_text(
                "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
                "eth0\t0011AC0A\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n",
                encoding="utf-8",
            )

            self.assertEqual(
                config.get_container_default_gateway_ip(str(route_path)), ""
            )


class TestSocialMetadata(unittest.TestCase):
    """通用短视频发布文案元数据生成。"""

    def test_build_prompt_auto_language_uses_source_language(self):
        """
        language 默认 auto 时，不应该固定成某个国家或语种，而是让模型
        跟随视频主题和脚本的语言，扩大 API 适用范围。
        """
        prompt = llm.build_social_metadata_prompt(
            video_subject="上海一日游",
            video_script="今天带你快速看完上海经典路线。",
            language="auto",
            platform="tiktok",
        )

        self.assertIn("TikTok", prompt)
        self.assertIn("Use the same language as the video subject and script", prompt)
        self.assertIn("上海一日游", prompt)
        self.assertIn("array of exactly 5 strings", prompt)

    def test_build_prompt_accepts_explicit_language(self):
        prompt = llm.build_social_metadata_prompt(
            video_subject="Coffee tips",
            language="en-US",
            platform="youtube_shorts",
        )

        self.assertIn("YouTube Shorts", prompt)
        self.assertIn('Write "title" and "caption" in this language: en-US', prompt)
        self.assertIn("array of exactly 3 strings", prompt)

    def test_unknown_platform_falls_back_to_tiktok(self):
        prompt = llm.build_social_metadata_prompt(
            video_subject="x",
            platform="unsupported-platform",
        )

        self.assertIn("TikTok", prompt)

    def test_normalize_hashtags_from_string_dedupes_and_clamps(self):
        tags = llm._normalize_hashtags("#fyp fyp, trending #Trending viral", count=2)

        self.assertEqual(tags, ["#fyp", "#trending"])

    def test_normalize_hashtags_from_list_keeps_unicode_letters(self):
        tags = llm._normalize_hashtags(
            ["上海 旅行", "#việt nam", "  ", "@bad!chars"], count=5
        )

        self.assertEqual(tags, ["#上海旅行", "#việtnam", "#badchars"])

    def test_parse_social_metadata_recovers_embedded_json(self):
        raw = 'Sure: {"title":"T","caption":"C","hashtags":["#x"]} thanks'
        result = llm._parse_social_metadata(raw, "tiktok")

        self.assertEqual(result["title"], "T")
        self.assertEqual(result["caption"], "C")
        self.assertEqual(result["hashtags"], ["#x"])

    def test_parse_social_metadata_requires_title_or_caption(self):
        with self.assertRaises(ValueError):
            llm._parse_social_metadata('{"hashtags":["#x"]}', "tiktok")

    def test_generate_social_metadata_uses_llm_response(self):
        payload = (
            '{"title":"上海一日游","caption":"收藏这条路线，下次直接出发！",'
            '"hashtags":["#上海","#旅行","#shorts"]}'
        )
        with patch.object(llm, "_generate_response", return_value=payload):
            result = llm.generate_social_metadata(
                video_subject="上海一日游",
                video_script="今天带你快速看完上海经典路线。",
                language="zh-CN",
                platform="tiktok",
            )

        self.assertEqual(result["title"], "上海一日游")
        self.assertEqual(result["caption"], "收藏这条路线，下次直接出发！")
        self.assertEqual(result["hashtags"], ["#上海", "#旅行", "#shorts"])

    def test_generate_social_metadata_falls_back_to_generic_hashtags(self):
        with patch.object(
            llm, "_generate_response", return_value="Error: api_key is not set"
        ):
            result = llm.generate_social_metadata(
                video_subject="Coffee tips",
                video_script="Save these three coffee tips.",
                platform="instagram_reels",
            )

        self.assertEqual(result["title"], "Coffee tips")
        self.assertEqual(result["caption"], "Save these three coffee tips.")
        self.assertEqual(len(result["hashtags"]), 8)
        self.assertEqual(result["hashtags"][0], "#shorts")

    def test_request_model_defaults_to_auto_language_tiktok(self):
        body = VideoSocialMetadataRequest(video_subject="Test")

        self.assertEqual(body.language, "auto")
        self.assertEqual(body.platform, "tiktok")

    def test_request_model_rejects_oversized_social_metadata_fields(self):
        """
        外部 API 不能接受无限长的脚本和语言参数，否则会直接放大 LLM
        token 成本。schema 层先拦截，服务层再做内部调用兜底。
        """
        with self.assertRaises(ValidationError):
            VideoSocialMetadataRequest(video_subject="x" * 501)

        with self.assertRaises(ValidationError):
            VideoSocialMetadataRequest(video_subject="x", video_script="x" * 8001)

        with self.assertRaises(ValidationError):
            VideoSocialMetadataRequest(video_subject="x", language="x" * 65)

    def test_build_prompt_clamps_direct_service_inputs(self):
        prompt = llm.build_social_metadata_prompt(
            video_subject="x" * 600,
            video_script="y" * 9000,
            language="en",
        )

        self.assertIn("x" * llm.MAX_SOCIAL_SUBJECT_LENGTH, prompt)
        self.assertNotIn("x" * (llm.MAX_SOCIAL_SUBJECT_LENGTH + 1), prompt)
        self.assertIn("y" * llm.MAX_SOCIAL_SCRIPT_LENGTH, prompt)
        self.assertNotIn("y" * (llm.MAX_SOCIAL_SCRIPT_LENGTH + 1), prompt)

    def test_social_metadata_endpoint_response_shape(self):
        from fastapi.testclient import TestClient

        from app.asgi import app

        request_body = {
            "video_subject": "Tokyo coffee shops",
            "video_script": "Three quiet coffee shops for your next Tokyo morning.",
            "language": "en",
            "platform": "youtube_shorts",
        }
        llm_response = (
            '{"title":"3 Quiet Tokyo Coffee Shops",'
            '"caption":"Save these spots for your next Tokyo morning.",'
            '"hashtags":["#Tokyo","#Coffee","#Shorts"]}'
        )

        with patch.object(llm, "_generate_response", return_value=llm_response):
            response = TestClient(app).post(
                "/api/v1/social-metadata",
                json=request_body,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": 200,
                "message": "success",
                "data": {
                    "title": "3 Quiet Tokyo Coffee Shops",
                    "caption": "Save these spots for your next Tokyo morning.",
                    "hashtags": ["#Tokyo", "#Coffee", "#Shorts"],
                },
            },
        )


FOUNDRY_KEY = os.environ.get("ANTHROPIC_FOUNDRY_API_KEY", "")
FOUNDRY_BASE = "https://amanrai-test-resource.services.ai.azure.com/anthropic"
FOUNDRY_MODEL = "azure_ai/claude-sonnet-4-6"


@unittest.skipUnless(
    RUN_INTEGRATION_TESTS and FOUNDRY_KEY,
    "MPT_RUN_INTEGRATION_TESTS and ANTHROPIC_FOUNDRY_API_KEY not set",
)
class TestLiteLLMLiveIntegration(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        config.app["llm_provider"] = "litellm"
        config.app["litellm_model_name"] = FOUNDRY_MODEL
        os.environ["AZURE_AI_API_KEY"] = FOUNDRY_KEY
        os.environ["AZURE_AI_API_BASE"] = FOUNDRY_BASE

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def test_live_litellm_completion(self):
        result = llm._generate_response("What is 2+2? Reply with just the number.")

        self.assertNotIn("Error:", result)
        self.assertIn("4", result)


class TestRetryWarningBoundary(unittest.TestCase):
    """'trying again' must not be logged on the last retry attempt."""

    def _trying_again_count(self, mock_logger: object, fragment: str) -> int:
        return sum(
            1 for call in mock_logger.warning.call_args_list if fragment in str(call)
        )

    def test_generate_script_no_spurious_warning_on_last_attempt(self):
        with (
            patch.object(
                llm,
                "_generate_response",
                side_effect=RuntimeError("provider unavailable"),
            ),
            patch.object(llm, "logger") as mock_logger,
        ):
            llm.generate_script(video_subject="test subject")

        count = self._trying_again_count(mock_logger, "trying again")
        self.assertEqual(
            count,
            llm._max_retries - 1,
            "Warning must not fire on the final attempt — no further retry will occur",
        )

    def test_generate_terms_no_spurious_warning_on_last_attempt(self):
        with (
            patch.object(
                llm,
                "_generate_response",
                side_effect=RuntimeError("provider unavailable"),
            ),
            patch.object(llm, "logger") as mock_logger,
        ):
            llm.generate_terms(
                video_subject="test subject",
                video_script="some script text",
            )

        count = self._trying_again_count(mock_logger, "trying again")
        self.assertEqual(
            count,
            llm._max_retries - 1,
            "Warning must not fire on the final attempt — no further retry will occur",
        )


if __name__ == "__main__":
    unittest.main()
