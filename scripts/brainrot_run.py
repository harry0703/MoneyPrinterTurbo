#!/usr/bin/env python3
"""
生成一条 brainrot 视频并发布到测试账号。

与 ``daily_run.py`` 分开：那边一天跑一轮、三个账号轮流，节奏由"每天一条"
决定；这边每四小时一条，由 cron 直接触发一次，脚本本身不排期。合在一起会
让两种完全不同的节奏共用一套调度逻辑，改一边就会碰坏另一边。

发布频率远高于其他账号，是使用者明确选择的测试条件，不是默认值。

    uv run python scripts/brainrot_run.py --dry-run
    uv run python scripts/brainrot_run.py --no-publish
    uv run python scripts/brainrot_run.py
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import random
import subprocess
import sys
import time

from loguru import logger

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ACCOUNT = "brainrot"
LOG_DIRNAME = "logs"

# cron 固定在整点触发。四小时一条已经很规律，再让每条都精确落在 :00，
# 时间戳本身就是一条"这是机器发的"的证据。
JITTER_RANGE = (0, 25 * 60)

# 渲染撞上生成锁时的等待策略。每天中午那一轮要跑完三条视频，横跨两个多
# 小时，正好会盖住 brainrot 的一个时段；直接放弃就白白少一条。
BUSY_WAIT_SECONDS = 45 * 60
BUSY_POLL_SECONDS = 5 * 60

# 与 run_plan.py 一致：75 表示"另一条生成正在进行"，不是失败。
EXIT_BUSY = 75


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_caption_profile() -> dict:
    """文案池那个文件同时存着这个账号的标签与定位，改文案不必改代码。"""
    path = os.path.join(project_root(), "brainrot_texts.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read brainrot_texts.json: {exc}")
    return payload.get("caption", {})


def build_caption(text: str, index: int) -> str:
    """
    复用内容计划那套文案格式：卡片文字、账号两行、标签。

    直接引用而不是照抄一份：三个正式账号的标签轮换规则以后要是改了，
    这个账号不应该悄悄留在旧规则上。
    """
    import importlib.util

    profile = load_caption_profile()
    # 固定文案优先。这个账号现在挂的是一段与画面无关的日文通告，每条都一样，
    # 是使用者选定的做法，不是缺省行为。
    fixed = profile.get("fixed", "").strip()
    if fixed:
        return fixed

    spec = importlib.util.spec_from_file_location(
        "build_content_plan",
        os.path.join(project_root(), "scripts", "build_content_plan.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_caption(profile, text, index)


def next_text(index: int) -> str:
    """--dry-run 用：看下一条会配什么文字，但不推进游标。"""
    path = os.path.join(project_root(), "brainrot_texts.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            texts = [t for t in json.load(handle).get("texts", []) if t.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read brainrot_texts.json: {exc}")
    return texts[index] if index < len(texts) else ""


def state_path() -> str:
    from app.utils import utils

    return os.path.join(utils.storage_dir(create=True), "brainrot_state.json")


def read_state() -> dict:
    try:
        with open(state_path(), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_state(state: dict) -> None:
    temp_path = f"{state_path()}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, state_path())


def set_pending(video_path: str, caption: str) -> None:
    """
    记下"已渲染、还没发出去"的那一条。

    渲染一成功，素材和文案的游标就前进了，而发布可能因为会话失效或限流失败。
    没有这条记录的话，下一轮会另起一条新的，那条已经做好的视频就永远留在
    盘上——诱饵素材本来就只有十几条，丢一条就少一天。
    """
    state = read_state()
    state["pending"] = {"video": video_path, "caption": caption}
    save_state(state)


def take_pending() -> dict:
    """取出待发布的那一条，文件已经不在就当作没有。"""
    pending = read_state().get("pending") or {}
    if pending.get("video") and os.path.isfile(pending["video"]):
        return pending
    return {}


def record_published(video_path: str, url: str) -> None:
    """把已发布的一条追加进状态文件，保留素材与文案的游标不动。"""
    state = read_state()
    state.setdefault("published", []).append(
        {
            "video": os.path.basename(video_path),
            "url": url,
            "at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
    )
    state.pop("pending", None)
    save_state(state)


def generation_busy() -> str:
    """占用中返回持有者描述，空闲返回空串。"""
    from app.services import generation_lock

    try:
        with generation_lock.acquire():
            return ""
    except generation_lock.GenerationBusyError as exc:
        return str(exc)


def wait_for_lock(budget: float, poll: float, sleep=time.sleep) -> bool:
    """
    等到生成锁空出来为止，超出预算就放弃。

    只是等，不占：真正加锁的是渲染子进程。这里先抢下来再交给子进程，锁会
    在父进程手里，子进程反而拿不到。
    """
    waited = 0.0
    while True:
        owner = generation_busy()
        if not owner:
            return True
        if waited >= budget:
            logger.warning(f"still busy after {waited / 60:.0f} min: {owner}")
            return False
        logger.info(f"generation busy, retrying in {poll / 60:.0f} min: {owner}")
        sleep(poll)
        waited += poll


def render(out_path: str, extra: list[str]) -> dict:
    """跑一次 make_brainrot.py --next，返回它写下的元数据。"""
    root = project_root()
    command = [
        sys.executable,
        os.path.join(root, "scripts", "make_brainrot.py"),
        "--next",
        "--out", out_path,
    ] + extra

    logger.info("rendering")
    completed = subprocess.run(command, cwd=root)
    if completed.returncode != 0:
        raise RuntimeError(f"make_brainrot.py exited with {completed.returncode}")

    # 读旁边那份 JSON，而不是解析标准输出：文案要进标题，格式变一变就会解析错。
    meta_path = os.path.splitext(out_path)[0] + ".json"
    with open(meta_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def publish(video_path: str, caption: str) -> dict:
    root = project_root()
    command = [
        sys.executable,
        os.path.join(root, "publish_instagram.py"),
        "--video", video_path,
        "--caption", caption,
        "--account", ACCOUNT,
    ]
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True)
    # 发布脚本把结果打成一行 JSON，最后一行就是它。
    tail = [line for line in completed.stdout.splitlines() if line.strip()]
    try:
        return json.loads(tail[-1])
    except (IndexError, json.JSONDecodeError):
        raise RuntimeError(
            f"publish_instagram.py exited with {completed.returncode}: "
            f"{completed.stderr.strip()[-400:]}"
        )


def finish(video_path: str, caption: str) -> int:
    """发布一条已经渲染好的视频，成功后把它记进已发布列表。"""
    result = publish(video_path, caption)
    if not result.get("url"):
        # 保留 pending：会话失效或限流都是暂时的，下一轮直接接着发。
        logger.error(f"publish failed: {result}")
        print(json.dumps(result, ensure_ascii=False))
        return 1

    record_published(video_path, result["url"])
    logger.info(f"published {result['url']}")
    print(json.dumps(result, ensure_ascii=False))
    return 0


def setup_logging() -> str:
    from app.utils import utils

    log_dir = os.path.join(utils.storage_dir(create=True), LOG_DIRNAME)
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(
        log_dir, f"brainrot_run-{datetime.date.today():%Y%m%d}.log"
    )
    logger.add(path, level="INFO", rotation="10 MB", retention="60 days",
               encoding="utf-8", enqueue=True)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render one brainrot video and publish it.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--no-publish", action="store_true",
                        help="render only, leave the file on disk")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the caption that would be used and exit")
    parser.add_argument("--no-jitter", action="store_true",
                        help="start immediately instead of waiting a random delay")
    parser.add_argument("--style", default=None,
                        help="force a variant instead of drawing one")
    parser.add_argument("--seed", type=int, default=0, help="0 picks a random one")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    index = int(read_state().get("text_index", 0))

    if args.dry_run:
        text = next_text(index)
        if not text:
            print(f"the text pool is exhausted at index {index}")
            return 1
        print(build_caption(text, index))
        return 0

    setup_logging()

    if not args.no_jitter:
        delay = random.uniform(*JITTER_RANGE)
        logger.info(f"waiting {delay / 60:.0f} min before starting")
        time.sleep(delay)

    # 上一轮渲染成功但没发出去，先把它发掉，而不是再做一条新的。
    pending = take_pending()
    if pending and not args.no_publish:
        logger.info(f"resuming {os.path.basename(pending['video'])}")
        return finish(pending["video"], pending["caption"])

    if not wait_for_lock(BUSY_WAIT_SECONDS, BUSY_POLL_SECONDS):
        return EXIT_BUSY

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    out_path = os.path.join(project_root(), "storage", "brainrot",
                            f"brainrot-{stamp}.mp4")

    extra = []
    if args.style:
        extra += ["--style", args.style]
    if args.seed:
        extra += ["--seed", str(args.seed)]

    try:
        meta = render(out_path, extra)
    except Exception as exc:
        logger.error(f"render failed: {exc}")
        return 1

    caption = build_caption(meta.get("text", ""), index)
    logger.info(f"rendered {os.path.basename(out_path)} "
                f"[{meta.get('style')}] {meta.get('text')}")

    if args.no_publish:
        print(json.dumps({"video": out_path, "caption": caption},
                         ensure_ascii=False))
        return 0

    set_pending(out_path, caption)
    return finish(out_path, caption)


if __name__ == "__main__":
    raise SystemExit(main())
