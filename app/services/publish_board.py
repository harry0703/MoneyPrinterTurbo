"""发布台账：记录生成过的视频、平台发布标记与账号绑定关系。

本模块是纯数据层，刻意不依赖 Streamlit，只负责三件事：

1. 维护四个目标平台的预设（B站 / 小红书 / 抖音 / 快手）；
2. 用 SQLite 保存账号、视频记录，以及「视频 × 平台 × 账号」的绑定关系；
3. 从 ``storage/tasks`` 自动同步已经产出成片的任务，同时允许手动补充。

数据库文件位于 ``storage/publish_board.db``，与任务产物同目录，随 Docker
挂载卷一起持久化。写操作统一串行化并开启 WAL，保证 WebUI 多会话并发下
不会写出半条记录。

平台在库里以稳定 ID 保存（``bilibili`` 等），展示用的中英文名由预设提供，
这样界面语言切换或平台改名都不需要迁移历史数据。
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterable, Iterator, List, Optional

from loguru import logger

from app.utils import utils

# ---------------------------------------------------------------------------
# 平台预设
# ---------------------------------------------------------------------------

# 顺序即界面展示顺序。``label`` 是中文名，``label_en`` 供英文界面使用；
# 与选题工坊一样，预设自带双语文案，避免把领域数据散落到 i18n 文件里。
PLATFORMS: tuple[Dict[str, str], ...] = (
    {
        "id": "bilibili",
        "label": "B站",
        "label_en": "Bilibili",
        "color": "#00A1D6",
    },
    {
        "id": "xiaohongshu",
        "label": "小红书",
        "label_en": "Xiaohongshu",
        "color": "#FF2442",
    },
    {
        "id": "douyin",
        "label": "抖音",
        "label_en": "Douyin",
        "color": "#111111",
    },
    {
        "id": "kuaishou",
        "label": "快手",
        "label_en": "Kuaishou",
        "color": "#FF4906",
    },
)

PLATFORM_IDS: tuple[str, ...] = tuple(item["id"] for item in PLATFORMS)

# 视频记录的来源。``auto`` 表示从任务目录同步而来，``manual`` 表示用户手工补充。
ORIGIN_AUTO = "auto"
ORIGIN_MANUAL = "manual"

MAX_SUBJECT_LENGTH = 200
MAX_ACCOUNT_NAME_LENGTH = 60
MAX_ACCOUNT_ID_LENGTH = 80
MAX_URL_LENGTH = 500
MAX_REMARK_LENGTH = 500
MAX_SCRIPT_EXCERPT_LENGTH = 300

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    account_name TEXT NOT NULL,
    account_id TEXT NOT NULL DEFAULT '',
    profile_url TEXT NOT NULL DEFAULT '',
    remark TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT UNIQUE,
    subject TEXT NOT NULL DEFAULT '',
    script_excerpt TEXT NOT NULL DEFAULT '',
    video_path TEXT NOT NULL DEFAULT '',
    video_size INTEGER NOT NULL DEFAULT 0,
    generated_at TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'auto',
    platforms TEXT NOT NULL DEFAULT '[]',
    remark TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    account_id INTEGER NOT NULL,
    published_at TEXT NOT NULL DEFAULT '',
    video_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (video_id, platform),
    FOREIGN KEY (video_id) REFERENCES videos(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_accounts_platform ON accounts (platform);
CREATE INDEX IF NOT EXISTS idx_videos_task_id ON videos (task_id);
CREATE INDEX IF NOT EXISTS idx_bindings_video ON bindings (video_id);
CREATE INDEX IF NOT EXISTS idx_bindings_account ON bindings (account_id);
"""

# SQLite 连接本身不跨线程共享，这里只用一把进程内锁把「读改写」这类复合
# 操作串起来，配合 WAL 足以覆盖 WebUI 单机多会话的并发强度。
_write_lock = threading.RLock()
_schema_ready = False
_schema_lock = threading.Lock()


# ---------------------------------------------------------------------------
# 平台辅助
# ---------------------------------------------------------------------------


def list_platforms() -> List[Dict[str, str]]:
    """返回平台预设的浅拷贝，避免调用方修改模块级常量。"""
    return [dict(item) for item in PLATFORMS]


def get_platform(platform_id: str) -> Optional[Dict[str, str]]:
    for item in PLATFORMS:
        if item["id"] == platform_id:
            return dict(item)
    return None


def platform_label(platform_id: str, language: str = "zh") -> str:
    """按界面语言返回平台展示名；未知平台回退为原始 ID。"""
    item = get_platform(platform_id)
    if item is None:
        return platform_id
    if str(language or "").lower().startswith("zh"):
        return item["label"]
    return item["label_en"]


def normalize_platforms(values: Iterable[Any]) -> List[str]:
    """过滤出合法平台 ID，去重并保持预设顺序，保证落库结果稳定可比较。"""
    if isinstance(values, str):
        values = [values]
    if values is None:
        return []
    try:
        raw = {str(item).strip() for item in values}
    except TypeError:
        return []
    return [platform_id for platform_id in PLATFORM_IDS if platform_id in raw]


# ---------------------------------------------------------------------------
# 底层连接
# ---------------------------------------------------------------------------


def db_path() -> str:
    """台账数据库路径。放在 storage 下，与任务产物一起被挂载卷持久化。"""
    return os.path.join(utils.storage_dir(), "publish_board.db")


def _connect() -> sqlite3.Connection:
    path = db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path, timeout=10.0)
    connection.row_factory = sqlite3.Row
    # 外键约束默认关闭，必须逐连接打开，否则删除账号不会级联清理绑定。
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        with _write_lock, _session() as connection:
            connection.executescript(_SCHEMA)
        _schema_ready = True


@contextmanager
def _session() -> Iterator[sqlite3.Connection]:
    """打开一次短连接，退出时提交并关闭。

    ``sqlite3`` 连接直接用作上下文管理器只会提交/回滚，不会关闭，长期运行
    的 Streamlit 进程会因此不断累积文件句柄。这里显式关闭，并统一在异常时
    回滚，保证「读改写」复合操作不会留下半条记录。
    """
    connection = _connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _now() -> str:
    """本地时间字符串。台账是给人看的运营记录，直接存本地时间便于核对。"""
    return datetime.now().isoformat(timespec="seconds")


def _text(value: Any, limit: int) -> str:
    return str(value if value is not None else "").strip()[:limit]


def _as_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _decode_platforms(raw: Any) -> List[str]:
    """解析 videos.platforms 列。历史或人工改坏的数据统一降级为空数组。"""
    if isinstance(raw, (list, tuple)):
        return normalize_platforms(raw)
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning(f"invalid platforms payload in publish board: {raw!r}")
        return []
    return normalize_platforms(parsed if isinstance(parsed, list) else [])


def _encode_platforms(platforms: Iterable[Any]) -> str:
    return json.dumps(normalize_platforms(platforms), ensure_ascii=False)


# ---------------------------------------------------------------------------
# 账号
# ---------------------------------------------------------------------------


def list_accounts(platform: str = "") -> List[Dict[str, Any]]:
    """列出账号，可按平台过滤。按平台预设顺序 + 账号名排序，展示更稳定。"""
    _ensure_schema()
    with _session() as connection:
        rows = connection.execute(
            "SELECT * FROM accounts ORDER BY platform, account_name COLLATE NOCASE"
        ).fetchall()
    accounts = [_as_dict(row) for row in rows]
    if platform:
        accounts = [item for item in accounts if item["platform"] == platform]
    order = {platform_id: index for index, platform_id in enumerate(PLATFORM_IDS)}
    accounts.sort(key=lambda item: (order.get(item["platform"], 99), item["account_name"]))
    return accounts


def get_account(account_id: int) -> Optional[Dict[str, Any]]:
    _ensure_schema()
    with _session() as connection:
        row = connection.execute(
            "SELECT * FROM accounts WHERE id = ?", (int(account_id),)
        ).fetchone()
    return _as_dict(row) if row else None


def create_account(
    platform: str,
    account_name: str,
    account_id: str = "",
    profile_url: str = "",
    remark: str = "",
) -> Dict[str, Any]:
    """新建账号。平台非法或账号名为空时抛 ``ValueError``。"""
    platform = str(platform or "").strip()
    if platform not in PLATFORM_IDS:
        raise ValueError(f"unsupported platform: {platform!r}")
    name = _text(account_name, MAX_ACCOUNT_NAME_LENGTH)
    if not name:
        raise ValueError("account name is required")

    now = _now()
    _ensure_schema()
    with _write_lock, _session() as connection:
        cursor = connection.execute(
            """
            INSERT INTO accounts
                (platform, account_name, account_id, profile_url, remark,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                platform,
                name,
                _text(account_id, MAX_ACCOUNT_ID_LENGTH),
                _text(profile_url, MAX_URL_LENGTH),
                _text(remark, MAX_REMARK_LENGTH),
                now,
                now,
            ),
        )
        new_id = int(cursor.lastrowid)
    return get_account(new_id)


def update_account(account_id: int, **fields: Any) -> Optional[Dict[str, Any]]:
    """更新账号指定字段；账号不存在时返回 ``None``。"""
    allowed = {
        "platform": (MAX_ACCOUNT_NAME_LENGTH, True),
        "account_name": (MAX_ACCOUNT_NAME_LENGTH, True),
        "account_id": (MAX_ACCOUNT_ID_LENGTH, False),
        "profile_url": (MAX_URL_LENGTH, False),
        "remark": (MAX_REMARK_LENGTH, False),
    }
    assignments: List[str] = []
    values: List[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        limit, required = allowed[key]
        cleaned = _text(value, limit)
        if required and not cleaned:
            raise ValueError(f"{key} must not be empty")
        if key == "platform" and cleaned not in PLATFORM_IDS:
            raise ValueError(f"unsupported platform: {cleaned!r}")
        assignments.append(f"{key} = ?")
        values.append(cleaned)

    if not assignments:
        return get_account(account_id)

    assignments.append("updated_at = ?")
    values.append(_now())
    values.append(int(account_id))

    _ensure_schema()
    with _write_lock, _session() as connection:
        cursor = connection.execute(
            f"UPDATE accounts SET {', '.join(assignments)} WHERE id = ?",  # noqa: S608
            values,
        )
        if cursor.rowcount == 0:
            return None
    return get_account(account_id)


def count_account_bindings(account_id: int) -> int:
    """统计账号已绑定的视频数，供删除前提示使用。"""
    _ensure_schema()
    with _session() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS total FROM bindings WHERE account_id = ?",
            (int(account_id),),
        ).fetchone()
    return int(row["total"]) if row else 0


def delete_account(account_id: int) -> bool:
    """删除账号；关联绑定由外键级联清理，账号不存在时返回 ``False``。"""
    _ensure_schema()
    with _write_lock, _session() as connection:
        cursor = connection.execute(
            "DELETE FROM accounts WHERE id = ?", (int(account_id),)
        )
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# 视频记录
# ---------------------------------------------------------------------------


def _decorate_video(video: Dict[str, Any], bindings: List[Dict[str, Any]]) -> Dict[str, Any]:
    video["platforms"] = _decode_platforms(video.get("platforms"))
    video["bindings"] = {
        item["platform"]: item for item in bindings if item["video_id"] == video["id"]
    }
    return video


def list_videos(
    keyword: str = "",
    platform: str = "",
    origin: str = "",
) -> List[Dict[str, Any]]:
    """列出视频记录（含平台标记与绑定），支持关键词/平台/来源过滤。"""
    _ensure_schema()
    with _session() as connection:
        video_rows = connection.execute(
            "SELECT * FROM videos ORDER BY COALESCE(NULLIF(generated_at, ''), created_at) DESC, id DESC"
        ).fetchall()
        binding_rows = connection.execute("SELECT * FROM bindings").fetchall()

    bindings = [_as_dict(row) for row in binding_rows]
    videos = [_decorate_video(_as_dict(row), bindings) for row in video_rows]

    keyword = str(keyword or "").strip().lower()
    if keyword:
        videos = [
            item
            for item in videos
            if keyword in str(item.get("subject", "")).lower()
            or keyword in str(item.get("remark", "")).lower()
            or keyword in str(item.get("script_excerpt", "")).lower()
        ]
    if platform:
        videos = [item for item in videos if platform in item["platforms"]]
    if origin:
        videos = [item for item in videos if item["origin"] == origin]
    return videos


def get_video(video_id: int) -> Optional[Dict[str, Any]]:
    _ensure_schema()
    with _session() as connection:
        row = connection.execute(
            "SELECT * FROM videos WHERE id = ?", (int(video_id),)
        ).fetchone()
        if row is None:
            return None
        binding_rows = connection.execute(
            "SELECT * FROM bindings WHERE video_id = ?", (int(video_id),)
        ).fetchall()
    return _decorate_video(_as_dict(row), [_as_dict(item) for item in binding_rows])


def create_video(
    subject: str,
    script_excerpt: str = "",
    video_path: str = "",
    remark: str = "",
    platforms: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
    """手动补充一条视频记录。"""
    title = _text(subject, MAX_SUBJECT_LENGTH)
    if not title:
        raise ValueError("video subject is required")

    now = _now()
    size = 0
    if video_path and os.path.isfile(video_path):
        try:
            size = os.path.getsize(video_path)
        except OSError:
            size = 0

    _ensure_schema()
    with _write_lock, _session() as connection:
        cursor = connection.execute(
            """
            INSERT INTO videos
                (task_id, subject, script_excerpt, video_path, video_size,
                 generated_at, origin, platforms, remark, created_at, updated_at)
            VALUES (NULL, ?, ?, ?, ?, '', ?, ?, ?, ?, ?)
            """,
            (
                title,
                _text(script_excerpt, MAX_SCRIPT_EXCERPT_LENGTH),
                _text(video_path, MAX_URL_LENGTH),
                size,
                ORIGIN_MANUAL,
                _encode_platforms(platforms or []),
                _text(remark, MAX_REMARK_LENGTH),
                now,
                now,
            ),
        )
        new_id = int(cursor.lastrowid)
    return get_video(new_id)


def update_video(video_id: int, **fields: Any) -> Optional[Dict[str, Any]]:
    """更新视频记录的可编辑字段；记录不存在时返回 ``None``。"""
    allowed = {
        "subject": (MAX_SUBJECT_LENGTH, True),
        "remark": (MAX_REMARK_LENGTH, False),
        "video_path": (MAX_URL_LENGTH, False),
    }
    assignments: List[str] = []
    values: List[Any] = []
    for key, value in fields.items():
        if key == "platforms":
            assignments.append("platforms = ?")
            values.append(_encode_platforms(value or []))
            continue
        if key not in allowed:
            continue
        limit, required = allowed[key]
        cleaned = _text(value, limit)
        if required and not cleaned:
            raise ValueError(f"{key} must not be empty")
        assignments.append(f"{key} = ?")
        values.append(cleaned)

    if not assignments:
        return get_video(video_id)

    assignments.append("updated_at = ?")
    values.append(_now())
    values.append(int(video_id))

    _ensure_schema()
    with _write_lock, _session() as connection:
        cursor = connection.execute(
            f"UPDATE videos SET {', '.join(assignments)} WHERE id = ?",  # noqa: S608
            values,
        )
        if cursor.rowcount == 0:
            return None

    # 取消某个平台标记时，对应绑定必须一起撤销，否则台账会出现
    # 「没标记该平台却绑定了账号」的矛盾记录。
    video = get_video(video_id)
    if video is not None:
        for bound_platform in list(video["bindings"]):
            if bound_platform not in video["platforms"]:
                unbind_account(video_id, bound_platform)
        video = get_video(video_id)
    return video


def set_video_platforms(video_id: int, platforms: Iterable[Any]) -> Optional[Dict[str, Any]]:
    """设置视频的平台标记，并同步清理已取消平台的绑定。"""
    return update_video(video_id, platforms=list(platforms or []))


def delete_video(video_id: int) -> bool:
    _ensure_schema()
    with _write_lock, _session() as connection:
        cursor = connection.execute(
            "DELETE FROM videos WHERE id = ?", (int(video_id),)
        )
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# 绑定关系
# ---------------------------------------------------------------------------


def bind_account(
    video_id: int,
    platform: str,
    account_id: int,
    video_url: str = "",
) -> Optional[Dict[str, Any]]:
    """把「某视频在某平台由某账号发布」写进台账。

    同一 (视频, 平台) 只保留一条记录，重复绑定会覆盖原账号，符合
    「一个视频在一个平台上由一个账号发布」的运营习惯。
    """
    platform = str(platform or "").strip()
    if platform not in PLATFORM_IDS:
        raise ValueError(f"unsupported platform: {platform!r}")

    account = get_account(account_id)
    if account is None:
        raise ValueError(f"account not found: {account_id}")
    if account["platform"] != platform:
        raise ValueError("account platform does not match the binding platform")

    video = get_video(video_id)
    if video is None:
        raise ValueError(f"video not found: {video_id}")

    now = _now()
    _ensure_schema()
    with _write_lock, _session() as connection:
        existing = connection.execute(
            "SELECT id, published_at FROM bindings WHERE video_id = ? AND platform = ?",
            (int(video_id), platform),
        ).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO bindings
                    (video_id, platform, account_id, published_at, video_url, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(video_id),
                    platform,
                    int(account_id),
                    now,
                    _text(video_url, MAX_URL_LENGTH),
                    now,
                ),
            )
        else:
            # 换账号时保留首次发布时间，只更新账号与作品链接。
            connection.execute(
                "UPDATE bindings SET account_id = ?, video_url = ? WHERE id = ?",
                (
                    int(account_id),
                    _text(video_url, MAX_URL_LENGTH),
                    int(existing["id"]),
                ),
            )
    return get_video(video_id)


def unbind_account(video_id: int, platform: str) -> bool:
    _ensure_schema()
    with _write_lock, _session() as connection:
        cursor = connection.execute(
            "DELETE FROM bindings WHERE video_id = ? AND platform = ?",
            (int(video_id), str(platform or "").strip()),
        )
        return cursor.rowcount > 0


def list_bindings(
    account_id: Optional[int] = None,
    video_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """列出绑定关系，可按账号或视频过滤。

    账号页用它展示「该账号发过哪些视频」，视频页用它核对某个视频的全部
    平台归属；两个过滤条件可同时使用。
    """
    _ensure_schema()
    clauses: List[str] = []
    values: List[Any] = []
    if account_id is not None:
        clauses.append("account_id = ?")
        values.append(int(account_id))
    if video_id is not None:
        clauses.append("video_id = ?")
        values.append(int(video_id))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

    with _session() as connection:
        rows = connection.execute(
            f"SELECT * FROM bindings{where} ORDER BY platform, id",  # noqa: S608
            values,
        ).fetchall()
    return [_as_dict(row) for row in rows]


# ---------------------------------------------------------------------------
# 从任务目录自动同步
# ---------------------------------------------------------------------------


def _find_final_video(task_path: str) -> str:
    """返回任务目录中优先展示的成片路径（优先 final-1.mp4）。"""
    try:
        names = os.listdir(task_path)
    except OSError:
        return ""

    finals = sorted(
        (name for name in names if name.startswith("final-") and name.endswith(".mp4")),
        key=lambda name: (len(name), name),
    )
    if not finals:
        return ""
    return os.path.join(task_path, finals[0])


def _load_task_script(task_path: str) -> Dict[str, Any]:
    script_file = os.path.join(task_path, "script.json")
    if not os.path.isfile(script_file):
        return {}
    try:
        with open(script_file, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.debug(f"skip unreadable task script: {script_file}, {exc}")
        return {}
    return payload if isinstance(payload, dict) else {}


def sync_from_tasks() -> Dict[str, int]:
    """把 ``storage/tasks`` 下已产出成片的任务补进台账。

    只新增、不覆盖：已经在台账里的任务保持用户编辑过的平台标记和备注不变，
    仅刷新成片路径、体积与生成时间，避免同步把手工维护的信息冲掉。
    """
    tasks_root = utils.task_dir()
    if not os.path.isdir(tasks_root):
        return {"scanned": 0, "added": 0, "updated": 0}

    scanned = 0
    added = 0
    updated = 0
    try:
        entries = sorted(os.scandir(tasks_root), key=lambda item: item.name)
    except OSError as exc:
        logger.warning(f"failed to scan task directory for publish board: {exc}")
        return {"scanned": 0, "added": 0, "updated": 0}

    for entry in entries:
        if entry.name.startswith(".") or not entry.is_dir(follow_symlinks=False):
            continue
        video_path = _find_final_video(entry.path)
        if not video_path:
            # 没有成片的任务不进台账，否则列表会被失败任务淹没。
            continue

        scanned += 1
        payload = _load_task_script(entry.path)
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        script_text = payload.get("script") if isinstance(payload.get("script"), str) else ""
        subject = _text(
            params.get("video_subject") or script_text[:40] or entry.name,
            MAX_SUBJECT_LENGTH,
        )
        try:
            size = os.path.getsize(video_path)
            generated_at = datetime.fromtimestamp(
                os.path.getmtime(entry.path)
            ).isoformat(timespec="seconds")
        except OSError:
            size = 0
            generated_at = ""

        _ensure_schema()
        with _write_lock, _session() as connection:
            existing = connection.execute(
                "SELECT id FROM videos WHERE task_id = ?", (entry.name,)
            ).fetchone()
            if existing is None:
                now = _now()
                connection.execute(
                    """
                    INSERT INTO videos
                        (task_id, subject, script_excerpt, video_path, video_size,
                         generated_at, origin, platforms, remark, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, '[]', '', ?, ?)
                    """,
                    (
                        entry.name,
                        subject,
                        _text(script_text, MAX_SCRIPT_EXCERPT_LENGTH),
                        video_path,
                        size,
                        generated_at,
                        ORIGIN_AUTO,
                        now,
                        now,
                    ),
                )
                added += 1
            else:
                connection.execute(
                    """
                    UPDATE videos
                       SET subject = ?, script_excerpt = ?, video_path = ?,
                           video_size = ?, generated_at = ?, updated_at = ?
                     WHERE id = ?
                    """,
                    (
                        subject,
                        _text(script_text, MAX_SCRIPT_EXCERPT_LENGTH),
                        video_path,
                        size,
                        generated_at,
                        _now(),
                        int(existing["id"]),
                    ),
                )
                updated += 1

    if added or updated:
        logger.info(
            f"publish board synced from tasks: scanned={scanned}, "
            f"added={added}, updated={updated}"
        )
    return {"scanned": scanned, "added": added, "updated": updated}


def summary() -> Dict[str, int]:
    """台账概览，供界面显示统计数字。"""
    _ensure_schema()
    with _session() as connection:
        account_total = connection.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"]
        video_total = connection.execute("SELECT COUNT(*) AS c FROM videos").fetchone()["c"]
        binding_total = connection.execute("SELECT COUNT(*) AS c FROM bindings").fetchone()["c"]
    return {
        "accounts": int(account_total),
        "videos": int(video_total),
        "bindings": int(binding_total),
    }
