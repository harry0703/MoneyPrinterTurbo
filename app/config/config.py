import os
import socket
import tomli
from loguru import logger

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
config_file = f"{root_dir}/config.toml"
logger.info(f"load config from file: {config_file}")

with open(config_file, mode="rb") as fp:
    _cfg = tomli.load(fp)

app = _cfg.get("app", {})
whisper = _cfg.get("whisper", {})
pexels = _cfg.get("pexels", {})

hostname = socket.gethostname()

log_level = _cfg.get("log_level", "DEBUG")
listen_host = _cfg.get("listen_host", "0.0.0.0")
listen_port = _cfg.get("listen_port", 8080)
project_name = _cfg.get("project_name", "MoneyPrinterTurbo")
project_description = _cfg.get("project_description", "MoneyPrinterTurbo\n by 抖音-网旭哈瑞.AI")
project_version = _cfg.get("project_version", "1.0.0")
reload_debug = False

imagemagick_path = app.get("imagemagick_path", "")
if imagemagick_path and os.path.isfile(imagemagick_path):
    os.environ["IMAGEMAGICK_BINARY"] = imagemagick_path

__cfg = {
    "hostname": hostname,
    "listen_host": listen_host,
    "listen_port": listen_port,
}
logger.info(__cfg)
