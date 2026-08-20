#!/usr/bin/env python3
"""
生成"诱饵 + 剪辑入侵"格式的短视频。

这个格式与主流水线没有共同之处：不写脚本、不合成语音、不检索素材库。它只做
三件事——取一段诱饵素材、压上一张固定文字卡、让一段现成剪辑从中途逐渐侵占
画面直到结束。因此它是一个独立脚本，而不是 VideoParams 上的又一组开关。

诱饵素材必须由使用者提供：这个格式成立的前提是画面粗糙、随手、不合逻辑，
而素材库提供的是打光考究的专业空镜，恰好是反面。

    uv run python scripts/make_brainrot.py --list
    uv run python scripts/make_brainrot.py --text "how it feels to check the mail"
    uv run python scripts/make_brainrot.py --bait-file clip.mp4 --seed 7
"""

from __future__ import annotations

import argparse
import os
import random
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BAIT_DIR = "resource/brainrotVideo/bait"
TEMPLATE_DEFAULT = "resource/brainrotVideo/template/Polyester Spiderman Edit Template.mp4"
FONT_DEFAULT = "resource/fonts/BeVietnamPro-Bold.ttf"
OUTPUT_DIR = "storage/brainrot"

VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".webm", ".m4v")

# 诱饵段的时长。参考样片是 10~14 秒：短于 8 秒观众来不及读完文字卡，
# 长于 15 秒则在剪辑开始前就流失。
DEFAULT_BAIT_SECONDS = 10.0
# 入侵持续多久。样片约 3~4 秒，短了像掉帧，长了会让人以为视频坏了。
DEFAULT_INVASION_SECONDS = 3.5

DEFAULT_WIDTH = 720
DEFAULT_HEIGHT = 1280
DEFAULT_FPS = 30
# 文字卡的纵向位置，相对画面高度。压在顶部安全区之下、主体之上。
CARD_TOP_RATIO = 0.06
CARD_FONT_RATIO = 0.061


def list_bait(bait_dir: str) -> list[str]:
    if not os.path.isdir(bait_dir):
        return []
    return sorted(
        os.path.join(bait_dir, name)
        for name in os.listdir(bait_dir)
        if name.lower().endswith(VIDEO_EXTENSIONS)
    )


def pick_bait(bait_dir: str, explicit: str, rng: random.Random) -> str:
    if explicit:
        if not os.path.isfile(explicit):
            raise SystemExit(f"bait clip not found: {explicit}")
        return explicit

    clips = list_bait(bait_dir)
    if not clips:
        raise SystemExit(
            f"no bait clips in {bait_dir}\n"
            "Drop a few short vertical clips there first — this format needs rough, "
            "amateur footage, which no stock library provides."
        )
    return rng.choice(clips)


def build_video(
    bait_path: str,
    template_path: str,
    text: str,
    output_path: str,
    width: int,
    height: int,
    fps: int,
    bait_seconds: float,
    invasion_seconds: float,
    font_path: str,
    seed: int,
):
    import numpy as np
    from moviepy import AudioFileClip, CompositeAudioClip, VideoClip, VideoFileClip, afx
    from PIL import Image

    from app.services.utils import brainrot_render as render

    bait = VideoFileClip(bait_path)
    template = VideoFileClip(template_path)

    # 诱饵不够长就循环，而不是缩短诱饵段：文字卡需要固定的停留时间。
    bait_seconds = min(bait_seconds, max(1.0, bait_seconds))
    total = bait_seconds + template.duration
    invasion_end = bait_seconds + invasion_seconds

    card = render.render_text_card(
        text=text,
        font_path=font_path,
        font_size=int(height * CARD_FONT_RATIO),
        max_width=int(width * 0.92),
    )
    card_image = Image.fromarray(card)
    card_x = (width - card_image.width) // 2
    card_y = int(height * CARD_TOP_RATIO)

    def bait_frame(t: float) -> np.ndarray:
        # 诱饵短于诱饵段时回绕播放，避免最后一帧定格。
        return render.crop_to_aspect(
            bait.get_frame(t % bait.duration), width, height
        )

    def template_frame(t: float) -> np.ndarray:
        offset = min(max(0.0, t - bait_seconds), template.duration - 1e-3)
        return render.crop_to_aspect(template.get_frame(offset), width, height)

    def make_frame(t: float) -> np.ndarray:
        if t >= invasion_end:
            return template_frame(t)

        base = Image.fromarray(bait_frame(t))

        if t >= bait_seconds:
            progress = (t - bait_seconds) / max(1e-6, invasion_seconds)
            edit = Image.fromarray(template_frame(t))
            for x, y, panel_w, panel_h in render.panel_rects(
                progress, width, height,
                seed=seed + render.panel_seed(t - bait_seconds),
            ):
                base.paste(edit.resize((panel_w, panel_h), Image.BILINEAR), (x, y))

        # 文字卡在入侵开始时撤走：样片里剪辑一露头，文字就没了。
        if t < bait_seconds:
            base.paste(card_image, (card_x, card_y), card_image)

        return np.array(base.convert("RGB"))

    clip = VideoClip(make_frame, duration=total)

    audio_parts = []
    if bait.audio is not None:
        audio_parts.append(
            bait.audio.subclipped(0, min(bait_seconds, bait.audio.duration))
        )
    if template.audio is not None:
        audio_parts.append(template.audio.with_start(bait_seconds))
    if audio_parts:
        clip = clip.with_audio(CompositeAudioClip(audio_parts))

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    clip.write_videofile(
        output_path, fps=fps, codec="libx264", audio_codec="aac", logger=None
    )
    for handle in (bait, template, clip):
        try:
            handle.close()
        except Exception:
            pass
    return total


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render one bait-plus-edit video.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--text", default="", help="the line shown on the text card")
    parser.add_argument("--bait-dir", default=BAIT_DIR, help="folder of bait clips")
    parser.add_argument("--bait-file", default="", help="use this exact bait clip")
    parser.add_argument("--template", default=TEMPLATE_DEFAULT, help="the edit to splice in")
    parser.add_argument("--font", default=FONT_DEFAULT)
    parser.add_argument("--out", default="", help="output file")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--bait-seconds", type=float, default=DEFAULT_BAIT_SECONDS)
    parser.add_argument("--invasion-seconds", type=float, default=DEFAULT_INVASION_SECONDS)
    parser.add_argument("--seed", type=int, default=0, help="0 picks a random one")
    parser.add_argument("--list", action="store_true", help="list available bait clips and exit")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.list:
        clips = list_bait(args.bait_dir)
        print(f"{len(clips)} bait clip(s) in {args.bait_dir}")
        for path in clips:
            print(f"  {os.path.basename(path)}")
        return 0

    if not args.text:
        raise SystemExit("--text is required: the card is the whole hook")

    seed = args.seed or random.randrange(1, 10**6)
    rng = random.Random(seed)
    bait_path = pick_bait(args.bait_dir, args.bait_file, rng)

    output_path = args.out or os.path.join(OUTPUT_DIR, f"brainrot-{seed}.mp4")
    print(f"bait     {os.path.basename(bait_path)}")
    print(f"text     {args.text}")
    print(f"seed     {seed}")

    duration = build_video(
        bait_path=bait_path,
        template_path=args.template,
        text=args.text,
        output_path=output_path,
        width=args.width,
        height=args.height,
        fps=args.fps,
        bait_seconds=args.bait_seconds,
        invasion_seconds=args.invasion_seconds,
        font_path=args.font,
        seed=seed,
    )
    print(f"\n{output_path}  ({duration:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
