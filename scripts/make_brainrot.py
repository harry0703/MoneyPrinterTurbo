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
import datetime
import json
import os
import random
import sys
from dataclasses import dataclass, field

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BAIT_DIR = "resource/brainrotVideo/bait"
TEMPLATE_DEFAULT = "resource/brainrotVideo/template/Polyester Spiderman Edit Template.mp4"
FONT_DEFAULT = "resource/fonts/BeVietnamPro-Bold.ttf"
OUTPUT_DIR = "storage/brainrot"

VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".webm", ".m4v")

# 诱饵段的时长。参考样片是 10~14 秒：短于 8 秒观众来不及读完文字卡，
# 长于 15 秒则在剪辑开始前就流失。
DEFAULT_BAIT_SECONDS = 7
# 入侵持续多久。样片约 3~4 秒，短了像掉帧，长了会让人以为视频坏了。
DEFAULT_INVASION_SECONDS = 4.8
# 每隔这么久叠一个新的播放实例。
DEFAULT_PANEL_INTERVAL = 0.3
# 每个实例自带的那份声音。六份错开叠加后整体电平与单份 1.2 相当，
# 但六份都听得见；再往上主要换来削波失真，而不是响度。
DEFAULT_STUTTER_VOLUME = 0.8



@dataclass(frozen=True)
class Cameo:
    """
    诱饵段里剪辑的一次短暂露面。

    正式入侵之前先让剪辑闪一下，观众会下意识等着它回来，诱饵段因此没那么容易
    被划走。``speed`` 同时作用于画面与声音：加速播放会把音高一起抬上去，
    这正是那种尖锐感的来源。
    """

    start: float          # 在成片时间轴上的出现时刻
    duration: float       # 在画面上停留多久
    kind: str = "flash"   # flash 定点闪现，sweep 横向掠过
    speed: float = 1.0    # 播放与音高倍率
    direction: int = 1    # sweep 专用：1 从左到右，-1 从右到左
    scale: float = 0.34   # 相对画面宽度的尺寸


@dataclass(frozen=True)
class Style:
    """一种变体。只覆盖与 classic 不同的部分，其余走默认值。"""

    bait_seconds: float | None = None
    invasion_seconds: float | None = None
    panel_interval: float | None = None
    edit_speed: float = 1.0
    cameos: tuple[Cameo, ...] = field(default_factory=tuple)


STYLES = {
    # 基准版：诱饵、入侵、剪辑，没有任何前置提示。
    "classic": Style(),
    # 剪辑先闪两下，各 0.1 秒，快到看不清是什么——正因为看不清才会想再看。
    "flash": Style(
        cameos=(
            Cameo(start=2.0, duration=0.1),
            Cameo(start=4.5, duration=0.1),
        )
    ),
    # 剪辑横穿画面两次，回程加速一倍因而音调更高，第二次比第一次更急。
    "sweep": Style(
        cameos=(
            Cameo(start=2.0, duration=2.0, kind="sweep", direction=1),
            Cameo(start=5.0, duration=1.0, kind="sweep", direction=-1, speed=2.0),
        )
    ),
    # 整段加速：入侵更密更短，剪辑本身也快放，音调随之抬高。
    "rush": Style(
        invasion_seconds=1.5,
        panel_interval=0.12,
        edit_speed=1.5,
    ),
}


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
    panel_interval: float = DEFAULT_PANEL_INTERVAL,
    stutter_volume: float = DEFAULT_STUTTER_VOLUME,
    cameos: tuple = (),
    edit_speed: float = 1.0,
):
    import numpy as np
    from moviepy import AudioFileClip, CompositeAudioClip, VideoClip, VideoFileClip, afx
    from PIL import Image

    from app.services.utils import brainrot_render as render

    bait = VideoFileClip(bait_path)
    template = VideoFileClip(template_path)

    invasion_start = bait_seconds
    invasion_end = bait_seconds + invasion_seconds

    def pitched(audio, speed: float):
        """加速播放，音高随之抬高。这里没有独立的变调特效，速度就是音高。"""
        if speed == 1.0:
            return audio
        return audio.time_transform(lambda t: speed * t).with_duration(
            audio.duration / speed
        )

    # 入侵期间第一个实例已经把剪辑放了这么久，正片从那里接着走。从头重放会让
    # 刚看过的几秒再来一遍，衔接处像卡住了。
    resume_at = min(invasion_seconds * edit_speed, max(0.0, template.duration - 1e-3))
    total = invasion_end + (template.duration - resume_at) / edit_speed

    card = render.render_text_card(
        text=text,
        font_path=font_path,
        font_size=int(height * CARD_FONT_RATIO),
        max_width=int(width * 0.92),
    )
    card_image = Image.fromarray(card)
    card_x = (width - card_image.width) // 2
    card_y = int(height * CARD_TOP_RATIO)

    # 入侵阶段每个实例、以及每个客串镜头，都从剪辑开头放起，需要的只是开头
    # 这几秒。预先解码成帧表，否则每输出一帧就要在文件里随机定位十几次。
    preload_seconds = max(
        [invasion_seconds * edit_speed]
        + [cameo.duration * cameo.speed for cameo in cameos]
    )
    instance_frames = [
        template.get_frame(min(index / fps, template.duration - 1e-3))
        for index in range(int(preload_seconds * fps) + 2)
    ]

    def edit_frame_at(source_seconds: float) -> np.ndarray:
        index = min(int(source_seconds * fps), len(instance_frames) - 1)
        return instance_frames[max(0, index)]

    def bait_frame(t: float) -> np.ndarray:
        # 诱饵短于诱饵段时回绕播放，避免最后一帧定格。
        return render.crop_to_aspect(
            bait.get_frame(t % bait.duration), width, height
        )

    def make_frame(t: float) -> np.ndarray:
        if t >= invasion_end:
            # 正式剪辑保持 16:9 原比例，上下留黑边；进度接着第一个实例继续。
            offset = min(
                resume_at + (t - invasion_end) * edit_speed, template.duration - 1e-3
            )
            return render.letterbox(template.get_frame(offset), width, height)

        base = Image.fromarray(bait_frame(t))

        if t >= invasion_start:
            elapsed = t - invasion_start
            for x, y, panel_w, panel_h, start in render.panel_schedule(
                elapsed, width, height, seed=seed, interval=panel_interval
            ):
                frame = edit_frame_at((elapsed - start) * edit_speed)
                panel = render.crop_to_aspect(frame, panel_w, panel_h)
                base.paste(Image.fromarray(panel), (x, y))
        else:
            # 客串镜头只出现在诱饵段；入侵一开始它们就没有意义了。
            for index, cameo in enumerate(cameos):
                if not cameo.start <= t < cameo.start + cameo.duration:
                    continue
                local = t - cameo.start
                x, y, panel_w, panel_h = render.cameo_rect(
                    width, height, cameo.scale, local / cameo.duration,
                    kind=cameo.kind, direction=cameo.direction, seed=seed + index,
                )
                frame = edit_frame_at(local * cameo.speed)
                panel = render.crop_to_aspect(frame, panel_w, panel_h)
                base.paste(Image.fromarray(panel), (x, y))

        # 文字卡在入侵开始时撤走：样片里剪辑一露头，文字就没了。
        if t < invasion_start:
            base.paste(card_image, (card_x, card_y), card_image)

        return np.array(base.convert("RGB"))

    clip = VideoClip(make_frame, duration=total)

    audio_parts = []
    if bait.audio is not None:
        audio_parts.append(
            bait.audio.subclipped(0, min(bait_seconds, bait.audio.duration))
        )
    if template.audio is not None:
        # 每份声音一直放到正片剪辑接手为止，和画面里的实例完全同步：先前把它
        # 截断成固定的一小段，结果新实例出现时旧的已经静音，六层叠加只剩两层
        # 在响——看得到堆叠却听不到。
        for _, _, _, _, start in render.panel_schedule(
            invasion_seconds, width, height, seed=seed, interval=panel_interval
        ):
            length = min(invasion_seconds - start, template.audio.duration)
            if length <= 0:
                continue
            audio_parts.append(
                pitched(
                    template.audio.subclipped(0, min(length * edit_speed,
                                                     template.audio.duration)),
                    edit_speed,
                )
                .with_start(invasion_start + start)
                .with_effects([afx.MultiplyVolume(stutter_volume)])
            )

        # 客串镜头各自带声，画面一闪，声音跟着一记。
        for cameo in cameos:
            span = min(cameo.duration * cameo.speed, template.audio.duration)
            audio_parts.append(
                pitched(template.audio.subclipped(0, span), cameo.speed)
                .with_start(cameo.start)
                .with_effects([afx.MultiplyVolume(stutter_volume)])
            )

        # 声音同样接着走：第一个实例正好放到 resume_at，两段无缝相接。
        audio_parts.append(
            pitched(template.audio.subclipped(resume_at), edit_speed)
            .with_start(invasion_end)
        )
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
    parser.add_argument("--style", default="classic", choices=sorted(STYLES),
                        help="which variant to render")
    # 这三项默认留空，用于区分"用户没给"和"用户给了默认值"：
    # 只有真正给出时才压过 style 的设定。
    parser.add_argument("--bait-seconds", type=float, default=None)
    parser.add_argument("--invasion-seconds", type=float, default=None)
    parser.add_argument("--panel-interval", type=float, default=None,
                        help="seconds between two stacked copies of the edit")
    parser.add_argument("--stutter-volume", type=float, default=DEFAULT_STUTTER_VOLUME,
                        help="volume of each stacked copy's audio")
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

    style = STYLES[args.style]
    def resolve(explicit, from_style, fallback):
        if explicit is not None:
            return explicit
        return fallback if from_style is None else from_style

    bait_seconds = resolve(args.bait_seconds, style.bait_seconds, DEFAULT_BAIT_SECONDS)
    invasion_seconds = resolve(
        args.invasion_seconds, style.invasion_seconds, DEFAULT_INVASION_SECONDS
    )
    panel_interval = resolve(
        args.panel_interval, style.panel_interval, DEFAULT_PANEL_INTERVAL
    )

    output_path = args.out or os.path.join(
        OUTPUT_DIR, f"brainrot-{args.style}-{seed}.mp4"
    )
    print(f"style    {args.style}")
    print(f"bait     {os.path.basename(bait_path)}")
    print(f"text     {args.text}")
    print(f"seed     {seed}")

    metadata = {
        "text": args.text,
        "style": args.style,
        "bait": os.path.basename(bait_path),
        "seed": seed,
        "created": datetime.date.today().isoformat(),
    }

    duration = build_video(
        bait_path=bait_path,
        template_path=args.template,
        text=args.text,
        output_path=output_path,
        width=args.width,
        height=args.height,
        fps=args.fps,
        bait_seconds=bait_seconds,
        invasion_seconds=invasion_seconds,
        font_path=args.font,
        seed=seed,
        panel_interval=panel_interval,
        stutter_volume=args.stutter_volume,
        cameos=style.cameos,
        edit_speed=style.edit_speed,
    )
    # 同名 JSON 让画廊页面能显示文字卡和诱饵来源：文件名里只有一个随机数，
    # 光看列表分不出哪条是哪条。
    metadata["duration"] = round(duration, 2)
    with open(os.path.splitext(output_path)[0] + ".json", "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)

    print(f"\n{output_path}  ({duration:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
