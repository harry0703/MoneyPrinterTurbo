import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.services import llm, script_prompt


class TestPlaybookSystemPrompt(unittest.TestCase):
    def test_prompt_carries_the_playbook_rules(self):
        """预设的价值在于把 playbook 的硬性规则写进提示词，而不是泛泛要求“写好”。"""
        prompt = script_prompt.build_playbook_system_prompt()

        self.assertIn("hook", prompt)
        self.assertIn("today we're going to talk about", prompt)
        self.assertIn("Never pad", prompt)
        self.assertIn("every few seconds", prompt)
        self.assertIn("same language as the video subject", prompt)
        self.assertNotIn("{", prompt)

    def test_duration_prior_matches_the_platform(self):
        """时长是实验先验，必须按平台注入，并换算成模型能对齐的词数预算。"""
        tiktok = script_prompt.build_playbook_system_prompt(platform="tiktok")
        reels = script_prompt.build_playbook_system_prompt(platform="reels")

        self.assertIn("20-30 seconds", tiktok)
        self.assertIn("50-75 spoken words", tiktok)
        self.assertIn("45-60 seconds", reels)
        self.assertIn("Instagram Reels", reels)

    def test_unknown_platform_falls_back_to_the_default_prior(self):
        prompt = script_prompt.build_playbook_system_prompt(platform="telegram")

        self.assertIn("TikTok", prompt)
        self.assertIn("20-30 seconds", prompt)

    def test_format_skeleton_is_injected_only_when_requested(self):
        without_format = script_prompt.build_playbook_system_prompt()
        with_format = script_prompt.build_playbook_system_prompt(
            video_format="mystery_reveal"
        )

        self.assertNotIn("## Format:", without_format)
        self.assertIn("mystery reveal", with_format)
        self.assertIn("open loop", with_format)

    def test_unknown_format_is_ignored(self):
        """未知格式不应让生成失败，模型自行选择叙事机制即可。"""
        prompt = script_prompt.build_playbook_system_prompt(video_format="tiktok_dance")

        self.assertNotIn("## Format:", prompt)


class TestScriptPromptPresetSelection(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def test_preset_is_disabled_by_default(self):
        """没有配置键时，流水线必须保持上游通用提示词的行为。"""
        config.app.pop("script_prompt_preset", None)

        prompt = llm.build_script_prompt(video_subject="coffee")

        self.assertIn("# Role: Video Script Generator", prompt)

    def test_playbook_preset_replaces_the_default_system_prompt(self):
        config.app.update(
            {
                "script_prompt_preset": "playbook",
                "script_preset_platform": "youtube_shorts",
                "script_preset_format": "myth_busting",
            }
        )

        prompt = llm.build_script_prompt(video_subject="coffee", paragraph_number=2)

        self.assertNotIn("# Role: Video Script Generator", prompt)
        self.assertIn("Short-Form Vertical Video Script Writer", prompt)
        self.assertIn("20-40 seconds", prompt)
        self.assertIn("myth busting", prompt)
        # 运行时上下文必须继续拼接，预设不能吃掉主题和段落数。
        self.assertIn("- video subject: coffee", prompt)
        self.assertIn("- number of paragraphs: 2", prompt)

    def test_custom_system_prompt_still_wins_over_the_preset(self):
        config.app["script_prompt_preset"] = "playbook"

        prompt = llm.build_script_prompt(
            video_subject="coffee",
            custom_system_prompt="# Role: My Own Writer",
        )

        self.assertIn("# Role: My Own Writer", prompt)
        self.assertNotIn("Short-Form Vertical Video Script Writer", prompt)

    def test_unknown_preset_falls_back_to_the_default_prompt(self):
        config.app["script_prompt_preset"] = "viral-magic"

        prompt = llm.build_script_prompt(video_subject="coffee")

        self.assertIn("# Role: Video Script Generator", prompt)

    def test_missing_template_does_not_break_generation(self):
        """模板读取失败只应降级到通用提示词，不能中断整条流水线。"""
        config.app["script_prompt_preset"] = "playbook"

        with patch.object(
            script_prompt,
            "build_playbook_system_prompt",
            side_effect=OSError("template is gone"),
        ):
            prompt = llm.build_script_prompt(video_subject="coffee")

        self.assertIn("# Role: Video Script Generator", prompt)


if __name__ == "__main__":
    unittest.main()
