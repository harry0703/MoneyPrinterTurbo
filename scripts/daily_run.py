#!/usr/bin/env python3
"""
每天跑一轮：三个账号随机排序，逐个生成并发布，彼此间隔一段随机时间。

为什么是一个脚本跑完三次，而不是三条 cron：
生成一条视频要十几分钟，而全机只有一把生成锁。三条 cron 各自定时触发时，
后一条很可能撞上前一条还没结束的渲染，被锁拒绝后直接放弃，那天就少发一条。
串行跑完则天然不会撞锁，而且间隔是从"上一条真正发完"开始算的。

时间也做了随机。固定 12:00 / 12:30 / 13:00 只打乱了账号顺序，每个账号仍然
只会落在这三个刻度上；起跑延迟加上随机间隔之后，同一个账号每天的发布时间
才真的不一样。

    uv run python scripts/daily_run.py --dry-run   # 只看今天的安排
    uv run python scripts/daily_run.py
"""

from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
import time
from datetime import date, datetime, timedelta

from loguru import logger

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ACCOUNTS = ("why", "waypoint", "creature")
LOG_DIRNAME = "logs"

# 起跑前的随机等待，让第一条的时间每天都不同。
FIRST_DELAY_RANGE = (0, 35 * 60)
# 两条之间的随机间隔，从上一条结束时算起。
GAP_RANGE = (25 * 60, 50 * 60)

# run_plan.py 用 75 表示"另一条生成正在进行，稍后重试"，不是失败。
EXIT_BUSY = 75


def plan_day(
    accounts: tuple[str, ...],
    rng: random.Random,
    first_delay_range: tuple[int, int] = FIRST_DELAY_RANGE,
    gap_range: tuple[int, int] = GAP_RANGE,
) -> list[tuple[str, float]]:
    """
    返回 ``[(账号, 开跑前等待的秒数)]``。

    第一项的等待相对脚本启动，其余相对上一条结束。顺序与间隔都取自传入的
    ``rng``，因此给定种子可以完整复现某一天的安排。
    """
    order = list(accounts)
    rng.shuffle(order)

    delays = [rng.uniform(*first_delay_range)]
    delays += [rng.uniform(*gap_range) for _ in order[1:]]
    return list(zip(order, delays))


def describe(schedule: list[tuple[str, float]], start: datetime) -> list[str]:
    """把安排渲染成人能读的预计时刻，供 --dry-run 与日志使用。"""
    lines = []
    moment = start
    for account, delay in schedule:
        moment += timedelta(seconds=delay)
        lines.append(f"{moment:%H:%M}  {account}  (+{delay / 60:.0f} min)")
    return lines


def setup_logging() -> str:
    from app.utils import utils

    log_dir = os.path.join(utils.storage_dir(create=True), LOG_DIRNAME)
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"daily_run-{date.today():%Y%m%d}.log")
    logger.add(log_path, level="INFO", rotation="10 MB", retention="60 days",
               encoding="utf-8", enqueue=True)
    return log_path


def run_account(account: str, extra: list[str]) -> int:
    """
    跑一个账号，返回退出码。

    用子进程而不是直接调用：一条视频的渲染会占用大量内存，跑完就随进程一起
    释放；某个账号异常退出也不会带走当天剩下的两条。
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    command = [sys.executable, os.path.join(root, "run_plan.py"),
               "--account", account] + extra

    logger.info(f"[{account}] starting")
    completed = subprocess.run(command, cwd=root)

    if completed.returncode == EXIT_BUSY:
        logger.warning(f"[{account}] skipped, another generation holds the lock")
    elif completed.returncode != 0:
        logger.error(f"[{account}] failed with exit code {completed.returncode}")
    else:
        logger.info(f"[{account}] done")
    return completed.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish one video per account, in a random order at random times.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--accounts", nargs="+", default=list(ACCOUNTS))
    parser.add_argument("--seed", type=int, default=0, help="0 picks a random one")
    parser.add_argument("--dry-run", action="store_true",
                        help="print today's schedule and exit")
    parser.add_argument("--no-publish", action="store_true",
                        help="render without publishing")
    parser.add_argument("--next", action="store_true",
                        help="ignore the schedule dates and take the next unrendered entry")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    seed = args.seed or random.randrange(1, 10**6)
    schedule = plan_day(tuple(args.accounts), random.Random(seed))
    lines = describe(schedule, datetime.now())

    if args.dry_run:
        print(f"seed {seed}")
        print("\n".join(lines))
        return 0

    setup_logging()
    logger.info(f"daily run, seed {seed}")
    for line in lines:
        logger.info(f"  {line}")

    extra = []
    if args.no_publish:
        extra.append("--no-publish")
    if args.next:
        extra.append("--next")

    failures = 0
    for account, delay in schedule:
        logger.info(f"waiting {delay / 60:.0f} min before {account}")
        time.sleep(delay)
        if run_account(account, extra) not in (0, EXIT_BUSY):
            failures += 1

    logger.info(f"daily run finished, {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
