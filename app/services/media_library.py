"""本地素材库：给 ``storage/local_videos`` 下的上传素材建索引，让它们可识别、可复用。

上传链路（``material_upload.save_material_upload``）为了安全只把文件存成
``<uuid4 十六进制><扩展名>``，**原始文件名只写进日志**。结果是素材目录里堆着一批
无法辨认的文件，用户下次想复用同一批图/片只能重新上传一遍。

本模块是纯数据层，刻意不依赖 Streamlit，只负责三件事：

1. 用 SQLite 记录每个素材的原始文件名、类型、体积、尺寸/时长和备注；
2. 从素材目录扫描回填历史文件，保证「先有文件、后有库」的场景也能补齐；
3. 提供「这个素材被哪些任务用过」的查询，删除前能提示引用关系。

数据库文件位于 ``storage/media_library.db``，与任务产物同目录，随 Docker 挂载卷
一起持久化。同步只新增、只回填空字段，绝不覆盖用户改过的原始名和备注——与发布
台账的 ``sync_from_tasks`` 保持同一套语义。
"""

import base64
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

from loguru import logger
from PIL import Image, UnidentifiedImageError

from app.services import material_upload
from app.utils import utils

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

KIND_IMAGE = "image"
KIND_VIDEO = "video"

# 顺序即界面展示顺序。与发布台账、选题工坊一样，预设自带双语文案，避免把领域
# 数据散落到 i18n 文件里。
KINDS: tuple[Dict[str, str], ...] = (
    {"id": KIND_IMAGE, "label": "图片", "label_en": "Image"},
    {"id": KIND_VIDEO, "label": "视频", "label_en": "Video"},
)

KIND_IDS: tuple[str, ...] = tuple(item["id"] for item in KINDS)

MAX_ORIGINAL_NAME_LENGTH = 255
MAX_REMARK_LENGTH = 500

# 引用扫描只需要判断「文件名是否出现在任务参数里」，因此按任务数量设上限，
# 避免素材库很大时每次删除都要读完全部历史任务。
REFERENCE_SCAN_LIMIT = 300

# 只接受上传链路自己生成的 ``<32 位十六进制><扩展名>``。这条白名单同时挡掉了
# 路径分隔符、``..`` 以及任何指向素材目录之外的名字。
_STORED_NAME_PATTERN = re.compile(r"^[0-9a-f]{32}\.[a-z0-9]{1,8}$")
_FFPROBE_TIMEOUT_SECONDS = 20

# 预览缩略图的最大边长与 JPEG 质量。原图动辄几百 KB，直接内联会让页面体积上到
# 十几 MB，缩略图能把它压到几十 KB。
THUMBNAIL_MAX_SIDE = 480
THUMBNAIL_QUALITY = 78
# 列表里的缩略图只占一个单元格（几十像素），用 480 那一档会把表格载荷推到 MB 级：
# 实测每张 480 档约 28 KB，60 行就是 1.6 MB。列表单独走小尺寸，约 3 KB 一张。
LIST_THUMBNAIL_MAX_SIDE = 128
_POSTER_TIMEOUT_SECONDS = 30

_SCHEMA = """
CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stored_name TEXT NOT NULL UNIQUE,
    original_name TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'image',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    width INTEGER,
    height INTEGER,
    duration REAL,
    remark TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_materials_kind ON materials (kind);
CREATE INDEX IF NOT EXISTS idx_materials_stored_name ON materials (stored_name);
"""

# SQLite 连接不跨线程共享；只用一把进程内锁把「读改写」串起来，配合 WAL 足以
# 覆盖 WebUI 单机多会话的并发强度。
_write_lock = threading.RLock()
_schema_ready = False
_schema_lock = threading.Lock()


# ---------------------------------------------------------------------------
# 连接与基础工具
# ---------------------------------------------------------------------------


def db_path() -> str:
    """素材库数据库路径。放在 storage 下，与任务产物一起被挂载卷持久化。"""
    return os.path.join(utils.storage_dir(), "media_library.db")


def material_dir(create: bool = False) -> str:
    """本地素材目录，与上传链路使用同一个位置。"""
    return material_upload.uploaded_material_dir(create=create)


def _connect() -> sqlite3.Connection:
    path = db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path, timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def _session() -> Iterator[sqlite3.Connection]:
    """打开一次短连接，退出时提交并关闭。

    ``sqlite3`` 连接直接当上下文管理器只会提交/回滚、不会关闭，长期运行的
    Streamlit 进程会因此不断累积文件句柄。这里显式关闭，并在异常时回滚。
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


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _text(value: Any, limit: int) -> str:
    return str(value if value is not None else "").strip()[:limit]


def _as_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def kind_for_name(filename: str) -> str:
    """按扩展名判断素材类型。未知扩展名按图片处理，避免整条记录不可用。"""
    if os.path.splitext(filename)[1].lower() in material_upload.SUPPORTED_VIDEO_EXTENSIONS:
        return KIND_VIDEO
    return KIND_IMAGE


def kind_label(kind: str, language: str = "zh") -> str:
    for item in KINDS:
        if item["id"] == kind:
            return item["label_en"] if str(language).startswith("en") else item["label"]
    return kind


def validate_stored_name(stored_name: str) -> str:
    """校验素材文件名，返回规范化结果；非法时抛 ``ValueError``。"""
    name = os.path.basename(str(stored_name or "").strip())
    if not _STORED_NAME_PATTERN.match(name):
        raise ValueError(f"invalid material stored name: {stored_name!r}")
    return name


def material_path(stored_name: str) -> str:
    """素材的绝对路径。路径被约束在素材目录内，不会越界。"""
    name = validate_stored_name(stored_name)
    directory = os.path.realpath(material_dir(create=False))
    candidate = os.path.realpath(os.path.join(directory, name))
    if os.path.dirname(candidate) != directory:
        raise ValueError(f"material path escapes storage directory: {stored_name!r}")
    return candidate


# ---------------------------------------------------------------------------
# 元数据探测（尽力而为，失败不影响入库）
# ---------------------------------------------------------------------------


def _ffprobe_binary() -> str:
    """定位 ffprobe。优先 PATH，其次取 ffmpeg 同目录，最后退回裸名字。"""
    found = shutil.which("ffprobe")
    if found:
        return found
    ffmpeg = utils.get_ffmpeg_binary()
    if ffmpeg and os.path.isabs(ffmpeg):
        suffix = ".exe" if os.name == "nt" else ""
        sibling = os.path.join(os.path.dirname(ffmpeg), f"ffprobe{suffix}")
        if os.path.isfile(sibling):
            return sibling
    return "ffprobe"


def _probe_image(path: str) -> Dict[str, Any]:
    with Image.open(path) as image:
        return {"width": int(image.width), "height": int(image.height), "duration": None}


def _probe_video(path: str) -> Dict[str, Any]:
    # ffprobe 没有 ffmpeg 的 ``-nostdin``（会报 "Option not found" 并直接退出），
    # 因此改用 stdin=DEVNULL 保证它不会去读标准输入。
    completed = subprocess.run(
        [
            _ffprobe_binary(),
            "-v",
            "error",
            # 上传素材是本地自包含文件，不需要任何网络协议。
            "-protocol_whitelist",
            "file,pipe",
            "-select_streams",
            "v:0",
            # 同一条 -show_entries 里用 ":" 分隔多个 section：重复给同一个选项
            # 会让后者覆盖前者，流信息会整段丢失。
            "-show_entries",
            "stream=width,height:format=duration",
            "-of",
            "json",
            path,
        ],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=_FFPROBE_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("ffprobe failed")
    payload = json.loads(completed.stdout.decode("utf-8", errors="replace") or "{}")
    streams = payload.get("streams") or []
    stream = streams[0] if isinstance(streams, list) and streams else {}
    duration_raw = (payload.get("format") or {}).get("duration")
    duration: Optional[float] = None
    try:
        if duration_raw not in (None, ""):
            duration = round(float(duration_raw), 3)
    except (TypeError, ValueError):
        duration = None
    return {
        "width": int(stream["width"]) if stream.get("width") else None,
        "height": int(stream["height"]) if stream.get("height") else None,
        "duration": duration,
    }


def probe_metadata(path: str, kind: str) -> Dict[str, Any]:
    """读取宽高/时长。素材可能是用户随手丢进来的损坏文件，因此失败一律降级。"""
    empty = {"width": None, "height": None, "duration": None}
    if not path or not os.path.isfile(path):
        return empty
    try:
        if kind == KIND_VIDEO:
            return _probe_video(path)
        return _probe_image(path)
    except (
        OSError,
        ValueError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ) as exc:
        logger.warning(f"failed to probe material metadata: path={path}, error={exc}")
        return empty


# ---------------------------------------------------------------------------
# 预览缩略图
# ---------------------------------------------------------------------------


def _to_data_uri(payload: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(payload).decode("ascii")


def _image_preview(path: str, max_side: int) -> str:
    with Image.open(path) as image:
        # thumbnail() 就地缩放，必须先把像素读进来，否则退出 with 后数据不可用。
        image.load()
        image = image.convert("RGB")
        image.thumbnail((max_side, max_side))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=THUMBNAIL_QUALITY, optimize=True)
    return _to_data_uri(buffer.getvalue())


def _video_poster(path: str, max_side: int) -> str:
    """用 ffmpeg 抽一帧当封面。ffmpeg 缺失或抽帧失败时抛错，由调用方降级。"""
    binary = utils.get_ffmpeg_binary() or "ffmpeg"
    with tempfile.TemporaryDirectory(prefix="mpt_poster_") as directory:
        target = os.path.join(directory, "poster.jpg")
        completed = subprocess.run(
            [
                binary,
                "-v",
                "error",
                # 与 ffprobe 不同，ffmpeg 支持 -nostdin，顺手挡掉它读标准输入。
                "-nostdin",
                # 取第 0.5 秒：第 0 帧常常是黑场或片头占位。
                "-ss",
                "0.5",
                "-i",
                path,
                "-frames:v",
                "1",
                "-vf",
                f"scale={max_side}:-2",
                "-y",
                target,
            ],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=_POSTER_TIMEOUT_SECONDS,
            check=False,
        )
        if completed.returncode != 0 or not os.path.isfile(target):
            raise RuntimeError("ffmpeg poster extraction failed")
        with open(target, "rb") as handle:
            payload = handle.read()
    return _to_data_uri(payload)


def preview_data_uri(
    path: str, kind: str = "", max_side: int = THUMBNAIL_MAX_SIDE
) -> str:
    """生成预览用的 data URI，失败返回空串。

    这里刻意不用 ``st.image`` / ``st.video`` 直接吃本地路径：Streamlit 1.59.1 与
    Starlette 1.8.0 的 gzip 中间件不兼容 —— 对 image/*、video/*、audio/* 这些被
    排除压缩的响应，中间件只记录了响应头，却没有把 ``http.response.start`` 发出去，
    紧接着直接发 body，服务端抛
    ``Expected ASGI message 'http.response.start', but got 'http.response.body'``，
    于是 ``/media/`` 端点对这类内容一律返回 500，页面只会得到裂图。

    改成内联 base64 缩略图后，``st.image`` 对 ``data:`` 开头的字符串直接透传，
    完全绕开该端点；顺带把每屏几百 KB 的原图压到几 KB。

    ``max_side`` 控制最长边：详情弹窗用默认的大图，列表单元格用
    ``LIST_THUMBNAIL_MAX_SIDE``，避免表格载荷被缩略图撑大。
    """
    if not path or not os.path.isfile(path):
        return ""
    resolved_kind = kind or kind_for_name(path)
    try:
        if resolved_kind == KIND_VIDEO:
            return _video_poster(path, max_side)
        return _image_preview(path, max_side)
    except (
        OSError,
        ValueError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ) as exc:
        logger.warning(f"failed to build material preview: path={path}, error={exc}")
        return ""


# ---------------------------------------------------------------------------
# 入库与同步
# ---------------------------------------------------------------------------


def _is_empty(value: Any) -> bool:
    """把 ``None`` / 空串 / 0 统一视为「没有值」。

    尺寸、时长、体积在库里的「未知」都落成 ``None`` 或 0，回填时按同一个标准判断，
    避免为 0 的旧值把新探测到的真实值挡住。
    """
    return value is None or value == "" or value == 0


def _backfill(
    connection: sqlite3.Connection, existing: Dict[str, Any], row: Dict[str, Any]
) -> bool:
    """只补齐空字段，返回是否发生了修改。

    用户手改过的 ``original_name`` / ``remark`` 属于人工数据，任何同步都不能覆盖。
    """
    updates = {}
    for field in ("original_name", "width", "height", "duration", "size_bytes"):
        incoming = row.get(field)
        if _is_empty(incoming):
            continue
        if _is_empty(existing.get(field)):
            updates[field] = incoming
    if not updates:
        return False
    updates["updated_at"] = _now()
    assignments = ", ".join(f"{field} = ?" for field in updates)
    connection.execute(
        f"UPDATE materials SET {assignments} WHERE stored_name = ?",
        (*updates.values(), row["stored_name"]),
    )
    return True


def register_material(
    stored_name: str,
    original_name: str = "",
    kind: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """登记一个素材。已存在时只回填空字段，不覆盖人工数据。

    ``metadata`` 允许调用方复用刚上传时已经探测过的结果，避免重复调用 ffprobe。
    """
    _ensure_schema()
    name = validate_stored_name(stored_name)
    path = material_path(name)
    resolved_kind = kind if kind in KIND_IDS else kind_for_name(name)
    size_bytes = 0
    try:
        size_bytes = os.path.getsize(path)
    except OSError:
        size_bytes = 0
    probed = dict(metadata or {})
    if metadata is None:
        probed = probe_metadata(path, resolved_kind)
    row = {
        "stored_name": name,
        "original_name": _text(original_name, MAX_ORIGINAL_NAME_LENGTH),
        "kind": resolved_kind,
        "size_bytes": int(size_bytes),
        "width": probed.get("width"),
        "height": probed.get("height"),
        "duration": probed.get("duration"),
    }
    now = _now()
    with _write_lock, _session() as connection:
        existing = connection.execute(
            "SELECT * FROM materials WHERE stored_name = ?", (name,)
        ).fetchone()
        if existing is not None:
            _backfill(connection, _as_dict(existing), row)
        else:
            connection.execute(
                """
                INSERT INTO materials (
                    stored_name, original_name, kind, size_bytes,
                    width, height, duration, remark, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?)
                """,
                (
                    row["stored_name"],
                    row["original_name"],
                    row["kind"],
                    row["size_bytes"],
                    row["width"],
                    row["height"],
                    row["duration"],
                    now,
                    now,
                ),
            )
    return get_material_by_name(name)


def sync_from_directory() -> Dict[str, int]:
    """把素材目录里尚未登记的本地文件补进库。

    上传接口与 WebUI 都可能先落文件、后登记（历史文件、手工拷进来的文件），
    因此每次进入素材库页面都做一次只新增的同步，让列表跟得上磁盘现状。
    """
    _ensure_schema()
    directory = material_dir(create=False)
    stats = {"scanned": 0, "added": 0, "updated": 0, "missing": 0}
    if not os.path.isdir(directory):
        return stats

    try:
        # 扫描句柄用完即关，只留下文件名，后续处理不再依赖打开着的目录迭代器。
        with os.scandir(directory) as iterator:
            names = []
            for entry in iterator:
                if not _STORED_NAME_PATTERN.match(entry.name):
                    # 上传中途的临时文件、.DS_Store 等一律不入库。
                    continue
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                names.append(entry.name)
    except OSError as exc:
        logger.warning(f"failed to scan material directory: {directory}, {exc}")
        return stats

    for name in sorted(names):
        stats["scanned"] += 1
        before = get_material_by_name(name)
        register_material(name)
        after = get_material_by_name(name)
        if before is None and after is not None:
            stats["added"] += 1
        elif before is not None and after != before:
            stats["updated"] += 1

    stats["missing"] = sum(1 for item in list_materials() if not item["exists"])
    return stats


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------


def _decorate(row: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(row)
    item["path"] = material_path(item["stored_name"])
    item["exists"] = os.path.isfile(item["path"])
    item["display_name"] = item["original_name"] or f"未命名素材 · {item['stored_name'][:8]}"
    return item


def get_material(material_id: int) -> Optional[Dict[str, Any]]:
    _ensure_schema()
    with _session() as connection:
        row = connection.execute(
            "SELECT * FROM materials WHERE id = ?", (int(material_id),)
        ).fetchone()
    return _decorate(_as_dict(row)) if row is not None else None


def get_material_by_name(stored_name: str) -> Optional[Dict[str, Any]]:
    _ensure_schema()
    name = validate_stored_name(stored_name)
    with _session() as connection:
        row = connection.execute(
            "SELECT * FROM materials WHERE stored_name = ?", (name,)
        ).fetchone()
    return _decorate(_as_dict(row)) if row is not None else None


def list_materials(keyword: str = "", kind: str = "") -> List[Dict[str, Any]]:
    """按关键字与类型筛选素材。关键字同时匹配原始文件名和备注。"""
    _ensure_schema()
    conditions = []
    params: List[Any] = []
    if kind in KIND_IDS:
        conditions.append("kind = ?")
        params.append(kind)
    text = str(keyword or "").strip()
    if text:
        conditions.append("(original_name LIKE ? OR remark LIKE ? OR stored_name LIKE ?)")
        pattern = f"%{text}%"
        params.extend([pattern, pattern, pattern])
    clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with _session() as connection:
        rows = connection.execute(
            f"SELECT * FROM materials {clause} ORDER BY created_at DESC, id DESC",
            tuple(params),
        ).fetchall()
    return [_decorate(_as_dict(row)) for row in rows]


def update_material(material_id: int, **fields: Any) -> Optional[Dict[str, Any]]:
    """更新人工字段（原始名、备注）。未知字段直接忽略。"""
    _ensure_schema()
    allowed = {"original_name": MAX_ORIGINAL_NAME_LENGTH, "remark": MAX_REMARK_LENGTH}
    updates: Dict[str, Any] = {}
    for field, limit in allowed.items():
        if field in fields:
            updates[field] = _text(fields[field], limit)
    if not updates:
        return get_material(material_id)
    updates["updated_at"] = _now()
    assignments = ", ".join(f"{field} = ?" for field in updates)
    with _write_lock, _session() as connection:
        connection.execute(
            f"UPDATE materials SET {assignments} WHERE id = ?",
            (*updates.values(), int(material_id)),
        )
    return get_material(material_id)


def count_references(stored_name: str) -> List[Dict[str, str]]:
    """返回引用了该素材的任务（task_id + 主题），供删除前提示。

    任务参数里的素材引用存的是绝对路径，因此只要文件名出现在 ``script.json``
    文本里就算命中；这里不做精确反序列化，避免为了提示而依赖参数模型的内部结构。
    """
    name = validate_stored_name(stored_name)
    tasks_root = utils.task_dir()
    if not os.path.isdir(tasks_root):
        return []
    try:
        with os.scandir(tasks_root) as entries:
            task_entries = sorted(
                (entry for entry in entries if entry.is_dir(follow_symlinks=False)),
                key=lambda entry: entry.name,
                reverse=True,
            )[:REFERENCE_SCAN_LIMIT]
    except OSError as exc:
        logger.warning(f"failed to scan task directory for references: {exc}")
        return []

    references: List[Dict[str, str]] = []
    for entry in task_entries:
        script_file = os.path.join(entry.path, "script.json")
        try:
            with open(script_file, "r", encoding="utf-8") as handle:
                raw = handle.read()
        except OSError:
            continue
        if name not in raw:
            continue
        subject = ""
        try:
            payload = json.loads(raw)
            params = payload.get("params") if isinstance(payload, dict) else {}
            if isinstance(params, dict):
                subject = str(params.get("video_subject") or "")
            if not subject and isinstance(payload, dict):
                subject = str(payload.get("script") or "")[:40]
        except (ValueError, TypeError):
            subject = ""
        references.append({"task_id": entry.name, "subject": subject})
    return references


def delete_material(material_id: int, remove_file: bool = True) -> bool:
    """删除素材记录；``remove_file`` 为真时同时删除磁盘文件。"""
    _ensure_schema()
    material = get_material(material_id)
    if material is None:
        return False
    if remove_file and material["exists"]:
        directory = os.path.realpath(material_dir(create=False))
        path = os.path.realpath(material["path"])
        # 双保险：即使 stored_name 校验被绕过，也不允许删到素材目录之外。
        if os.path.dirname(path) == directory:
            try:
                os.remove(path)
            except OSError as exc:
                logger.warning(f"failed to remove material file: path={path}, error={exc}")
                raise
        else:
            raise ValueError(f"refusing to remove file outside material dir: {path}")
    with _write_lock, _session() as connection:
        connection.execute("DELETE FROM materials WHERE id = ?", (int(material_id),))
    logger.info(f"material deleted: id={material_id}, remove_file={remove_file}")
    return True


def summary() -> Dict[str, Any]:
    """素材库概览：总数、图片数、视频数、总占用字节。"""
    _ensure_schema()
    with _session() as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS materials,
                COALESCE(SUM(kind = ?), 0) AS images,
                COALESCE(SUM(kind = ?), 0) AS videos,
                COALESCE(SUM(size_bytes), 0) AS bytes
            FROM materials
            """,
            (KIND_IMAGE, KIND_VIDEO),
        ).fetchone()
    payload = _as_dict(row)
    return {
        "materials": int(payload["materials"] or 0),
        "images": int(payload["images"] or 0),
        "videos": int(payload["videos"] or 0),
        "bytes": int(payload["bytes"] or 0),
    }


def format_size(size_bytes: int) -> str:
    """人类可读的体积，供界面直接展示。"""
    value = float(size_bytes or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def format_duration(seconds: Optional[float]) -> str:
    """把秒数格式化成 ``mm:ss`` / ``h:mm:ss``；未知时返回空串。"""
    if not seconds or seconds <= 0:
        return ""
    total = int(round(float(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
