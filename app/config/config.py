import os
import shutil
import socket

import toml
from loguru import logger

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
config_file = f"{root_dir}/config.toml"
_CONTAINER_CGROUP_MARKERS = ("docker", "containerd", "kubepods", "libpod", "podman")
_DOCKER_HOST_GATEWAY_NAME = "host.docker.internal"


def is_running_in_container(
    dockerenv_path: str = "/.dockerenv",
    containerenv_path: str = "/run/.containerenv",
    cgroup_path: str = "/proc/1/cgroup",
) -> bool:
    """
    현재 프로세스가 컨테이너 내부에서 실행 중인지 판단합니다.

    이 판단은 주로 Ollama 기본 주소 선택에 사용됩니다.
    - 일반적인 로컬 실행 시 `localhost`는 사용자 머신 자신을 가리킵니다.
    - Docker 컨테이너 내부에서는 `localhost`가 컨테이너 자신을 가리키므로,
      호스트의 Ollama에 접근하려면 보통 `host.docker.internal`을 사용해야 합니다.

    `/proc/1/cgroup` 파일의 존재 여부만으로는 판단할 수 없습니다. 일반 Linux에도 이 파일이 있기 때문입니다.
    여기서는 명확한 컨테이너 표시가 감지된 경우에만 True를 반환하여, Docker가 아닌 Linux 사용자를 잘못 판단하지 않도록 합니다.
    파라미터는 주입 가능한 경로로 유지하여, 단위 테스트에서 다양한 실행 환경을 다룰 수 있게 합니다.
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
    # /proc/net/route 안의 Gateway는 16진수 리틀엔디언이며, 예를 들어 010011AC는
    # 172.17.0.1을 의미합니다. 여기서 별도로 파싱하는 이유는, 네이티브 Linux Docker에서
    # host.docker.internal DNS 레코드가 없을 때 컨테이너 기본 게이트웨이의 호스트에 접근을 시도하기 위함입니다.
    if len(hex_gateway) != 8:
        raise ValueError("invalid gateway length")

    octets = [
        str(int(hex_gateway[index : index + 2], 16))
        for index in range(6, -1, -2)
    ]
    return ".".join(octets)


def get_container_default_gateway_ip(route_path: str = "/proc/net/route") -> str:
    """
    Linux 컨테이너 안의 기본 게이트웨이 IP를 읽습니다.

    Docker Desktop은 보통 `host.docker.internal`을 제공하지만, 네이티브 Linux Docker는
    기본적으로 이 DNS 이름을 제공하지 않을 수 있습니다. 기본 게이트웨이는 보통 호스트 서비스에 접근하기 위한
    대체 주소로 사용할 수 있습니다. 다만 사용자의 Ollama가 127.0.0.1만 수신 중이라면,
    여전히 Ollama가 호스트 네트워크 인터페이스를 수신하도록 하거나 `ollama_base_url`을 수동으로 설정해야 합니다.
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
    Ollama의 기본 OpenAI-compatible base_url을 반환합니다.

    사용자가 `ollama_base_url`을 명시적으로 설정한 경우에는 이 경로를 거치지 않습니다. 여기서는
    "설정되지 않았을 때의 최적 기본값"만 처리합니다. 컨테이너 내부에서는 기본적으로 호스트를 가리키고,
    일반적인 로컬 실행에서는 기본적으로 localhost를 가리킵니다.
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
    with open(config_file, "w", encoding="utf-8") as f:
        _cfg["app"] = app
        _cfg["azure"] = azure
        _cfg["siliconflow"] = siliconflow
        _cfg["ui"] = ui
        f.write(toml.dumps(_cfg))


_cfg = load_config()
app = _cfg.get("app", {})
whisper = _cfg.get("whisper", {})
proxy = _cfg.get("proxy", {})
azure = _cfg.get("azure", {})
siliconflow = _cfg.get("siliconflow", {})
ui = _cfg.get(
    "ui",
    {
        "hide_log": False,
    },
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
project_version = _cfg.get("project_version", "1.2.8")
reload_debug = False

app["redis_host"] = os.getenv(
    "MPT_APP_REDIS_HOST",
    os.getenv("REDIS_HOST", app.get("redis_host", "localhost")),
)

imagemagick_path = app.get("imagemagick_path", "")
if imagemagick_path and os.path.isfile(imagemagick_path):
    os.environ["IMAGEMAGICK_BINARY"] = imagemagick_path

ffmpeg_path = app.get("ffmpeg_path", "")
if ffmpeg_path and os.path.isfile(ffmpeg_path):
    os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_path

logger.info(f"{project_name} v{project_version}")
