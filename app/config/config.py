import errno
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
    """dict 사용법은 그대로 두면서, 런타임 설정 쓰기 작업이 같은 락을 따르게 한다."""

    def __setitem__(self, key, value):
        # Streamlit 은 페이지를 통째로 rerun 할 때마다 현재 위젯 값을 설정에 다시 쓴다.
        # 영상 작업이 runtime_config_lock 을 쥐고 있을 때 값이 바뀌지 않았다면 이 쓰기는
        # 아무 부작용이 없으므로, 새로고침한 페이지가 폼 중간에서 멈춰서는 안 된다.
        # 실제로 설정을 바꾸는 쓰기는 여전히 아래 락으로 들어간다. 따라서 영상을 생성하는
        # 도중에 Provider, 키, 기타 전역 설정을 바꿀 수는 없다.
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
        # ``pop(key, default)`` 도 key 가 없으면 설정을 바꾸지 않는다. WebUI 는 이 표현으로
        # '기본 정책을 따른다' 는 뜻을 나타내므로, 새로고침 시 바로 끝나도록 허용해야 한다.
        if key not in self:
            if default is _MISSING:
                raise KeyError(key)
            return default
        with _config_save_lock:
            if default is _MISSING:
                return super().pop(key)
            return super().pop(key, default)

    def setdefault(self, key, default=None):
        # __setitem__ 과 마찬가지로, 이미 있는 key 에 대한 setdefault 는 읽기 전용 작업이다.
        # 먼저 반환하면 기본 설정만 읽는 페이지 새로고침이 장시간 작업의 설정 락에
        # 영향을 받지 않는다.
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
    전역 설정에 의존하는 작업 하나가 끝날 때까지 다른 WebUI 세션이 설정을 고치지 못하게 한다.

    현재 프로젝트는 기본적으로 로컬 루프백에 바인딩하며, 설정은 여전히 단일 사용자
    전역 설정이다. 이 가벼운 락은 주로 생성이나 미리듣기 같은 긴 작업을 보호해, 다른
    탭이 작업 도중 Provider 나 키를 바꾸는 것을 막는다.
    """
    with _config_save_lock:
        yield


@contextmanager
def try_runtime_config_lock():
    """
    런타임 설정 락을 시도해 보고 성공 여부를 즉시 반환한다.

    WebUI 미리듣기는 사용자가 직접 누르는 짧은 작업이므로, 백그라운드 영상 작업이 락을
    쥐고 있을 때 몇 분씩 기다려서는 안 된다. 호출자는 락을 얻지 못하면 사용자에게 잠시
    후 다시 시도하라고 바로 안내하면 된다. 락을 얻은 뒤에는 미리듣기 동안 Provider,
    키, 모델 설정이 다른 세션에 의해 바뀌지 않는 것이 보장된다.
    """
    acquired = _config_save_lock.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired:
            _config_save_lock.release()


def is_running_in_container(
    dockerenv_path: str = "/.dockerenv",
    containerenv_path: str = "/run/.containerenv",
    cgroup_path: str = "/proc/1/cgroup",
) -> bool:
    """
    현재 프로세스가 컨테이너 안에서 도는지 판정한다.

    이 판정은 주로 Ollama 기본 주소를 고르는 데 쓴다.
    - 일반적인 로컬 실행에서 `localhost` 는 사용자 머신 자신을 가리킨다.
    - Docker 컨테이너 안에서 `localhost` 는 컨테이너 자신을 가리키므로, 호스트의
      Ollama 에 접근하려면 보통 `host.docker.internal` 을 써야 한다.

    `/proc/1/cgroup` 이 있는지만 봐서는 안 된다. 일반 Linux 에도 이 파일이 있기 때문이다.
    여기서는 명확한 컨테이너 표식을 찾았을 때만 True 를 반환해, Docker 가 아닌 Linux
    사용자가 오판되는 것을 막는다. 인자를 주입 가능한 경로로 남겨 둔 것은 단위 테스트가
    여러 실행 환경을 덮을 수 있게 하기 위해서다.
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
    # /proc/net/route 의 Gateway 는 16 진수 리틀 엔디언이다. 예를 들어 010011AC 는
    # 172.17.0.1 을 뜻한다. 여기서 따로 해석하는 이유는, 네이티브 Linux Docker 에
    # host.docker.internal DNS 레코드가 없을 때도 컨테이너 기본 게이트웨이 상의 호스트에
    # 접근을 시도할 수 있게 하기 위해서다.
    if len(hex_gateway) != 8:
        raise ValueError("invalid gateway length")

    octets = [
        str(int(hex_gateway[index : index + 2], 16))
        for index in range(6, -1, -2)
    ]
    return ".".join(octets)


def get_container_default_gateway_ip(route_path: str = "/proc/net/route") -> str:
    """
    Linux 컨테이너의 기본 게이트웨이 IP 를 읽는다.

    Docker Desktop 은 보통 `host.docker.internal` 을 제공하지만, 네이티브 Linux Docker 는
    이 DNS 이름을 기본으로 주지 않을 수 있다. 기본 게이트웨이는 대체로 호스트 서비스에
    접근하는 대비책 주소로 쓸 수 있다. 사용자의 Ollama 가 127.0.0.1 만 수신하고 있다면,
    여전히 사용자가 Ollama 를 호스트 네트워크 인터페이스에서 수신하게 하거나
    `ollama_base_url` 을 직접 설정해야 한다.
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
    Ollama 의 기본 OpenAI 호환 base_url 을 반환한다.

    사용자가 `ollama_base_url` 을 명시적으로 설정했다면 여기로 오지 않는다. 여기서는
    '설정하지 않았을 때의 최선의 기본값' 만 다룬다. 컨테이너 안에서는 기본적으로 호스트를,
    일반적인 로컬 실행에서는 localhost 를 가리킨다.
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
    # fix: IsADirectoryError: [Errno 21] Is a directory: '/shipcast/config.toml'
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
    런타임 설정을 원자적으로 저장한다.

    Streamlit 의 서로 다른 세션이 비슷한 시각에 설정 저장을 유발할 수 있다. config.toml 을
    바로 덮어쓰면 다른 스레드가 일부만 쓰인 TOML 을 읽을 수 있다. 여기서는 프로세스 내
    재진입 락으로 저장을 직렬화하고, 같은 디렉터리의 임시 파일에 먼저 쓴 뒤 os.replace 로
    대상 파일을 원자적으로 교체한다.

    Docker Desktop 의 단일 파일 bind mount 는 config.toml 자체를 마운트 지점으로 만든다.
    Linux 커널은 rename/replace 로 마운트 지점을 교체하는 것을 허용하지 않으므로 EBUSY 가
    반환된다. 이 경우에는 락 안에서 파일을 제자리 덮어쓰는 수밖에 없다. 다른 예외는 그대로
    던져서 권한, 디스크, 경로 오류를 가리지 않는다.

    이렇게 해도 프로젝트의 기존 단일 사용자 전역 설정 의미는 그대로 유지되며, 복잡한
    다중 사용자 설정 체계를 새로 들이지도 않는다. 주로 여러 탭이나 빠른 rerun 때
    설정 파일이 손상되는 것을 막는 용도다.
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

        # WebUI 는 rerun 이 끝날 때 저장을 호출한다. 내용이 바뀌지 않았으면 바로 반환해,
        # 평범한 위젯을 누를 때마다 디스크 쓰기와 fsync 가 발생하지 않게 한다.
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
            try:
                os.replace(temp_path, config_file)
            except OSError as exc:
                if exc.errno != errno.EBUSY:
                    raise

                logger.warning(
                    "atomic config replacement is unavailable for the mounted "
                    f"file, fallback to in-place write: {config_file}"
                )
                with open(config_file, mode="w", encoding="utf-8") as f:
                    f.write(serialized_config)
                    f.flush()
                    os.fsync(f.fileno())
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
# 텔레그램 봇. 봇 토큰과 허용할 대화 상대를 담는다. WebUI 가 쓰지 않으므로
# save_config 의 갱신 대상에는 넣지 않는다 — 사용자가 파일에 직접 적는 값이다.
telegram = _SynchronizedConfig(_cfg.get("telegram", {}))
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
project_name = _cfg.get("project_name", "shipcast")
project_description = _cfg.get(
    "project_description",
    # API 문서 상단에 뜨는 링크. 지금 도는 서버가 무엇인지 가리켜야 한다.
    # 원본에 대한 출처 표기는 README 에 있다.
    "<a href='https://github.com/raidostar/MoneyPrinterTurbo'>"
    "https://github.com/raidostar/MoneyPrinterTurbo</a>",
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
