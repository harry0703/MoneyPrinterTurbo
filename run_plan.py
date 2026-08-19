#!/usr/bin/env python3
"""
按内容计划生成并发布一条视频。

一条命令完成"取出当天条目 → 用该账号的参数生成视频 → 发布到对应账号"，
因此可以直接交给 cron 调度。

状态记录在 ``storage/content_plan_state.json``：已完成的条目不会重复执行，
生成成功但发布失败的条目会保留视频路径，重跑时直接续做发布，不会浪费一次
完整的渲染。

    uv run python run_plan.py --account why            # 跑该账号当天应发的一条
    uv run python run_plan.py --account why --dry-run  # 只看会跑什么
    uv run python run_plan.py --id why-001             # 指定条目
    uv run python run_plan.py --status                 # 查看整体进度
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

from loguru import logger

PLAN_FILENAME = "content_plan.json"
LOG_DIRNAME = "logs"
STATE_FILENAME = "content_plan_state.json"

class GenerationBusy(RuntimeError):
    """另一条生成正在进行。属于稍后重试，不是本条目失败。"""


STATUS_DONE = "published"
STATUS_GENERATED = "generated"
STATUS_FAILED = "failed"


def setup_logging() -> str:
    """
    每次运行都追加写入按日期分文件的日志。

    cron 执行时终端输出无人查看，没有落盘日志就无法回溯"某天那条视频
    为什么失败"。控制台输出保持不变，便于手动运行时直接观察进度。
    """
    from app.utils import utils

    log_dir = os.path.join(utils.storage_dir(create=True), LOG_DIRNAME)
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"run_plan-{date.today():%Y%m%d}.log")
    logger.add(
        log_path,
        level="INFO",
        rotation="10 MB",
        retention="30 days",
        encoding="utf-8",
        enqueue=True,
    )
    return log_path


def _plan_path() -> str:
    from app.utils import utils

    return os.path.join(utils.root_dir(), PLAN_FILENAME)


def _state_path() -> str:
    from app.utils import utils

    return os.path.join(utils.storage_dir(create=True), STATE_FILENAME)


def load_plan() -> dict:
    path = _plan_path()
    if not os.path.isfile(path):
        raise SystemExit(f"content plan not found: {path}")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_state() -> dict:
    try:
        with open(_state_path(), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_entry(entry_id: str, record: dict) -> None:
    """
    只更新一个条目，写入前重新读取磁盘上的状态。

    一次生成要十几分钟，期间进程一直持有开始时读到的状态副本。如果直接把
    这份副本整体写回，另一个进程在这段时间里写下的记录就会被悄悄抹掉——
    实际发生过：一条被拒绝的条目在长任务结束时从文件里消失了。
    """
    path = _state_path()
    state = load_state()
    state[entry_id] = record
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def _has_video(record: dict) -> bool:
    video_path = record.get("video_path")
    return bool(video_path and os.path.isfile(video_path))


def select_entry(plan: dict, state: dict, args) -> dict | None:
    """
    选出本次要执行的条目。

    默认只做"当天及之前尚未完成的最早一条"，这样偶尔漏跑一天，第二天会
    自动补上，而不会一次性把积压的视频全部推到同一天发布。

    ``--next`` 用于计划正式开始之前的预生成：忽略排期日期，直接取第一条
    还没有成片的条目，方便先渲染几条出来检查风格。
    """
    schedule = plan["schedule"]

    if args.id:
        for entry in schedule:
            if entry["id"] == args.id:
                return entry
        raise SystemExit(f"unknown plan entry: {args.id}")

    candidates = [
        entry
        for entry in schedule
        if not args.account or entry["account"] == args.account
    ]

    if getattr(args, "next", False):
        pending = [
            entry
            for entry in candidates
            if state.get(entry["id"], {}).get("status") != STATUS_DONE
            and not _has_video(state.get(entry["id"], {}))
        ]
        return pending[0] if pending else None

    today = args.date or date.today().isoformat()
    pending = [
        entry
        for entry in candidates
        if entry["date"] <= today
        and state.get(entry["id"], {}).get("status") != STATUS_DONE
    ]
    return pending[0] if pending else None


def build_params(plan: dict, entry: dict):
    from app.models.schema import VideoParams

    profile = plan["accounts"][entry["account"]]
    fields = dict(profile["defaults"])
    fields["video_subject"] = entry["subject"]
    fields["video_script_prompt"] = profile.get("video_script_prompt", "")
    # 每条视频的曲目由计划固定，保证同一账号的听感稳定且可复现。
    if entry.get("bgm_file"):
        fields["bgm_file"] = entry["bgm_file"]
    return VideoParams(**fields)


def generate_video(plan: dict, entry: dict) -> str:
    from uuid import uuid4

    from app.models import const
    from app.services import task as task_service

    params = build_params(plan, entry)
    task_id = str(uuid4())
    logger.info(f"[{entry['id']}] generating: {entry['subject']}")

    result = task_service.start(task_id=task_id, params=params, stop_at="video")
    if not result or result.get("state") == const.TASK_STATE_FAILED:
        error = (result or {}).get("error", "unknown generation failure")
        if (result or {}).get("error_code") == "busy":
            raise GenerationBusy(error)
        raise RuntimeError(f"generation failed: {error}")

    videos = result.get("videos") or []
    if not videos:
        raise RuntimeError("generation produced no video file")
    return videos[0]


def publish_video(plan: dict, entry: dict, video_path: str) -> dict:
    from app.services import instagram

    profile = plan["accounts"][entry["account"]]
    logger.info(f"[{entry['id']}] publishing to {profile['instagram_username']}")
    return instagram.publish_reel(
        video_path=video_path,
        caption=entry["caption"],
        account=entry["account"],
    )


def _running_generation() -> str:
    """
    读取生成锁的持有者信息。

    "另一条生成正在进行"是最容易让人困惑的状态：命令看上去无缘无故失败，
    而使用者并不知道机器上还有别的任务。把它直接显示在状态里。
    """
    from app.services import generation_lock

    path = generation_lock.lock_path()
    if not os.path.isfile(path):
        return ""

    try:
        with open(path, "r", encoding="utf-8") as handle:
            owner = handle.read().strip()
    except OSError:
        return ""

    if not owner:
        return ""

    # 锁文件在任务结束后仍然存在，必须通过实际加锁来判断是否真的被占用。
    try:
        with generation_lock.acquire():
            return ""
    except generation_lock.GenerationBusyError:
        return owner


def show_status(plan: dict, state: dict) -> int:
    today = date.today().isoformat()
    per_account: dict[str, dict[str, int]] = {}

    for entry in plan["schedule"]:
        bucket = per_account.setdefault(
            entry["account"], {"total": 0, "published": 0, "failed": 0, "due": 0}
        )
        bucket["total"] += 1
        status = state.get(entry["id"], {}).get("status")
        if status == STATUS_DONE:
            bucket["published"] += 1
        elif status == STATUS_FAILED:
            bucket["failed"] += 1
        elif entry["date"] <= today:
            bucket["due"] += 1

    running = _running_generation()
    if running:
        print(f"generation in progress — {running}\n")

    print(f"{'account':12} {'published':>10} {'failed':>7} {'due now':>8} {'total':>6}")
    for account, counts in per_account.items():
        print(
            f"{account:12} {counts['published']:>10} {counts['failed']:>7} "
            f"{counts['due']:>8} {counts['total']:>6}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate and publish the next scheduled video from the content plan.",
    )
    parser.add_argument("--account", default="", help="restrict to one account label")
    parser.add_argument("--id", default="", help="run one specific plan entry")
    parser.add_argument("--date", default="", help="treat this ISO date as today")
    parser.add_argument(
        "--next",
        action="store_true",
        help="take the next entry with no video yet, ignoring the schedule date",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-generate even when a video already exists for the entry",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show the selected entry and exit"
    )
    parser.add_argument(
        "--no-publish", action="store_true", help="generate the video but do not publish"
    )
    parser.add_argument("--status", action="store_true", help="print progress and exit")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    plan = load_plan()
    state = load_state()

    if args.status:
        return show_status(plan, state)

    # 只读操作不必留下日志文件，真正会改变状态的运行才记录。
    if not args.dry_run:
        setup_logging()

    entry = select_entry(plan, state, args)
    if entry is None:
        logger.info("nothing due")
        return 0

    record = state.setdefault(entry["id"], {})

    if args.dry_run:
        profile = plan["accounts"][entry["account"]]
        print(
            json.dumps(
                {
                    "id": entry["id"],
                    "date": entry["date"],
                    "account": entry["account"],
                    "instagram_username": profile["instagram_username"],
                    "subject": entry["subject"],
                    "status": record.get("status", "pending"),
                    "params": profile["defaults"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    try:
        # 生成成功但发布失败时保留视频，重跑直接续做发布。渲染一条视频
        # 需要十几分钟，不应该因为一次网络错误就重来。
        video_path = None if args.force else record.get("video_path")
        if not (video_path and os.path.isfile(video_path)):
            video_path = generate_video(plan, entry)
            record.update({"status": STATUS_GENERATED, "video_path": video_path})
            save_entry(entry["id"], record)

        if args.no_publish:
            logger.info(f"[{entry['id']}] generated, publishing skipped")
            print(json.dumps({"id": entry["id"], "video": video_path}))
            return 0

        result = publish_video(plan, entry, video_path)
    except GenerationBusy as exc:
        # 不写入任何状态：本条目还没开始做，下次运行会照常选中它。
        logger.warning(f"[{entry['id']}] postponed: {exc}")
        print(json.dumps({"id": entry["id"], "ok": False, "error_code": "busy",
                          "error": str(exc)}, ensure_ascii=False))
        return 75
    except Exception as exc:
        record["status"] = STATUS_FAILED
        record["error"] = f"{type(exc).__name__}: {exc}"
        save_entry(entry["id"], record)
        logger.error(f"[{entry['id']}] failed: {exc}")
        print(json.dumps({"id": entry["id"], "ok": False, "error": str(exc)}))
        return 1

    record.update(
        {
            "status": STATUS_DONE,
            "video_path": video_path,
            "url": result.get("url"),
            "published_at": result.get("published_at"),
        }
    )
    record.pop("error", None)
    save_entry(entry["id"], record)

    logger.success(f"[{entry['id']}] published: {result.get('url')}")
    print(json.dumps({"id": entry["id"], "ok": True, "url": result.get("url")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
