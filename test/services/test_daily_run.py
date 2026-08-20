import importlib.util
import os
import random
import sys
import unittest
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location(
    "daily_run", os.path.join(ROOT, "scripts", "daily_run.py")
)
daily_run = importlib.util.module_from_spec(_spec)
sys.modules["daily_run"] = daily_run
_spec.loader.exec_module(daily_run)

ACCOUNTS = ("why", "waypoint", "creature")


class PlanDayTest(unittest.TestCase):
    def _plan(self, seed=1, **kwargs):
        return daily_run.plan_day(ACCOUNTS, random.Random(seed), **kwargs)

    def test_every_account_runs_exactly_once(self):
        """漏掉一个账号就是那天少发一条，且不会有任何报错提示。"""
        accounts = [account for account, _ in self._plan()]
        self.assertEqual(sorted(accounts), sorted(ACCOUNTS))

    def test_order_varies_between_days(self):
        orders = {tuple(a for a, _ in self._plan(seed=seed)) for seed in range(40)}
        self.assertGreater(len(orders), 1)

    def test_delays_stay_within_their_ranges(self):
        first_range, gap_range = (60, 120), (300, 600)
        plan = self._plan(first_delay_range=first_range, gap_range=gap_range)
        self.assertGreaterEqual(plan[0][1], first_range[0])
        self.assertLessEqual(plan[0][1], first_range[1])
        for _, delay in plan[1:]:
            self.assertGreaterEqual(delay, gap_range[0])
            self.assertLessEqual(delay, gap_range[1])

    def test_gaps_are_never_identical_across_days(self):
        """固定间隔会让每个账号每天只落在同样几个刻度上，等于没有随机。"""
        gaps = {round(delay) for seed in range(20) for _, delay in self._plan(seed)[1:]}
        self.assertGreater(len(gaps), 5)

    def test_same_seed_reproduces_the_same_day(self):
        self.assertEqual(self._plan(seed=7), self._plan(seed=7))

    def test_a_single_account_gets_only_the_first_delay(self):
        plan = daily_run.plan_day(("why",), random.Random(1))
        self.assertEqual(len(plan), 1)

    def test_no_account_yields_an_empty_plan(self):
        self.assertEqual(daily_run.plan_day((), random.Random(1)), [])


class DescribeTest(unittest.TestCase):
    def test_times_accumulate_rather_than_repeat(self):
        """每一项都相对上一项结束，不是相对启动时刻。"""
        plan = [("why", 600), ("waypoint", 1800), ("creature", 1800)]
        lines = daily_run.describe(plan, datetime(2026, 8, 24, 12, 0))
        self.assertIn("12:10", lines[0])
        self.assertIn("12:40", lines[1])
        self.assertIn("13:10", lines[2])

    def test_each_line_names_its_account(self):
        plan = [("why", 60), ("creature", 60)]
        lines = daily_run.describe(plan, datetime(2026, 8, 24, 12, 0))
        self.assertIn("why", lines[0])
        self.assertIn("creature", lines[1])


class BusyExitCodeTest(unittest.TestCase):
    def test_busy_matches_run_plan(self):
        """两个文件各写一个 75 就会在某次改动后悄悄分叉，这里钉住它们一致。"""
        source = open(os.path.join(ROOT, "run_plan.py"), encoding="utf-8").read()
        self.assertIn("return 75", source)
        self.assertEqual(daily_run.EXIT_BUSY, 75)


if __name__ == "__main__":
    unittest.main()
