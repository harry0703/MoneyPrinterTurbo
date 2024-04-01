import os
import socket
import tomli
from loguru import logger

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
config_file = f"{root_dir}/config.toml"
if not os.path.isfile(config_file):
    example_file = f"{root_dir}/config.example.toml"
    if os.path.isfile(example_file):
        import shutil

        shutil.copyfile(example_file, config_file)
        logger.info(f"copy config.example.toml to config.toml")

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
project_description = _cfg.get("project_description",
                               "<a href='https://github.com/harry0703/MoneyPrinterTurbo'>https://github.com/harry0703/MoneyPrinterTurbo</a>")
project_version = _cfg.get("project_version", "1.0.1")
reload_debug = False

imagemagick_path = app.get("imagemagick_path", "")
if imagemagick_path and os.path.isfile(imagemagick_path):
    os.environ["IMAGEMAGICK_BINARY"] = imagemagick_path

ffmpeg_path = app.get("ffmpeg_path", "")
if ffmpeg_path and os.path.isfile(ffmpeg_path):
    os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_path

# __cfg = {
#     "hostname": hostname,
#     "listen_host": listen_host,
#     "listen_port": listen_port,
# }
# logger.info(__cfg)
