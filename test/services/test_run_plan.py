import json
import os
import tempfile
import unittest
from unittest.mock import patch

import run_plan


def _plan():
    return {
        "version": 1,
        "accounts": {
            "why": {
                "instagram_username": "why.though101",
                "defaults": {
                    "video_aspect": "9:16",
                    "paragraph_number": 1,
                    "voice_name": "en-US-AvaMultilingualNeural-Female",
                },
                "video_script_prompt": "Open with the question.",
                "hashtags": ["#a"],
            },
            "creature": {
                "instagram_username": "creature.feature60",
                "defaults": {"video_aspect": "9:16", "paragraph_number": 1},
                "video_script_prompt": "Open with the fact.",
                "hashtags": ["#b"],
            },
        },
        "schedule": [
            {"id": "why-001", "date": "2026-08-24", "account": "why",
             "subject": "Why is the sky blue?", "caption": "c1"},
            {"id": "creature-001", "date": "2026-08-24", "account": "creature",
             "subject": "An octopus has three hearts", "caption": "c2"},
            {"id": "why-002", "date": "2026-08-25", "account": "why",
             "subject": "Why is the sea salty?", "caption": "c3"},
        ],
    }


class _Args:
    def __init__(self, **kwargs):
        self.account = kwargs.get("account", "")
        self.id = kwargs.get("id", "")
        self.date = kwargs.get("date", "")


class SelectEntryTest(unittest.TestCase):
    def test_picks_earliest_due_entry(self):
        entry = run_plan.select_entry(_plan(), {}, _Args(date="2026-08-25"))
        self.assertEqual(entry["id"], "why-001")

    def test_account_filter_is_respected(self):
        entry = run_plan.select_entry(
            _plan(), {}, _Args(date="2026-08-25", account="creature")
        )
        self.assertEqual(entry["id"], "creature-001")

    def test_published_entries_are_skipped(self):
        state = {"why-001": {"status": run_plan.STATUS_DONE}}
        entry = run_plan.select_entry(
            _plan(), state, _Args(date="2026-08-25", account="why")
        )
        self.assertEqual(entry["id"], "why-002")

    def test_future_entries_are_not_run_early(self):
        """未到日期的条目不能提前发布，否则一次补跑会把积压全部推出去。"""
        state = {"why-001": {"status": run_plan.STATUS_DONE}}
        entry = run_plan.select_entry(
            _plan(), state, _Args(date="2026-08-24", account="why")
        )
        self.assertIsNone(entry)

    def test_failed_entries_are_retried(self):
        """失败的条目应在下次运行时重试，而不是被永久跳过。"""
        state = {"why-001": {"status": run_plan.STATUS_FAILED}}
        entry = run_plan.select_entry(
            _plan(), state, _Args(date="2026-08-25", account="why")
        )
        self.assertEqual(entry["id"], "why-001")

    def test_explicit_id_overrides_schedule(self):
        entry = run_plan.select_entry(_plan(), {}, _Args(id="why-002"))
        self.assertEqual(entry["subject"], "Why is the sea salty?")

    def test_unknown_id_fails_loudly(self):
        with self.assertRaises(SystemExit):
            run_plan.select_entry(_plan(), {}, _Args(id="nope-999"))


class BuildParamsTest(unittest.TestCase):
    def test_account_defaults_and_subject_are_merged(self):
        plan = _plan()
        params = run_plan.build_params(plan, plan["schedule"][0])
        self.assertEqual(params.video_subject, "Why is the sky blue?")
        self.assertEqual(params.voice_name, "en-US-AvaMultilingualNeural-Female")
        self.assertEqual(params.video_script_prompt, "Open with the question.")

    def test_each_account_keeps_its_own_style(self):
        """三个账号必须产生不同的脚本指令，否则内容会趋同。"""
        plan = _plan()
        first = run_plan.build_params(plan, plan["schedule"][0])
        second = run_plan.build_params(plan, plan["schedule"][1])
        self.assertNotEqual(first.video_script_prompt, second.video_script_prompt)


class ResumeTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.plan = _plan()
        patcher = patch.object(run_plan, "load_plan", return_value=self.plan)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.state_path = os.path.join(self.temp_dir, "state.json")
        patcher2 = patch.object(run_plan, "_state_path", return_value=self.state_path)
        patcher2.start()
        self.addCleanup(patcher2.stop)

        self.video_path = os.path.join(self.temp_dir, "final-1.mp4")
        with open(self.video_path, "wb") as handle:
            handle.write(b"video")

    def test_publish_failure_keeps_video_for_retry(self):
        """渲染一条视频要十几分钟，发布失败不能让它作废重来。"""
        with patch.object(run_plan, "generate_video", return_value=self.video_path):
            with patch.object(run_plan, "publish_video", side_effect=RuntimeError("boom")):
                code = run_plan.main(["--account", "why", "--date", "2026-08-24"])

        self.assertEqual(code, 1)
        state = json.load(open(self.state_path, encoding="utf-8"))
        self.assertEqual(state["why-001"]["status"], run_plan.STATUS_FAILED)
        self.assertEqual(state["why-001"]["video_path"], self.video_path)

    def test_retry_reuses_existing_video(self):
        """重跑时必须复用已渲染的视频，不再调用生成流程。"""
        with patch.object(run_plan, "generate_video", return_value=self.video_path):
            with patch.object(run_plan, "publish_video", side_effect=RuntimeError("boom")):
                run_plan.main(["--account", "why", "--date", "2026-08-24"])

        with patch.object(run_plan, "generate_video") as generate:
            with patch.object(
                run_plan, "publish_video", return_value={"url": "https://x/reel/A/"}
            ):
                code = run_plan.main(["--account", "why", "--date", "2026-08-24"])

        generate.assert_not_called()
        self.assertEqual(code, 0)
        state = json.load(open(self.state_path, encoding="utf-8"))
        self.assertEqual(state["why-001"]["status"], run_plan.STATUS_DONE)
        self.assertNotIn("error", state["why-001"])

    def test_successful_run_records_url(self):
        with patch.object(run_plan, "generate_video", return_value=self.video_path):
            with patch.object(
                run_plan, "publish_video", return_value={"url": "https://x/reel/B/"}
            ):
                code = run_plan.main(["--account", "why", "--date", "2026-08-24"])

        self.assertEqual(code, 0)
        state = json.load(open(self.state_path, encoding="utf-8"))
        self.assertEqual(state["why-001"]["url"], "https://x/reel/B/")

    def test_no_publish_stops_after_generation(self):
        with patch.object(run_plan, "generate_video", return_value=self.video_path):
            with patch.object(run_plan, "publish_video") as publish:
                code = run_plan.main(
                    ["--account", "why", "--date", "2026-08-24", "--no-publish"]
                )

        publish.assert_not_called()
        self.assertEqual(code, 0)

    def test_nothing_due_exits_cleanly(self):
        """没有待办时必须正常退出，否则 cron 每次都会报警。"""
        code = run_plan.main(["--account", "why", "--date", "2026-08-01"])
        self.assertEqual(code, 0)


class RealPlanTest(unittest.TestCase):
    """针对仓库中真实的 content_plan.json，避免计划文件损坏后无人察觉。"""

    def setUp(self):
        self.plan = run_plan.load_plan()

    def test_every_entry_references_a_configured_account(self):
        accounts = set(self.plan["accounts"])
        for entry in self.plan["schedule"]:
            self.assertIn(entry["account"], accounts)

    def test_entry_ids_are_unique(self):
        ids = [entry["id"] for entry in self.plan["schedule"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_subjects_are_never_repeated_within_an_account(self):
        """重复主题正是平台判定模板化生产的依据，必须杜绝。"""
        seen: dict[str, set] = {}
        for entry in self.plan["schedule"]:
            bucket = seen.setdefault(entry["account"], set())
            self.assertNotIn(entry["subject"], bucket)
            bucket.add(entry["subject"])

    def test_all_entries_build_valid_video_params(self):
        for entry in self.plan["schedule"]:
            params = run_plan.build_params(self.plan, entry)
            self.assertTrue(params.video_subject)
            self.assertEqual(params.video_aspect.value, "9:16")

    def test_every_entry_has_a_resolvable_track(self):
        """计划里写死的曲目必须真实存在，否则整条视频会在合成阶段才失败。"""
        from app.services import bgm

        for entry in self.plan["schedule"]:
            self.assertTrue(entry.get("bgm_file"))
            bgm.resolve_bgm_file(entry["bgm_file"])

    def test_accounts_do_not_share_tracks(self):
        """曲目池不重叠，三个账号才会有各自稳定的听感。"""
        pools: dict[str, set] = {}
        for entry in self.plan["schedule"]:
            pools.setdefault(entry["account"], set()).add(entry["bgm_file"])
        for account, tracks in pools.items():
            others = set().union(
                *(value for key, value in pools.items() if key != account)
            )
            self.assertFalse(tracks & others, f"{account} shares tracks")

    def test_schedule_is_chronological(self):
        dates = [entry["date"] for entry in self.plan["schedule"]]
        self.assertEqual(dates, sorted(dates))


if __name__ == "__main__":
    unittest.main()
