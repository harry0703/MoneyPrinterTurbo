"""
Instagram Reels 直接发布服务。

与 ``upload_post`` 的区别：后者通过第三方付费中转服务发布，这里直接调用
Instagram 移动端私有接口，不产生额外订阅成本，但需要自己承担账号安全与
频率控制。

instagrapi 与 MoviePy 的 Pillow 版本要求互相冲突，无法共存于同一环境，
因此真正的接口调用放在 ``scripts/instagram_worker.py``，由 ``uv run``
在独立环境中执行。本模块只负责配置、频率限制、进程编排和错误归类，
不导入 instagrapi，因此在未安装该依赖的环境里也能正常导入和测试。
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass

from loguru import logger

from app.config import config
from app.utils import utils

_WORKER_RELATIVE_PATH = os.path.join("scripts", "instagram_worker.py")
_SESSION_FILENAME = "instagram_session_{slug}.json"
_HISTORY_FILENAME = "instagram_uploads_{slug}.json"
# 登录、素材上传和转码都在服务端进行，正常情况下几分钟内完成。
_WORKER_TIMEOUT_SECONDS = 900
_MAX_CAPTION_LENGTH = 2200


class InstagramError(RuntimeError):
    """Instagram 发布链路的领域异常。"""


class InstagramNotConfiguredError(InstagramError):
    """缺少启用开关或账号凭据。"""


class InstagramAuthError(InstagramError):
    """会话失效、登录被拒或触发验证挑战。"""


class InstagramRateLimitError(InstagramError):
    """达到本地频率上限，或被 Instagram 判定为频繁操作。"""


class InstagramAccountNotFoundError(InstagramError):
    """请求的账号标识在配置中不存在。"""


@dataclass(frozen=True)
class InstagramAccount:
    """单个发布账号。多账号必须各自独立，否则会被平台关联。"""

    label: str
    username: str
    password: str
    verification_code: str = ""
    proxy: str = ""

    @property
    def is_usable(self) -> bool:
        return bool(self.username and self.password)

    @property
    def slug(self) -> str:
        """用于会话与配额文件名，避免用户名里的字符影响路径。"""
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", self.username or self.label)
        return safe.lower() or "default"


@dataclass(frozen=True)
class InstagramSettings:
    enabled: bool
    accounts: tuple[InstagramAccount, ...]
    max_uploads_per_hour: int
    max_uploads_per_day: int

    @classmethod
    def from_config(cls) -> "InstagramSettings":
        section = getattr(config, "instagram", {}) or {}
        return cls(
            enabled=bool(section.get("enabled", False)),
            accounts=_parse_accounts(section),
            # Instagram 对连续发布非常敏感，默认值刻意低于社区观察到的阈值。
            # 该限制按账号独立计算，不在账号之间共享。
            max_uploads_per_hour=max(1, int(section.get("max_uploads_per_hour", 3))),
            max_uploads_per_day=max(1, int(section.get("max_uploads_per_day", 10))),
        )


def _account_from_mapping(values, fallback_label: str) -> InstagramAccount:
    username = str(values.get("username", "") or "").strip()
    return InstagramAccount(
        label=str(values.get("label", "") or "").strip() or (username or fallback_label),
        username=username,
        password=str(values.get("password", "") or ""),
        verification_code=str(values.get("verification_code", "") or "").strip(),
        proxy=str(values.get("proxy", "") or "").strip(),
    )


def _parse_accounts(section) -> tuple[InstagramAccount, ...]:
    """
    读取账号列表，同时兼容单账号写法。

    多账号使用 ``[[instagram.accounts]]``；仍然支持在 ``[instagram]`` 顶层直接
    写 username/password 的旧配置，避免已有安装升级后失效。
    """
    accounts = []
    raw_accounts = section.get("accounts") or []
    if isinstance(raw_accounts, list):
        for index, entry in enumerate(raw_accounts):
            if isinstance(entry, dict):
                account = _account_from_mapping(entry, f"account-{index + 1}")
                if account.is_usable:
                    accounts.append(account)

    if not accounts:
        single = _account_from_mapping(section, "default")
        if single.is_usable:
            accounts.append(single)

    return tuple(accounts)


def is_enabled() -> bool:
    settings = InstagramSettings.from_config()
    return settings.enabled and bool(settings.accounts)


def list_accounts() -> tuple[InstagramAccount, ...]:
    return InstagramSettings.from_config().accounts


def resolve_account(identifier: str = "", settings: InstagramSettings | None = None) -> InstagramAccount:
    """
    按标签或用户名选出目标账号。

    多账号配置下刻意要求显式指定：静默地发布到"第一个账号"是这类工具
    最容易造成的事故。
    """
    settings = settings or InstagramSettings.from_config()
    if not settings.accounts:
        raise InstagramNotConfiguredError("no Instagram account is configured")

    wanted = (identifier or "").strip().lower()
    if not wanted:
        if len(settings.accounts) > 1:
            labels = ", ".join(account.label for account in settings.accounts)
            raise InstagramAccountNotFoundError(
                f"several Instagram accounts are configured ({labels}); "
                "name the one to publish with"
            )
        return settings.accounts[0]

    for account in settings.accounts:
        if wanted in {account.label.lower(), account.username.lower()}:
            return account

    labels = ", ".join(account.label for account in settings.accounts)
    raise InstagramAccountNotFoundError(
        f"unknown Instagram account {identifier!r}; configured: {labels}"
    )


def session_file(account: InstagramAccount) -> str:
    """每个账号一份会话。共用会话会让平台把多个账号视为同一实体。"""
    return os.path.join(
        utils.storage_dir(create=True), _SESSION_FILENAME.format(slug=account.slug)
    )


def _history_file(account: InstagramAccount) -> str:
    return os.path.join(
        utils.storage_dir(create=True), _HISTORY_FILENAME.format(slug=account.slug)
    )


def _read_history(account: InstagramAccount) -> list[float]:
    try:
        with open(_history_file(account), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(payload, list):
        return []
    return [float(item) for item in payload if isinstance(item, (int, float))]


def _write_history(account: InstagramAccount, timestamps: list[float]) -> None:
    try:
        with open(_history_file(account), "w", encoding="utf-8") as handle:
            # 只保留一天以内的记录，避免文件无限增长。
            json.dump(sorted(timestamps)[-100:], handle)
    except OSError as exc:
        logger.warning(f"failed to persist Instagram upload history: {exc}")


def check_rate_limit(
    account: InstagramAccount,
    settings: InstagramSettings | None = None,
    now: float | None = None,
) -> None:
    """
    发布前的本地频率检查，按账号独立计算。

    Instagram 触发风控后的惩罚是账号级的，比单次发布失败严重得多。
    因此在请求发出之前先自我约束，而不是等服务端拒绝。
    """
    settings = settings or InstagramSettings.from_config()
    now = now if now is not None else time.time()
    history = _read_history(account)

    last_hour = [item for item in history if now - item < 3600]
    if len(last_hour) >= settings.max_uploads_per_hour:
        oldest = min(last_hour)
        wait_minutes = max(1, int((3600 - (now - oldest)) // 60))
        raise InstagramRateLimitError(
            f"hourly limit reached for {account.label} "
            f"({len(last_hour)}/{settings.max_uploads_per_hour}); "
            f"retry in about {wait_minutes} min"
        )

    last_day = [item for item in history if now - item < 86400]
    if len(last_day) >= settings.max_uploads_per_day:
        raise InstagramRateLimitError(
            f"daily limit reached for {account.label} "
            f"({len(last_day)}/{settings.max_uploads_per_day})"
        )


def _record_upload(account: InstagramAccount, now: float | None = None) -> None:
    history = _read_history(account)
    history.append(now if now is not None else time.time())
    _write_history(account, history)


def _worker_path() -> str:
    return os.path.join(utils.root_dir(), _WORKER_RELATIVE_PATH)


def _worker_command(worker: str) -> list[str]:
    """
    构造独立环境的执行命令。

    ``--no-project`` 让 uv 忽略当前项目的依赖树，仅按脚本内联声明解析，
    这正是绕开 Pillow 版本冲突的关键。
    """
    uv_binary = shutil.which("uv")
    if not uv_binary:
        raise InstagramError(
            "uv is required to run the Instagram worker in an isolated "
            "environment; install it from https://astral.sh/uv"
        )
    return [uv_binary, "run", "--no-project", "--quiet", "--python", "3.11", worker]


def _run_worker(request: dict) -> dict:
    worker = _worker_path()
    if not os.path.isfile(worker):
        raise InstagramError(f"Instagram worker script not found: {worker}")

    try:
        completed = subprocess.run(
            _worker_command(worker),
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=_WORKER_TIMEOUT_SECONDS,
            cwd=utils.root_dir(),
        )
    except subprocess.TimeoutExpired as exc:
        raise InstagramError(
            f"Instagram worker timed out after {_WORKER_TIMEOUT_SECONDS}s"
        ) from exc

    stderr = (completed.stderr or "").strip()
    if stderr:
        # 工作进程的诊断信息不含凭据，可以安全并入主日志。
        for line in stderr.splitlines():
            logger.debug(f"[instagram-worker] {line}")

    stdout = (completed.stdout or "").strip()
    if not stdout:
        raise InstagramError(
            f"Instagram worker produced no result (exit code {completed.returncode})"
        )

    # 结果固定是最后一行 JSON，避免依赖环境偶发输出干扰解析。
    last_line = stdout.splitlines()[-1]
    try:
        return json.loads(last_line)
    except json.JSONDecodeError as exc:
        raise InstagramError(f"unreadable Instagram worker result: {last_line}") from exc


def _raise_for_result(result: dict) -> None:
    error_type = result.get("error_type", "upload")
    message = result.get("error", "unknown Instagram error")
    if error_type in {"auth", "challenge", "app_version", "session_expired"}:
        raise InstagramAuthError(message)
    if error_type == "rate_limit":
        raise InstagramRateLimitError(message)
    if error_type == "config":
        raise InstagramNotConfiguredError(message)
    raise InstagramError(message)


def _build_request(account: InstagramAccount, **overrides) -> dict:
    request = {
        "username": account.username,
        "password": account.password,
        "verification_code": account.verification_code,
        "proxy": account.proxy,
        "session_file": session_file(account),
        # 略微拉长请求间隔，行为更接近真实客户端。
        "delay_range": [2, 5],
    }
    request.update(overrides)
    return request


def verify_session(account: str = "") -> dict:
    """
    验证凭据与会话是否可用，不发布任何内容。

    用于配置阶段确认账号可登录，避免等到真正发布时才发现问题；多账号时
    也用来分别建立每个账号的会话文件。
    """
    settings = InstagramSettings.from_config()
    if not settings.enabled:
        raise InstagramNotConfiguredError("Instagram publishing is disabled")

    target = resolve_account(account, settings)
    result = _run_worker(_build_request(target, action="check"))
    if not result.get("ok"):
        _raise_for_result(result)
    result["account"] = target.label
    return result


# 允许读数据的账号。
#
# 上一版对四个账号一起读，其中三个的会话在那次调用之后随即失效。证据无法
# 分辨是这些接口造成的，还是它们本来就快不行了。因此先只对这个一次性测试
# 账号开放，观察几天；它扛得住再逐个加进来。名单为空表示不限制。
STATS_ACCOUNTS = ("brainrot",)


class InstagramStatsNotAllowedError(InstagramError):
    """账号不在读数据的名单里时抛出。"""


def stats_accounts() -> tuple[str, ...]:
    """返回当前允许读数据的账号，顺序与配置一致。"""
    allowed = set(STATS_ACCOUNTS)
    if not allowed:
        return tuple(account.label for account in list_accounts())
    return tuple(
        account.label for account in list_accounts() if account.label in allowed
    )


def fetch_stats(account: str = "", amount: int = 12) -> dict:
    """
    读取一个账号的关注数与最近若干条 Reels 的计数。

    存在的理由是让使用者不必登录 Instagram 就能看数据：每次在浏览器里登录，
    平台都会看到一台"新设备"，而触发一次安全验证就可能连带作废正在用的会话。
    """
    settings = InstagramSettings.from_config()
    if not settings.enabled:
        raise InstagramNotConfiguredError("Instagram publishing is disabled")

    target = resolve_account(account, settings)
    if STATS_ACCOUNTS and target.label not in STATS_ACCOUNTS:
        raise InstagramStatsNotAllowedError(
            f"reading stats is not enabled for {target.label}; "
            f"currently allowed: {', '.join(STATS_ACCOUNTS)}"
        )

    result = _run_worker(_build_request(target, action="stats", amount=amount))
    if not result.get("ok"):
        _raise_for_result(result)
    result["account"] = target.label
    return result


def import_session(sessionid: str, account: str = "") -> dict:
    """
    用浏览器会话建立客户端会话，绕开账密登录。

    私有 API 的账密登录会校验客户端版本号；instagrapi 内置的那串一旦被判过期
    就无法登录，而它必须与真实应用一致，本地改不出来。浏览器里已经登录好的
    会话不经过这道校验。成功后写入会话文件，之后的发布照常复用，不必再提供。
    """
    sessionid = (sessionid or "").strip()
    if not sessionid:
        raise InstagramNotConfiguredError("a session id is required")

    settings = InstagramSettings.from_config()
    target = resolve_account(account, settings)
    result = _run_worker(
        _build_request(target, action="check", sessionid=sessionid)
    )
    if not result.get("ok"):
        _raise_for_result(result)
    result["account"] = target.label
    return result


def _extract_thumbnail(video_path: str, at_seconds: float = 0.0) -> str:
    """
    抽一帧作为封面，返回临时 JPEG 路径；失败时返回空字符串。

    instagrapi 自己抽帧要靠 MoviePy，而工作进程刻意不装它——两者对 Pillow 的
    版本要求互相冲突，隔离正是为此。主进程本来就有 ffmpeg，由它抽帧再把文件
    交过去，既绕开冲突，也让封面变成我们能决定的东西而不是碰运气。

    取第 0 帧：brainrot 的成片把封面画在了那里，普通成片的首帧也够用。
    """
    handle, thumbnail_path = tempfile.mkstemp(prefix="ig-cover-", suffix=".jpg")
    os.close(handle)

    try:
        subprocess.run(
            [
                utils.get_ffmpeg_binary(),
                "-y", "-hide_banner", "-loglevel", "error",
                "-ss", str(max(0.0, at_seconds)),
                "-i", video_path,
                "-frames:v", "1",
                "-q:v", "2",
                thumbnail_path,
            ],
            capture_output=True, timeout=120, check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning(f"could not extract a cover frame: {exc}")
        _remove_quietly(thumbnail_path)
        return ""

    if os.path.getsize(thumbnail_path) == 0:
        _remove_quietly(thumbnail_path)
        return ""
    return thumbnail_path


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def publish_reel(
    video_path: str,
    caption: str = "",
    music_query: str = "",
    video_duration_ms: int = 0,
    account: str = "",
) -> dict:
    """
    发布一条 Reel，返回包含作品链接的结果字典。

    调用方只需处理 ``InstagramError`` 及其子类；底层的会话复用、重试和
    "上传成功但响应解析失败"的确认都在工作进程内完成。
    """
    settings = InstagramSettings.from_config()
    if not settings.enabled:
        raise InstagramNotConfiguredError("Instagram publishing is disabled")

    target = resolve_account(account, settings)

    if not os.path.isfile(video_path):
        raise InstagramError(f"video file not found: {video_path}")

    check_rate_limit(target, settings)

    thumbnail_path = _extract_thumbnail(video_path)
    request = _build_request(
        target,
        action="publish",
        video_path=os.path.abspath(video_path),
        caption=(caption or "")[:_MAX_CAPTION_LENGTH],
        music_query=music_query or "",
        video_duration_ms=int(video_duration_ms or 0),
        thumbnail=thumbnail_path,
    )

    logger.info(
        f"publishing Instagram reel as {target.label}: {os.path.basename(video_path)}"
    )
    try:
        result = _run_worker(request)
    finally:
        if thumbnail_path:
            _remove_quietly(thumbnail_path)

    if not result.get("ok"):
        _raise_for_result(result)

    # 只有确认发布成功才计入频率窗口，失败重试不应消耗配额。
    _record_upload(target)
    result["account"] = target.label
    logger.success(f"Instagram reel published: {result.get('url')}")
    return result
