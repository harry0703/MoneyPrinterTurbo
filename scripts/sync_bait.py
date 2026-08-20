#!/usr/bin/env python3
"""
在本机与服务器之间同步 brainrot 素材。

``resource/brainrotVideo/`` 被 gitignore 排除——里面是第三方素材，既不该进
仓库也不该占版本历史。代价是它不会跟着 ``git pull`` 走，所以需要这条独立通道。

用 rsync 而不是 scp：素材会逐步增加，每次只传新增的文件，中断后重跑也能续上。

    uv run python scripts/sync_bait.py            # 本机 -> 服务器
    uv run python scripts/sync_bait.py --pull     # 服务器 -> 本机
    uv run python scripts/sync_bait.py --dry-run  # 只看会传什么
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

DEFAULT_HOST = "ubuntu@141.253.101.226"
DEFAULT_KEY = "~/.ssh/id_ed25519"
DEFAULT_REMOTE_DIR = "MoneyPrinterTurbo"
ASSET_DIR = "resource/brainrotVideo"


def local_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync brainrot source material with the server.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="ssh destination")
    parser.add_argument("--key", default=DEFAULT_KEY, help="ssh private key")
    parser.add_argument("--remote-dir", default=DEFAULT_REMOTE_DIR,
                        help="project path on the server, relative to its home")
    parser.add_argument("--pull", action="store_true",
                        help="copy from the server instead of to it")
    parser.add_argument("--delete", action="store_true",
                        help="also remove files missing on the source side")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would move without moving it")
    return parser


def build_command(args) -> list[str]:
    rsync = shutil.which("rsync")
    if not rsync:
        raise SystemExit("rsync is required; install it with: sudo apt install rsync")

    # 末尾的斜杠决定 rsync 是同步目录内容还是把目录本身塞进去，两边都必须带。
    local_path = os.path.join(local_root(), ASSET_DIR) + os.sep
    remote_path = f"{args.host}:{args.remote_dir}/{ASSET_DIR}/"

    command = [
        rsync, "-az", "--partial", "--human-readable", "--info=progress2,name",
        "-e", f"ssh -i {os.path.expanduser(args.key)} -o BatchMode=yes",
    ]
    if args.dry_run:
        command.append("--dry-run")
    if args.delete:
        command.append("--delete")

    source, destination = (remote_path, local_path) if args.pull else (local_path, remote_path)
    command += [source, destination]
    return command


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    local_path = os.path.join(local_root(), ASSET_DIR)
    if not args.pull and not os.path.isdir(local_path):
        raise SystemExit(f"nothing to send: {local_path} does not exist")
    if args.pull:
        os.makedirs(local_path, exist_ok=True)

    # rsync 不会替远端创建多级父目录，先确保目标存在。
    if not args.pull:
        subprocess.run(
            ["ssh", "-i", os.path.expanduser(args.key), "-o", "BatchMode=yes", args.host,
             f"mkdir -p {args.remote_dir}/{ASSET_DIR}/bait {args.remote_dir}/{ASSET_DIR}/template"],
            check=True,
        )

    direction = "server -> local" if args.pull else "local -> server"
    print(f"{direction}  ({ASSET_DIR})")
    result = subprocess.run(build_command(args))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
