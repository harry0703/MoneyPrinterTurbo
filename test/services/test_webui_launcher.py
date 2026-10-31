"""webui.bat must start the WebUI from folders with ( ) or & in their path.

A ")" in the path of the project folder, as in "MoneyPrinterTurbo-main (1)"
from a second download of the source ZIP or "Program Files (x86)", stopped
the launcher with a cmd syntax error before Python started, and a "&" made it
miss the project Python.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import venv
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).parent.parent.parent

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="webui.bat runs on Windows only"
)

# Stands in for Streamlit and records the arguments webui.bat passed to it.
STREAMLIT_STUB = """\
import json, os, sys

with open(os.environ["MPT_TEST_LAUNCH_RECORD"], "w", encoding="utf-8") as f:
    json.dump(sys.argv[1:], f)
"""


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _make_project(tmp_path, folder_name):
    project = tmp_path / folder_name
    project.mkdir()
    shutil.copyfile(ROOT_DIR / "webui.bat", project / "webui.bat")
    return project


def _run_webui_bat(project, record, extra_path=()):
    """Run webui.bat from its own folder, as a double-click in Explorer does."""
    port = _free_port()
    system_root = os.environ["SYSTEMROOT"]
    env = dict(os.environ)
    env.update(
        # Only Windows itself, so that a uv or streamlit on PATH is not used.
        PATH=os.pathsep.join(
            [
                *extra_path,
                os.path.join(system_root, "System32"),
                system_root,
                os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0"),
            ]
        ),
        MPT_WEBUI_HOST="127.0.0.1",
        MPT_WEBUI_PORT=str(port),
        MPT_TEST_LAUNCH_RECORD=str(record),
    )
    result = subprocess.run(
        ["cmd", "/d", "/c", r".\webui.bat"],
        cwd=project,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
    )
    return result, port


@pytest.mark.parametrize(
    "folder_name",
    ["MoneyPrinterTurbo", "MoneyPrinterTurbo (1)", "R&D MoneyPrinterTurbo"],
)
def test_webui_bat_starts_project_python_from_any_folder(tmp_path, folder_name):
    project = _make_project(tmp_path, folder_name)
    venv.create(project / ".venv", with_pip=False)
    site_packages = project / ".venv" / "Lib" / "site-packages"
    (site_packages / "streamlit.py").write_text(STREAMLIT_STUB, encoding="utf-8")
    record = tmp_path / "streamlit_args.json"

    result, port = _run_webui_bat(project, record)

    assert result.returncode == 0, result.stdout + result.stderr
    assert folder_name in result.stdout  # the "Current directory" line
    assert json.loads(record.read_text(encoding="utf-8"))[:4] == [
        "run",
        r".\webui\Main.py",
        "--server.address=127.0.0.1",
        f"--server.port={port}",
    ]


def test_webui_bat_falls_back_to_uv_from_folder_with_parentheses(tmp_path):
    project = _make_project(tmp_path, "MoneyPrinterTurbo (1)")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uv.bat").write_text(
        '@echo off\n>"%MPT_TEST_LAUNCH_RECORD%" echo %*\n', encoding="ascii"
    )
    record = tmp_path / "uv_args.txt"

    result, port = _run_webui_bat(project, record, extra_path=[str(bin_dir)])

    assert result.returncode == 0, result.stdout + result.stderr
    assert record.read_text(encoding="ascii").split()[:6] == [
        "run",
        "streamlit",
        "run",
        r".\webui\Main.py",
        "--server.address=127.0.0.1",
        f"--server.port={port}",
    ]
