#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["yt-dlp>=2025.1.15", "imageio-ffmpeg>=0.5.1"]
# ///
"""
把一条网上的视频取到 brainrot 素材目录。

和 ``instagram_worker.py`` 同样用 PEP 723 隔离运行：yt-dlp 更新频繁，而主项目
的依赖树已经在 Pillow 上和 instagrapi 打过一次架，不值得为一个下载器再冒险。

YouTube 与 Instagram 都由 yt-dlp 处理，因此只有一个工具、一套依赖。对
Instagram 这还有个要紧的好处：走的是公开页面而不是登录态，不会给刚建好的
发布账号增加任何 API 调用。代价是私密账号和仅限关注者的内容取不到。

    uv run --no-project scripts/download_clip.py <url>
    uv run --no-project scripts/download_clip.py <url> --start 12 --end 28
    uv run --no-project scripts/download_clip.py <url> --dest template --name spiderman

在本机下载、再用 ``sync_bait.py`` 推到服务器：YouTube 对数据中心 IP 会弹人机
验证，而家用宽带不会。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys

ASSET_DIR = "resource/brainrotVideo"
MAX_SLUG_LENGTH = 60


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:MAX_SLUG_LENGTH].rstrip("-") or "clip"


FFMPEG_CACHE = os.path.join(
    os.path.expanduser("~"), ".cache", "moneyprinterturbo", "ffmpeg-bin"
)


def find_ffmpeg() -> str:
    """
    优先用系统 ffmpeg，找不到再退回 imageio-ffmpeg 自带的二进制。

    服务器上装了系统版，本机没有；把兜底写进依赖比要求两台机器保持一致更省事。

    兜底的二进制名为 ``ffmpeg-linux-x86_64-v7.0.2``，而 yt-dlp 只按 ``ffmpeg``
    这个确切文件名去目录里找，因此这里在缓存目录建一个符号链接，让它落在
    yt-dlp 预期的名字上。
    """
    system = shutil.which("ffmpeg")
    if system:
        return system

    import imageio_ffmpeg

    bundled = imageio_ffmpeg.get_ffmpeg_exe()
    os.makedirs(FFMPEG_CACHE, exist_ok=True)
    link = os.path.join(FFMPEG_CACHE, "ffmpeg")
    if not os.path.exists(link) or os.path.realpath(link) != os.path.realpath(bundled):
        if os.path.lexists(link):
            os.remove(link)
        os.symlink(bundled, link)
    return link


def trim(source: str, destination: str, ffmpeg: str, start: float, end: float | None) -> None:
    """
    按时间裁剪。重新编码而不是流拷贝：流拷贝只能从关键帧切，
    实际起点可能和请求差上几秒，而这里的素材本来就只有十几秒。
    """
    command = [ffmpeg, "-v", "error", "-y", "-ss", str(start)]
    if end is not None:
        command += ["-to", str(end)]
    command += ["-i", source, "-c:v", "libx264", "-c:a", "aac", destination]
    subprocess.run(command, check=True)


def download(url: str, dest_dir: str, name: str, ffmpeg: str, cookies: str = "") -> str:
    import yt_dlp

    os.makedirs(dest_dir, exist_ok=True)
    template = os.path.join(dest_dir, f"{name}.%(ext)s" if name else "%(title).60B.%(ext)s")

    options = {
        "outtmpl": template,
        "format": "bestvideo[ext=mp4][height<=1920]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "ffmpeg_location": os.path.dirname(ffmpeg),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "restrictfilenames": True,
    }
    # YouTube 会对数据中心 IP 弹出人机验证，服务器上必然撞上。常规做法是在本机
    # 下载再同步过去；确实需要在服务器上取时，可以带上导出的 cookies。
    if cookies:
        options["cookiefile"] = cookies

    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)
        path = downloader.prepare_filename(info)

    # 合并后的容器可能与 prepare_filename 的推断不同，按实际落盘的文件校正。
    if not os.path.isfile(path):
        base = os.path.splitext(path)[0]
        candidates = [base + ext for ext in (".mp4", ".mkv", ".webm")]
        found = [candidate for candidate in candidates if os.path.isfile(candidate)]
        if not found:
            raise SystemExit(f"download finished but no file was found near {path}")
        path = found[0]
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download a YouTube or Instagram video into the brainrot assets.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("url", help="YouTube or Instagram URL")
    parser.add_argument("--dest", default="bait", choices=("bait", "template"),
                        help="which asset folder to fill")
    parser.add_argument("--name", default="", help="output filename without extension")
    parser.add_argument("--start", type=float, default=0.0, help="trim from this second")
    parser.add_argument("--end", type=float, default=None, help="trim up to this second")
    parser.add_argument("--cookies", default="",
                        help="Netscape cookies file, for hosts that challenge datacenter IPs")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    ffmpeg = find_ffmpeg()
    dest_dir = os.path.join(project_root(), ASSET_DIR, args.dest)
    name = slugify(args.name) if args.name else ""

    print(f"downloading into {args.dest}/ ...")
    path = download(args.url, dest_dir, name, ffmpeg, args.cookies)

    if args.start or args.end is not None:
        base, extension = os.path.splitext(path)
        trimmed = f"{base}-cut{extension}"
        trim(path, trimmed, ffmpeg, args.start, args.end)
        os.remove(path)
        os.replace(trimmed, path)
        span = f"{args.start}s -> {args.end if args.end is not None else 'end'}"
        print(f"trimmed {span}")

    size = os.path.getsize(path) / 1e6
    print(f"\n{os.path.relpath(path, project_root())}  ({size:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
