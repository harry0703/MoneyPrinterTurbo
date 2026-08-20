"""
在浏览器里查看服务器上已生成的视频，不必先把文件下载到本地。

作为现有 WebUI 的一个子页面提供。原本想独立成一个应用跑在单独端口上，
但云端安全组只放行了现有端口，因此复用已经可访问的 WebUI 更可靠，
用户也不需要再开一个地址。

带宽是这个页面的主要约束：成片约 15 MB 一条，通过手机热点逐条查看很快
就会把流量用完。因此默认播放按需生成的低清预览（约 2 MB），只有在需要
确认成片质量时才切换到原片。
"""

import json
import os
import subprocess
import sys

import streamlit as st

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
)

from app.utils import utils  # noqa: E402

PREVIEW_SUFFIX = ".preview.mp4"
PREVIEW_HEIGHT = 854
PREVIEW_VIDEO_BITRATE = "400k"
PREVIEW_AUDIO_BITRATE = "48k"


st.set_page_config(page_title="MoneyPrinterTurbo — Videos", page_icon="🎬", layout="wide")


def _plan_path() -> str:
    return os.path.join(utils.root_dir(), "content_plan.json")


def _state_path() -> str:
    return os.path.join(utils.storage_dir(create=True), "content_plan_state.json")


@st.cache_data(ttl=10)
def load_plan() -> dict:
    try:
        with open(_plan_path(), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"accounts": {}, "schedule": []}


def load_state() -> dict:
    # 状态随每次生成变化，不做缓存，避免刚跑完的视频看不到。
    try:
        with open(_state_path(), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def human_size(path: str) -> str:
    try:
        return f"{os.path.getsize(path) / 1048576:.1f} MB"
    except OSError:
        return "—"


@st.cache_data(show_spinner=False)
def probe_duration(path: str, size: int) -> float:
    """``size`` 参与缓存键，文件被替换后会自动重新探测。"""
    try:
        result = subprocess.run(
            [
                utils.get_ffmpeg_binary().replace("ffmpeg", "ffprobe"),
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1",
                path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        return float(result.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def build_preview(source: str) -> str | None:
    """
    生成并缓存低清预览。

    预览只用于确认画面节奏、字幕大小和配乐是否合适，不需要原始码率。
    体积约为成片的六分之一，对流量有限的连接差别很大。
    """
    # 预览文件名必须由源文件派生：计划视频各自独占一个任务目录，而 brainrot
    # 视频全部堆在同一个目录里，固定文件名会让它们互相覆盖。
    preview_path = os.path.splitext(source)[0] + PREVIEW_SUFFIX
    if os.path.isfile(preview_path) and os.path.getmtime(preview_path) >= os.path.getmtime(source):
        return preview_path

    try:
        subprocess.run(
            [
                utils.get_ffmpeg_binary(),
                "-y", "-hide_banner", "-loglevel", "error",
                "-i", source,
                "-vf", f"scale=-2:{PREVIEW_HEIGHT}",
                "-c:v", "libx264", "-b:v", PREVIEW_VIDEO_BITRATE, "-preset", "veryfast",
                "-c:a", "aac", "-b:a", PREVIEW_AUDIO_BITRATE,
                "-movflags", "+faststart",
                preview_path,
            ],
            capture_output=True, text=True, timeout=600, check=True,
        )
        return preview_path
    except (OSError, subprocess.SubprocessError):
        return None


def collect_videos() -> list[dict]:
    """把计划条目和已生成的成片对应起来，按账号和编号排序。"""
    plan = load_plan()
    state = load_state()
    entries = {entry["id"]: entry for entry in plan.get("schedule", [])}

    videos = []
    for entry_id, record in state.items():
        path = record.get("video_path")
        if not path or not os.path.isfile(path):
            continue
        entry = entries.get(entry_id, {})
        videos.append(
            {
                "id": entry_id,
                "account": entry.get("account", "unsorted"),
                "subject": entry.get("subject", entry_id),
                "date": entry.get("date", ""),
                "status": record.get("status", ""),
                "url": record.get("url"),
                "path": path,
            }
        )
    return sorted(videos, key=lambda item: (item["account"], item["id"]))


def collect_brainrot() -> list[dict]:
    """
    收集 brainrot 视频。

    它们不属于内容计划，因此没有条目可查，只能直接扫描输出目录。生成时留下的
    同名 JSON 提供文字卡与诱饵素材；早于该机制的文件回退到文件名。
    """
    directory = os.path.join(utils.storage_dir(create=True), "brainrot")
    if not os.path.isdir(directory):
        return []

    videos = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".mp4") or name.endswith(PREVIEW_SUFFIX):
            continue
        path = os.path.join(directory, name)
        stem = os.path.splitext(path)[0]

        meta = {}
        try:
            with open(f"{stem}.json", "r", encoding="utf-8") as handle:
                meta = json.load(handle)
        except (OSError, json.JSONDecodeError):
            pass

        videos.append(
            {
                "id": os.path.splitext(name)[0],
                "account": "brainrot",
                "subject": meta.get("text") or os.path.splitext(name)[0],
                "date": meta.get("created", ""),
                # 变体决定观感差异，比诱饵文件名更值得直接看到。
                "status": meta.get("style", "") or meta.get("bait", ""),
                "bait": meta.get("bait", ""),
                "url": None,
                "path": path,
            }
        )
    return videos


videos = collect_videos() + collect_brainrot()

st.title("🎬 Generated videos")

if not videos:
    st.info(
        "No video yet. Render one with "
        "`uv run python run_plan.py --account why --next --no-publish`, "
        "or a brainrot one with "
        "`uv run python scripts/make_brainrot.py --text \"...\"`."
    )
    st.stop()

accounts = sorted({video["account"] for video in videos})

with st.sidebar:
    st.header("Filter")
    selected_accounts = st.multiselect("Account", accounts, default=accounts)
    quality = st.radio(
        "Quality",
        ["Preview (~2 MB)", "Original (~15 MB)"],
        help="Preview is re-encoded once and cached. Use it to check pacing, "
             "subtitles and music without spending mobile data on every video.",
    )
    st.caption(f"{len(videos)} video(s) on the server")

visible = [video for video in videos if video["account"] in selected_accounts]

for account in selected_accounts:
    account_videos = [video for video in visible if video["account"] == account]
    if not account_videos:
        continue

    st.subheader(f"{account} — {len(account_videos)} video(s)")

    for video in account_videos:
        size = os.path.getsize(video["path"])
        duration = probe_duration(video["path"], size)
        with st.expander(
            f"{video['id']} — {video['subject']}  ·  {duration:.0f}s · {human_size(video['path'])}",
            expanded=False,
        ):
            columns = st.columns([2, 3])
            with columns[0]:
                if quality.startswith("Preview"):
                    with st.spinner("Preparing preview…"):
                        playable = build_preview(video["path"])
                    if playable is None:
                        st.warning("Preview failed, falling back to the original file.")
                        playable = video["path"]
                else:
                    playable = video["path"]
                st.video(playable)

            with columns[1]:
                if video["account"] == "brainrot":
                    st.write(f"**Rendered** {video['date'] or '—'}")
                    st.write(f"**Style** {video['status'] or '—'}")
                    st.write(f"**Bait** {video.get('bait') or '—'}")
                else:
                    st.write(f"**Scheduled** {video['date'] or '—'}")
                    st.write(f"**Status** {video['status'] or '—'}")
                if video["url"]:
                    st.write(f"**Published** {video['url']}")
                st.code(video["path"], language=None)
