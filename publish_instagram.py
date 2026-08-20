#!/usr/bin/env python3
"""
把已生成的视频发布到 Instagram Reels。

刻意与 ``cli.py`` 分开：生成和发布是两件独立的事，失败原因、重试策略和
频率约束都不一样。分开之后，一条视频可以先生成、人工确认，再择时发布。

用法示例：

    uv run python publish_instagram.py --check
    uv run python publish_instagram.py --task <task-id> --caption "..."
    uv run python publish_instagram.py --video ./storage/tasks/<id>/final-1.mp4
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from loguru import logger


def _video_from_task(task_id: str) -> str:
    from app.utils import utils

    task_dir = utils.task_dir(task_id)
    if not os.path.isdir(task_dir):
        raise SystemExit(f"task directory not found: {task_dir}")

    candidates = sorted(
        name for name in os.listdir(task_dir)
        if name.startswith("final-") and name.endswith(".mp4")
    )
    if not candidates:
        raise SystemExit(f"no final video found in {task_dir}")
    return os.path.join(task_dir, candidates[0])


def _probe_duration_ms(video_path: str) -> int:
    """读取真实时长，供配乐区间使用；失败时返回 0 并继续发布。"""
    from app.utils import utils

    try:
        result = subprocess.run(
            [
                utils.get_ffmpeg_binary().replace("ffmpeg", "ffprobe"),
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return int(float(result.stdout.strip()) * 1000)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        logger.warning("could not probe video duration; music range may be off")
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish a generated video to Instagram Reels.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--task", help="task id under storage/tasks/")
    source.add_argument("--video", help="explicit path to an .mp4 file")

    parser.add_argument("--caption", default="", help="reel caption, hashtags included")
    parser.add_argument(
        "--music",
        default="",
        help="optional Instagram track to attach, searched by name",
    )
    parser.add_argument(
        "--account",
        default="",
        help="account label or username; required when several are configured",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify credentials and stored session, publish nothing",
    )
    parser.add_argument(
        "--import-session",
        default="",
        metavar="SESSIONID",
        help="build the stored session from a browser sessionid cookie, "
             "for when password login is refused",
    )
    parser.add_argument(
        "--check-all",
        action="store_true",
        help="verify every configured account's session in one go",
    )
    parser.add_argument(
        "--list-accounts",
        action="store_true",
        help="print the configured accounts and exit",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    from app.services import instagram

    if args.list_accounts:
        accounts = [
            {"label": account.label, "username": account.username,
             "proxy": bool(account.proxy)}
            for account in instagram.list_accounts()
        ]
        print(json.dumps(accounts, ensure_ascii=False))
        return 0

    if args.import_session:
        try:
            result = instagram.import_session(
                args.import_session, account=args.account
            )
        except instagram.InstagramError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 1
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if args.check_all:
        # 会话会被平台单方面吊销，而失效只有在发布那一刻才会显现。逐个账号
        # 报告，就能在当天的定时任务跑起来之前先看一眼。
        failures = 0
        for account in instagram.list_accounts():
            try:
                instagram.verify_session(account=account.label)
                print(f"{account.label:12} ok       {account.username}")
            except instagram.InstagramError as exc:
                failures += 1
                print(f"{account.label:12} FAILED   {exc}")
        return 1 if failures else 0

    if args.check:
        try:
            result = instagram.verify_session(account=args.account)
        except instagram.InstagramError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 1
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if not args.task and not args.video:
        raise SystemExit(
            "one of --task, --video, --check, --import-session "
            "or --list-accounts is required"
        )

    video_path = args.video or _video_from_task(args.task)
    if not os.path.isfile(video_path):
        raise SystemExit(f"video file not found: {video_path}")

    try:
        result = instagram.publish_reel(
            video_path=video_path,
            caption=args.caption,
            music_query=args.music,
            video_duration_ms=_probe_duration_ms(video_path) if args.music else 0,
            account=args.account,
        )
    except instagram.InstagramRateLimitError as exc:
        print(json.dumps({"ok": False, "error_type": "rate_limit", "error": str(exc)}))
        return 1
    except instagram.InstagramAuthError as exc:
        print(json.dumps({"ok": False, "error_type": "auth", "error": str(exc)}))
        return 1
    except instagram.InstagramError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
