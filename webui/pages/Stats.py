"""
在浏览器里看四个账号的数据，而不必登录 Instagram。

这一页存在的理由不是省事，而是安全：每次在浏览器里登录，平台都会看到一台
"新设备"，一旦触发安全验证，正在被定时任务使用的那份会话可能连带作废。数据
本来就能用已有会话读出来，那就没有理由再去登录。

请求刻意做得很省：一个账号一次调用，结果缓存十五分钟，刷新要手动点。逐条
去查每个链接的计数会把一次浏览变成十几个请求，那正是最该避免的访问模式。
"""

import os
import sys
from datetime import datetime

import streamlit as st

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
)

CACHE_SECONDS = 15 * 60
DEFAULT_AMOUNT = 12

st.set_page_config(page_title="MoneyPrinterTurbo — Accounts", page_icon="📈",
                   layout="wide")


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def load_stats(label: str, amount: int) -> dict:
    """一个账号一次调用。失败原因原样带回，让面板能分辨会话失效和限流。"""
    from app.services import instagram

    try:
        return instagram.fetch_stats(account=label, amount=amount)
    except Exception as exc:  # 一个账号出问题不该让整页空白
        return {"error": f"{type(exc).__name__}: {exc}"}


def account_labels() -> list[str]:
    from app.services import instagram

    try:
        return [account.label for account in instagram.list_accounts()]
    except Exception:
        return []


def when(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%d/%m %H:%M")
    except ValueError:
        return value[:16]


st.title("📈 Accounts")

labels = account_labels()
if not labels:
    st.warning("No Instagram account configured.")
    st.stop()

with st.sidebar:
    st.header("Accounts")
    selected = st.multiselect("Show", labels, default=labels)
    amount = st.slider("Reels per account", 3, 30, DEFAULT_AMOUNT)
    if st.button("Refresh now"):
        load_stats.clear()
        st.rerun()
    st.caption(
        f"Cached for {CACHE_SECONDS // 60} min. Reading these numbers uses the "
        "session the scheduler publishes with, so it is kept deliberately quiet."
    )

if not selected:
    st.info("Pick at least one account in the sidebar.")
    st.stop()

with st.spinner("Reading Instagram…"):
    data = {label: load_stats(label, amount) for label in selected}

working = {label: payload for label, payload in data.items() if "error" not in payload}

if working:
    columns = st.columns(len(working))
    for column, (label, payload) in zip(columns, working.items()):
        plays = sum(item["plays"] for item in payload["media"])
        column.metric(
            f"{label} — @{payload['username']}",
            f"{payload['followers']} followers",
            f"{plays} plays over {len(payload['media'])} reel(s)",
            delta_color="off",
        )

for label in selected:
    payload = data[label]
    st.subheader(label)

    if "error" in payload:
        # 会话失效是这里最常见的失败，而修复命令固定不变，直接写出来。
        st.error(payload["error"])
        st.code(
            f"uv run python publish_instagram.py --import-session <sessionid> "
            f"--account {label}",
            language="bash",
        )
        continue

    if not payload["media"]:
        st.info("No reel published yet.")
        continue

    st.dataframe(
        [
            {
                "Posted": when(item["taken_at"]),
                "Plays": item["plays"],
                "Likes": item["likes"],
                "Comments": item["comments"],
                "Link": f"https://www.instagram.com/reel/{item['code']}/",
                "Caption": item["caption"],
            }
            for item in payload["media"]
        ],
        hide_index=True,
        use_container_width=True,
        column_config={"Link": st.column_config.LinkColumn("Link", display_text="open")},
    )
