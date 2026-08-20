#!/usr/bin/env python3
"""
生成"诱饵 + 剪辑入侵"格式的短视频。

这个格式与主流水线没有共同之处：不写脚本、不合成语音、不检索素材库。它只做
三件事——取一段诱饵素材、压上一张固定文字卡、让一段现成剪辑从中途逐渐侵占
画面直到结束。因此它是一个独立脚本，而不是 VideoParams 上的又一组开关。

诱饵素材必须由使用者提供：这个格式成立的前提是画面粗糙、随手、不合逻辑，
而素材库提供的是打光考究的专业空镜，恰好是反面。

    uv run python scripts/make_brainrot.py --next
    uv run python scripts/make_brainrot.py --list
    uv run python scripts/make_brainrot.py --style rush --card

文案不必每次自己想：省略 --text 就从 brainrot_texts.json 里取一条。这条文案
默认只当发布时的标题，不画到画面上；要压成文字卡，加 --card。
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

def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Chemins absolus : ces valeurs partent en défaut d'arguments et servaient de
# chemins relatifs, donc dépendants du répertoire courant. Depuis cron ou depuis
# un autre dossier, on lisait le mauvais dossier d'appâts sans le voir.
BAIT_DIR = os.path.join(project_root(), "resource", "brainrotVideo", "bait")
TEMPLATE_DEFAULT = os.path.join(
    project_root(), "resource", "brainrotVideo", "template",
    "Polyester Spiderman Edit Template.mp4",
)
FONT_DEFAULT = os.path.join(project_root(), "resource", "fonts",
                            "BeVietnamPro-Bold.ttf")
OUTPUT_DIR = os.path.join(project_root(), "storage", "brainrot")

VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".webm", ".m4v")

# 诱饵段的时长。文字卡取消之后，这段不再需要留出阅读时间，只要够看出画面
# 有多随手就行；classic 和 rush 因此缩到 3.5 秒。flash 和 sweep 仍用这个值，
# 它们要在入侵之前放进客串镜头，压缩之后那些镜头就没地方待了。
DEFAULT_BAIT_SECONDS = 7
# 没有客串镜头的变体，诱饵段可以短得多。
SHORT_BAIT_SECONDS = 3.5
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
    "classic": Style(bait_seconds=SHORT_BAIT_SECONDS),
    # 剪辑先闪两下，各 0.3 秒：够看清是什么，又短到留不下完整印象。
    "flash": Style(
        cameos=(
            Cameo(start=2.0, duration=0.3),
            Cameo(start=4.5, duration=0.3),
        )
    ),
    # 剪辑横穿画面两次，回程加速一倍因而音调更高，第二次比第一次更急。
    "sweep": Style(
        cameos=(
            Cameo(start=2.0, duration=2.0, kind="sweep", direction=1),
            Cameo(start=5.0, duration=1.0, kind="sweep", direction=-1, speed=2.0),
        )
    ),
    # 整段加速：入侵更密，剪辑本身也快放，音调随之抬高。入侵不能太短——
    # 第一个实例要正好放到剪辑自己的重拍上，接手的瞬间才不会踩空。
    "rush": Style(
        bait_seconds=SHORT_BAIT_SECONDS,
        invasion_seconds=3.5,
        panel_interval=0.12,
        edit_speed=1.5,
    ),
}


# 每个剪辑模板配一张封面图，写成成片的第一帧。Instagram 取封面时会落在开头，
# 用文件名作键而不是按目录约定，是因为封面和模板本来就未必同名。
THUMBNAILS = {
    "Polyester Spiderman Edit Template.mp4":
        "resource/brainrotVideo/Miniature/miniature_spiderman.png",
}


def resolve_thumbnail(template_path: str, explicit: str, disabled: bool) -> str:
    """按模板挑封面。显式给出的优先，找不到就不放封面，而不是报错。"""
    if disabled:
        return ""
    if explicit:
        return explicit
    return THUMBNAILS.get(os.path.basename(template_path), "")


TEXTS_FILENAME = "brainrot_texts.json"
STATE_FILENAME = "brainrot_state.json"

# 变体的抽取权重。数值直接是百分比，四项相加为 100。
STYLE_WEIGHTS = {
    "classic": 15,
    "sweep": 25,
    "flash": 30,
    "rush": 30,
}


def weighted_style(rng: random.Random, weights: dict | None = None) -> str:
    """按权重抽一个变体。"""
    weights = weights or STYLE_WEIGHTS
    names = sorted(weights)
    return rng.choices(names, weights=[weights[name] for name in names], k=1)[0]


def next_bait(clips: list[str], used: list[str]) -> str:
    """
    取第一个还没用过的诱饵，按文件名排序。

    按顺序而不是随机：随机会在素材还剩很多时就重复，而重复的诱饵正是平台
    判定"模板化生产"的依据。用完为止，不回头再用。
    """
    consumed = set(used)
    for clip in clips:
        if os.path.basename(clip) not in consumed:
            return clip
    return ""


def load_state() -> dict:
    from app.utils import utils

    path = os.path.join(utils.storage_dir(create=True), STATE_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_state(state: dict) -> None:
    from app.utils import utils

    path = os.path.join(utils.storage_dir(create=True), STATE_FILENAME)
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def load_texts() -> list[str]:
    path = os.path.join(project_root(), TEXTS_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read {TEXTS_FILENAME}: {exc}")
    return [line for line in payload.get("texts", []) if line.strip()]


def random_text(rng: random.Random) -> str:
    """从文案池里随便抽一条，不动索引。"""
    texts = load_texts()
    if not texts:
        raise SystemExit(
            f"{TEXTS_FILENAME} has no usable line; add one or pass --text"
        )
    return rng.choice(texts)


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
    thumbnail_path: str = "",
    show_card: bool = False,
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

    # 文字卡默认不画。诱饵素材本身已经足够无厘头，压一张白卡上去反而像个
    # 模板；这条线仍然写进旁边的 JSON，用作发布时的标题。
    card_image = None
    if show_card and text:
        card_image = Image.fromarray(
            render.render_text_card(
                text=text,
                font_path=font_path,
                font_size=int(height * CARD_FONT_RATIO),
                max_width=int(width * 0.92),
            )
        )
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

    # 只占第一帧。Instagram 取封面时会落在视频开头，而 1/fps 秒的停留短到
    # 几乎看不出来——不是完全看不见，注意看仍会察觉闪了一下。
    cover_frame = None
    if thumbnail_path and os.path.isfile(thumbnail_path):
        with Image.open(thumbnail_path) as cover:
            cover_frame = render.crop_to_aspect(
                np.array(cover.convert("RGB")), width, height
            )
    elif thumbnail_path:
        print(f"thumbnail not found, skipping: {thumbnail_path}")

    def bait_frame(t: float) -> np.ndarray:
        # 诱饵短于诱饵段时回绕播放，避免最后一帧定格。
        return render.crop_to_aspect(
            bait.get_frame(t % bait.duration), width, height
        )

    def make_frame(t: float) -> np.ndarray:
        if cover_frame is not None and t < 0.5 / fps:
            return cover_frame

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
        if card_image is not None and t < invasion_start:
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
    parser.add_argument("--text", default="",
                        help="the line shown on the text card "
                             f"(default: one from {TEXTS_FILENAME})")
    parser.add_argument("--bait-dir", default=BAIT_DIR, help="folder of bait clips")
    parser.add_argument("--bait-file", default="", help="use this exact bait clip")
    parser.add_argument("--template", default=TEMPLATE_DEFAULT, help="the edit to splice in")
    parser.add_argument("--font", default=FONT_DEFAULT)
    parser.add_argument("--out", default="", help="output file")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    # Défaut à None pour distinguer "non précisé" de "classic demandé" :
    # avec --next, non précisé veut dire "tire selon les pondérations".
    parser.add_argument("--style", default=None, choices=sorted(STYLES),
                        help="which variant to render (default: classic, "
                             "or weighted random with --next)")
    parser.add_argument("--next", action="store_true",
                        help="take the next unused bait clip and the next text, "
                             "and pick a style at random by weight")
    # 这三项默认留空，用于区分"用户没给"和"用户给了默认值"：
    # 只有真正给出时才压过 style 的设定。
    parser.add_argument("--bait-seconds", type=float, default=None)
    parser.add_argument("--invasion-seconds", type=float, default=None)
    parser.add_argument("--panel-interval", type=float, default=None,
                        help="seconds between two stacked copies of the edit")
    parser.add_argument("--stutter-volume", type=float, default=DEFAULT_STUTTER_VOLUME,
                        help="volume of each stacked copy's audio")
    parser.add_argument("--thumbnail", default="",
                        help="cover image to write as the first frame "
                             "(defaults to the one mapped to the template)")
    parser.add_argument("--no-thumbnail", action="store_true",
                        help="render without a cover frame")
    parser.add_argument("--card", action="store_true",
                        help="burn the line onto the video as a text card; "
                             "off by default, the line only becomes the caption")
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

    seed = args.seed or random.randrange(1, 10**6)
    rng = random.Random(seed)

    state = load_state() if args.next else {}
    style_name = args.style or "classic"

    if args.next:
        clips = list_bait(args.bait_dir)
        if not clips:
            raise SystemExit(f"no bait clips in {args.bait_dir}")

        used = state.get("used_bait", [])
        bait_path = next_bait(clips, used)
        if not bait_path:
            raise SystemExit(
                f"every bait clip in {args.bait_dir} has been used "
                f"({len(used)} of them); add more before the next run"
            )

        texts = load_texts()
        text_index = int(state.get("text_index", 0))
        if text_index >= len(texts):
            raise SystemExit(
                f"the text pool is exhausted ({len(texts)} lines used); "
                f"add more to {TEXTS_FILENAME}"
            )
        text = args.text or texts[text_index]
        style_name = args.style or weighted_style(rng)
    else:
        bait_path = pick_bait(args.bait_dir, args.bait_file, rng)
        # 手动跑一条时同样从文案池里取，不必先自己想一句词。这里抽的是随机一条
        # 而不是"下一条"：推进索引是 --next 的职责，一次试渲染不该消耗排期。
        text = args.text or random_text(rng)

    args.style = style_name
    style = STYLES[style_name]
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

    thumbnail_path = resolve_thumbnail(
        args.template, args.thumbnail, args.no_thumbnail
    )

    output_path = args.out or os.path.join(
        OUTPUT_DIR, f"brainrot-{args.style}-{seed}.mp4"
    )
    print(f"style    {args.style}")
    print(f"cover    {os.path.basename(thumbnail_path) or '—'}")
    print(f"bait     {os.path.basename(bait_path)}")
    print(f"text     {text}" + ("" if args.card else "  (caption only)"))
    print(f"seed     {seed}")

    metadata = {
        "text": text,
        "style": args.style,
        "bait": os.path.basename(bait_path),
        "cover": os.path.basename(thumbnail_path),
        "card": bool(args.card),
        "seed": seed,
        "created": datetime.date.today().isoformat(),
    }

    duration = build_video(
        bait_path=bait_path,
        template_path=args.template,
        text=text,
        output_path=output_path,
        width=args.width,
        height=args.height,
        fps=args.fps,
        bait_seconds=bait_seconds,
        invasion_seconds=invasion_seconds,
        font_path=args.font,
        seed=seed,
        thumbnail_path=thumbnail_path,
        show_card=args.card,
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

    if args.next:
        # 只有真的产出了成片才推进索引：失败后重跑应当拿到同一条素材，
        # 而不是把它悄悄跳过。
        state.setdefault("used_bait", []).append(os.path.basename(bait_path))
        state["text_index"] = int(state.get("text_index", 0)) + 1
        save_state(state)

    print(f"\n{output_path}  ({duration:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
