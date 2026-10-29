"""pip 安装后的 mpt 启动入口，复用现有 WebUI 和 CLI。"""

import argparse
import socket
import subprocess
import sys
from pathlib import Path

from app import __version__, paths


def _port_number(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _available_port(host: str) -> int:
    # 与源码启动脚本保持一致：默认端口被占用时继续寻找，显式指定的端口则
    # 交给 Streamlit 原样绑定和报错，避免把用户带到另一个服务上。
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    for port in range(8501, 8600):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as probe:
                probe.bind((host, port))
            return port
        except OSError:
            continue
    raise OSError(f"no available WebUI port on {host} between 8501 and 8599")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # CLI 自己负责完整参数校验、帮助和退出码，避免两层解析器吞掉业务参数。
    if argv and argv[0] == "cli":
        if paths.is_source_checkout():
            import cli
        else:
            from app import cli

        cli._force_utf8_console()
        return cli.run_cli(argv[1:])

    parser = argparse.ArgumentParser(prog="mpt", description="MoneyPrinterTurbo")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("cli", help="generate videos (mpt cli --help)")
    webui = commands.add_parser("webui", help="start the WebUI")
    webui.add_argument("--host", default="127.0.0.1", help="listen address")
    webui.add_argument("--port", type=_port_number, help="listen port (default: first free port from 8501)")
    webui.add_argument("--headless", action="store_true", help="do not open a browser")
    args = parser.parse_args(argv)
    if args.command != "webui":
        parser.print_help()
        return 0

    try:
        port = args.port if args.port is not None else _available_port(args.host)
        ui = Path(__file__).resolve().parent.parent / "webui" / "Main.py"
        return subprocess.call([
            sys.executable, "-m", "streamlit", "run", str(ui),
            f"--server.address={args.host}", f"--server.port={port}",
            f"--server.headless={str(args.headless).lower()}",
            "--browser.gatherUsageStats=false", "--client.toolbarMode=minimal",
            "--logger.hideWelcomeMessage=true", "--server.showEmailPrompt=false",
        ])
    except OSError as exc:
        parser.exit(1, f"mpt: {exc}\n")
    except KeyboardInterrupt:
        return 130
