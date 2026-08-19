#!/usr/bin/env python3
"""
把服务器上生成的视频取回本地，并按账号分目录存放。

直接用 rsync 同步 ``storage/tasks/`` 只能得到一堆以任务 UUID 命名的目录，
既看不出属于哪个账号，也看不出讲的是什么。这里改为以内容计划为索引：
计划提供"条目 → 账号 / 主题"，服务器状态文件提供"条目 → 视频路径"，
两者相交即可得到可读的本地结构。

    ~/Videos/MoneyPrinterTurbo/
        why/       why-001-why-is-the-sky-blue.mp4
        waypoint/  waypoint-001-the-city-that-is-sinking.mp4
        creature/  creature-001-an-octopus-has-three-hearts.mp4

已存在的文件不会重复下载，因此可以随时重复执行。

    uv run python scripts/fetch_videos.py
    uv run python scripts/fetch_videos.py --account why
    uv run python scripts/fetch_videos.py --id why-004
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

DEFAULT_HOST = "ubuntu@141.253.101.226"
DEFAULT_KEY = "~/.ssh/id_ed25519"
DEFAULT_REMOTE_DIR = "~/MoneyPrinterTurbo"
DEFAULT_DEST = "~/Videos/MoneyPrinterTurbo"
MAX_SLUG_LENGTH = 60


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:MAX_SLUG_LENGTH].rstrip("-") or "untitled"


def _ssh_base(key: str) -> list[str]:
    return ["ssh", "-i", os.path.expanduser(key), "-o", "BatchMode=yes"]


def read_remote_state(host: str, key: str, remote_dir: str) -> dict:
    """读取远端计划状态。文件不存在说明还没生成过视频，属于正常情况。"""
    remote_path = f"{remote_dir}/storage/content_plan_state.json"
    result = subprocess.run(
        _ssh_base(key) + [host, f"cat {remote_path} 2>/dev/null || echo '{{}}'"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise SystemExit(f"cannot reach {host}: {result.stderr.strip()}")
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        raise SystemExit("remote plan state is not valid JSON")


def load_plan() -> dict:
    plan_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "content_plan.json"
    )
    if not os.path.isfile(plan_path):
        raise SystemExit(f"content plan not found: {plan_path}")
    with open(plan_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def download(host: str, key: str, remote_file: str, local_file: str) -> bool:
    os.makedirs(os.path.dirname(local_file), exist_ok=True)
    result = subprocess.run(
        [
            "scp",
            "-i", os.path.expanduser(key),
            "-o", "BatchMode=yes",
            "-q",
            f"{host}:{remote_file}",
            local_file,
        ],
        capture_output=True,
        text=True,
        timeout=900,
    )
    if result.returncode != 0:
        print(f"  failed: {result.stderr.strip()}", file=sys.stderr)
        return False
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch generated videos and sort them into one folder per account.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="ssh destination")
    parser.add_argument("--key", default=DEFAULT_KEY, help="ssh private key")
    parser.add_argument("--remote-dir", default=DEFAULT_REMOTE_DIR, help="project path on the server")
    parser.add_argument("--dest", default=DEFAULT_DEST, help="local folder to fill")
    parser.add_argument("--account", default="", help="only fetch this account")
    parser.add_argument("--id", default="", help="only fetch this plan entry, e.g. why-004")
    parser.add_argument(
        "--force",
        action="store_true",
        help="download again even if the local file already exists",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    dest_root = os.path.expanduser(args.dest)

    plan = load_plan()
    entries = {entry["id"]: entry for entry in plan["schedule"]}
    state = read_remote_state(args.host, args.key, args.remote_dir)

    downloaded = skipped = missing = 0

    for entry_id, record in sorted(state.items()):
        remote_file = record.get("video_path")
        if not remote_file:
            continue

        entry = entries.get(entry_id)
        if entry is None:
            # 计划之外的临时任务（例如手工测试）没有账号归属，跳过而不是
            # 丢进某个账号目录里造成混淆。
            missing += 1
            continue

        if args.account and entry["account"] != args.account:
            continue

        if args.id and entry_id != args.id:
            continue

        filename = f"{entry_id}-{slugify(entry['subject'])}.mp4"
        local_file = os.path.join(dest_root, entry["account"], filename)

        if os.path.isfile(local_file) and not args.force:
            skipped += 1
            continue

        print(f"{entry['account']:10} {filename}")
        if download(args.host, args.key, remote_file, local_file):
            downloaded += 1

    print()
    print(f"downloaded {downloaded}, already present {skipped}, outside the plan {missing}")
    print(f"destination: {dest_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
