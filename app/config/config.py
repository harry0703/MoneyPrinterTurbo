import os
import shutil
import socket
import tempfile
import threading
from contextlib import contextmanager

import toml
from loguru import logger

from app import __version__

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
config_file = f"{root_dir}/config.toml"
_CONTAINER_CGROUP_MARKERS = ("docker", "containerd", "kubepods", "libpod", "podman")
_DOCKER_HOST_GATEWAY_NAME = "host.docker.internal"
_config_save_lock = threading.RLock()
_MISSING = object()


class _SynchronizedConfig(dict):
    """保持 dict 使用方式不变，同时让运行期配置写操作服从同一把锁。"""

    def __setitem__(self, key, value):
        # Streamlit 每次整页 rerun 都会把当前控件值重新写回配置。视频任务持有
        # runtime_config_lock 时，如果值没有变化，这次写入没有任何副作用，也
        # 不应让刷新后的页面卡在表单中途。真正改变配置的写入仍进入下方锁，
        # 因而不能在正在生成的视频中途切换 Provider、密钥或其它全局设置。
        current = super().get(key, _MISSING)
        if current is not _MISSING and current == value:
            return
        with _config_save_lock:
            super().__setitem__(key, value)

    def __delitem__(self, key):
        with _config_save_lock:
            super().__delitem__(key)

    def clear(self):
        if not self:
            return
        with _config_save_lock:
            super().clear()

    def pop(self, key, default=_MISSING):
        # ``pop(key, default)`` 在 key 不存在时同样不会改变配置。WebUI 使用
        # 这种写法表达“采用默认策略”，刷新时必须允许它直接完成。
        if key not in self:
            if default is _MISSING:
                raise KeyError(key)
            return default
        with _config_save_lock:
            if default is _MISSING:
                return super().pop(key)
            return super().pop(key, default)

    def setdefault(self, key, default=None):
        # 与 __setitem__ 相同，已存在 key 的 setdefault 是只读操作。提前返回
        # 可以让只读取默认配置的页面刷新不受长任务配置锁影响。
        current = super().get(key, _MISSING)
        if current is not _MISSING:
            return current
        with _config_save_lock:
            return super().setdefault(key, default)

    def update(self, *args, **kwargs):
        changes = dict(*args, **kwargs)
        if all(
            (current := dict.get(self, key, _MISSING)) is not _MISSING
            and current == value
            for key, value in changes.items()
        ):
            return
        with _config_save_lock:
            super().update(changes)


@contextmanager
def runtime_config_lock():
    """
    在一次依赖全局配置的完整操作期间阻止其它 WebUI 会话改写配置。

    当前项目默认绑定本地回环地址，配置仍然是单用户全局配置。这个轻量锁主要
    保护生成、试听等长操作，避免另一个标签页在操作中途切换 Provider 或密钥。
    """
    with _config_save_lock:
        yield


def is_running_in_container(
    dockerenv_path: str = "/.dockerenv",
    containerenv_path: str = "/run/.containerenv",
    cgroup_path: str = "/proc/1/cgroup",
) -> bool:
    """
    判断当前进程是否运行在容器内。

    这个判断主要用于 Ollama 默认地址选择：
    - 普通本机运行时，`localhost` 指向用户机器本身；
    - Docker 容器内，`localhost` 指向容器自己，访问宿主机 Ollama
      通常需要使用 `host.docker.internal`。

    不能只判断 `/proc/1/cgroup` 是否存在，因为普通 Linux 也会有这个文件。
    这里只在检测到明确的容器标记时返回 True，避免误伤非 Docker Linux 用户。
    参数保留为可注入路径，便于单元测试覆盖不同运行环境。
    """
    if os.path.isfile(dockerenv_path) or os.path.isfile(containerenv_path):
        return True

    try:
        with open(cgroup_path, mode="r", encoding="utf-8") as fp:
            cgroup_content = fp.read().lower()
    except OSError:
        return False

    return any(marker in cgroup_content for marker in _CONTAINER_CGROUP_MARKERS)


def _can_resolve_hostname(hostname: str) -> bool:
    try:
        socket.gethostbyname(hostname)
    except OSError:
        return False
    return True


def _decode_linux_route_gateway(hex_gateway: str) -> str:
    # /proc/net/route 里的 Gateway 是 16 进制小端序，例如 010011AC 表示
    # 172.17.0.1。这里单独解析，是为了在原生 Linux Docker 没有
    # host.docker.internal DNS 记录时，还能尝试访问容器默认网关上的宿主机。
    if len(hex_gateway) != 8:
        raise ValueError("invalid gateway length")

    octets = [
        str(int(hex_gateway[index : index + 2], 16))
        for index in range(6, -1, -2)
    ]
    return ".".join(octets)


def get_container_default_gateway_ip(route_path: str = "/proc/net/route") -> str:
    """
    读取 Linux 容器里的默认网关 IP。

    Docker Desktop 通常提供 `host.docker.internal`，但原生 Linux Docker
    默认不一定提供这个 DNS 名称。默认网关通常可以作为访问宿主机服务的
    兜底地址；如果用户的 Ollama 只监听 127.0.0.1，则仍需要用户让
    Ollama 监听宿主机网卡或手动配置 `ollama_base_url`。
    """
    try:
        with open(route_path, mode="r", encoding="utf-8") as fp:
            route_lines = fp.readlines()
    except OSError:
        return ""

    for line in route_lines[1:]:
        fields = line.strip().split()
        if len(fields) < 3:
            continue

        destination = fields[1]
        gateway = fields[2]
        if destination != "00000000" or gateway == "00000000":
            continue

        try:
            return _decode_linux_route_gateway(gateway)
        except ValueError:
            logger.warning(f"invalid container gateway route entry: {line.strip()}")
            return ""

    return ""


def get_default_ollama_base_url() -> str:
    """
    返回 Ollama 的默认 OpenAI-compatible base_url。

    用户显式配置 `ollama_base_url` 时不会走这里；这里只处理“未配置时的
    最佳默认值”。容器内默认指向宿主机，普通本机运行默认指向 localhost。
    """
    if not is_running_in_container():
        return "http://localhost:11434/v1"

    if _can_resolve_hostname(_DOCKER_HOST_GATEWAY_NAME):
        return f"http://{_DOCKER_HOST_GATEWAY_NAME}:11434/v1"

    gateway_ip = get_container_default_gateway_ip()
    if gateway_ip:
        logger.info(
            "host.docker.internal is not resolvable, fallback to container "
            f"default gateway for Ollama: {gateway_ip}"
        )
        return f"http://{gateway_ip}:11434/v1"

    logger.warning(
        "failed to resolve host.docker.internal and container default gateway; "
        "fallback to host.docker.internal for Ollama"
    )
    return f"http://{_DOCKER_HOST_GATEWAY_NAME}:11434/v1"


def load_config():
    # fix: IsADirectoryError: [Errno 21] Is a directory: '/MoneyPrinterTurbo/config.toml'
    if os.path.isdir(config_file):
        shutil.rmtree(config_file)

    if not os.path.isfile(config_file):
        example_file = f"{root_dir}/config.example.toml"
        if os.path.isfile(example_file):
            shutil.copyfile(example_file, config_file)
            logger.info("copy config.example.toml to config.toml")

    logger.info(f"load config from file: {config_file}")

    try:
        _config_ = toml.load(config_file)
    except Exception as e:
        logger.warning(f"load config failed: {str(e)}, try to load as utf-8-sig")
        with open(config_file, mode="r", encoding="utf-8-sig") as fp:
            _cfg_content = fp.read()
            _config_ = toml.loads(_cfg_content)
    return _config_


def save_config():
    """
    原子保存运行时配置。

    Streamlit 的不同会话可能在相近时间触发配置保存。直接覆盖 config.toml 时，
    另一个线程可能读取到只写了一部分的 TOML 内容。这里使用进程内可重入锁串行化
    保存，并先写入同目录临时文件，再通过 os.replace 原子替换目标文件。

    这仍然保留项目现有的单用户全局配置语义，不额外引入复杂的多用户配置系统；
    主要用于避免多标签页或快速 rerun 时损坏配置文件。
    """
    with _config_save_lock:
        config_to_save = dict(_cfg)
        config_to_save["app"] = dict(app)
        config_to_save["azure"] = dict(azure)
        config_to_save["siliconflow"] = dict(siliconflow)
        config_to_save["elevenlabs"] = dict(elevenlabs)
        config_to_save["chatterbox"] = dict(chatterbox)
        config_to_save["ui"] = dict(ui)
        serialized_config = toml.dumps(config_to_save)

        # WebUI 完整 rerun 结束时会调用保存。内容没有变化时直接返回，避免每次
        # 点击普通控件都产生一次磁盘写入和 fsync。
        try:
            with open(config_file, mode="r", encoding="utf-8") as f:
                if f.read() == serialized_config:
                    _cfg.clear()
                    _cfg.update(config_to_save)
                    return
        except (OSError, UnicodeError):
            pass

        temp_path = ""
        try:
            fd, temp_path = tempfile.mkstemp(
                prefix=".config-",
                suffix=".toml.tmp",
                dir=root_dir,
            )
            with os.fdopen(fd, mode="w", encoding="utf-8") as f:
                f.write(serialized_config)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, config_file)
            _cfg.clear()
            _cfg.update(config_to_save)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)


_cfg = load_config()
app = _SynchronizedConfig(_cfg.get("app", {}))
whisper = _cfg.get("whisper", {})
proxy = _cfg.get("proxy", {})
azure = _SynchronizedConfig(_cfg.get("azure", {}))
siliconflow = _SynchronizedConfig(_cfg.get("siliconflow", {}))
elevenlabs = _SynchronizedConfig(_cfg.get("elevenlabs", {}))
chatterbox = _SynchronizedConfig(_cfg.get("chatterbox", {}))
ui = _SynchronizedConfig(
    _cfg.get(
        "ui",
        {
            "hide_log": False,
        },
    )
)

hostname = socket.gethostname()

log_level = _cfg.get("log_level", "DEBUG")
listen_host = _cfg.get("listen_host", "0.0.0.0")
listen_port = _cfg.get("listen_port", 8080)
project_name = _cfg.get("project_name", "MoneyPrinterTurbo")
project_description = _cfg.get(
    "project_description",
    "<a href='https://github.com/harry0703/MoneyPrinterTurbo'>https://github.com/harry0703/MoneyPrinterTurbo</a>",
)
project_version = _cfg.get("project_version", __version__)
reload_debug = False

app["redis_host"] = os.getenv(
    "MPT_APP_REDIS_HOST",
    os.getenv("REDIS_HOST", app.get("redis_host", "localhost")),
)

ffmpeg_path = app.get("ffmpeg_path", "")
if ffmpeg_path and os.path.isfile(ffmpeg_path):
    os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_path

logger.info(f"{project_name} v{project_version}")
