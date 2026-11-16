"""webui.bat must start the WebUI from any folder and on the host in MPT_WEBUI_HOST.

A ")" in the path of the project folder, as in "MoneyPrinterTurbo-main (1)"
from a second download of the source ZIP or "Program Files (x86)", stopped
the launcher with a cmd syntax error before Python started, and a "&" made it
miss the project Python.

MPT_WEBUI_HOST=0.0.0.0, which the README gives for access from other devices
on the LAN, stopped the launcher with "No available WebUI port found", because
the port check looked the host up with Dns.GetHostAddresses(), which rejects
0.0.0.0. Streamlit was also told to open http://0.0.0.0 in the browser, an
address that Windows does not connect to.

With 0.0.0.0 the port check must also skip a port that another program, such
as an earlier WebUI, listens on at 127.0.0.1: Windows lets a plain bind to
0.0.0.0 share that port, and the browser would open the other program.

Run as administrator starts batch files in the System32 folder of Windows, and
a cmd window in another folder starts webui.bat in that folder. The launcher
took the folder it was started in for the project, so it stopped with "Neither
project Python, uv, nor streamlit was found" although the project had its
.venv, or ran uv in the wrong folder.
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

# Stands in for Streamlit and records the arguments webui.bat passed to it, and
# in a second file the folder it runs in.
STREAMLIT_STUB = """\
import json, os, sys

record = os.environ["MPT_TEST_LAUNCH_RECORD"]
with open(record, "w", encoding="utf-8") as f:
    json.dump(sys.argv[1:], f)
with open(record + ".cwd", "w", encoding="utf-8") as f:
    f.write(os.getcwd())
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


def _add_venv_with_streamlit_stub(project):
    venv.create(project / ".venv", with_pip=False)
    site_packages = project / ".venv" / "Lib" / "site-packages"
    (site_packages / "streamlit.py").write_text(STREAMLIT_STUB, encoding="utf-8")


def _run_webui_bat(
    project, record, extra_path=(), host="127.0.0.1", port=None, cwd=None
):
    """Run webui.bat from its own folder, as a double-click in Explorer does,
    or by its full path from the folder cwd."""
    if cwd is None:
        cwd, command = project, ["cmd", "/d", "/c", r".\webui.bat"]
    else:
        # The doubled quotes keep the path quoted with spaces, ( ) or & in it;
        # /s makes cmd strip only the outer pair.
        command = f'cmd /d /s /c ""{project / "webui.bat"}""'
    if port is None:
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
        MPT_WEBUI_HOST=host,
        MPT_WEBUI_PORT=str(port),
        MPT_TEST_LAUNCH_RECORD=str(record),
    )
    result = subprocess.run(
        command,
        cwd=cwd,
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
    _add_venv_with_streamlit_stub(project)
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


@pytest.mark.parametrize(
    "folder_name",
    ["MoneyPrinterTurbo", "MoneyPrinterTurbo (1)", "R&D MoneyPrinterTurbo"],
)
def test_webui_bat_starts_project_python_when_started_in_system32(
    tmp_path, folder_name
):
    # Run as administrator starts batch files in C:\Windows\System32.
    system32 = Path(os.environ["SYSTEMROOT"], "System32")
    project = _make_project(tmp_path, folder_name)
    _add_venv_with_streamlit_stub(project)
    record = tmp_path / "streamlit_args.json"

    result, port = _run_webui_bat(project, record, cwd=system32)

    assert result.returncode == 0, result.stdout + result.stderr
    assert folder_name in result.stdout  # the "Current directory" line
    # Streamlit opens .\webui\Main.py from the folder it runs in.
    streamlit_cwd = Path(f"{record}.cwd").read_text(encoding="utf-8")
    assert Path(streamlit_cwd) == project
    assert json.loads(record.read_text(encoding="utf-8"))[:4] == [
        "run",
        r".\webui\Main.py",
        "--server.address=127.0.0.1",
        f"--server.port={port}",
    ]


def test_webui_bat_runs_uv_in_project_folder_when_started_in_system32(tmp_path):
    system32 = Path(os.environ["SYSTEMROOT"], "System32")
    project = _make_project(tmp_path, "MoneyPrinterTurbo (1)")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Records the folder that uv runs in; cmd /u writes it as UTF-16, whatever the code page.
    (bin_dir / "uv.bat").write_text(
        '@echo off\n>"%MPT_TEST_LAUNCH_RECORD%" cmd /d /u /c cd\n', encoding="ascii"
    )
    record = tmp_path / "uv_cwd.txt"

    result, _ = _run_webui_bat(project, record, extra_path=[str(bin_dir)], cwd=system32)

    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(record.read_text(encoding="utf-16-le").strip()) == project


@pytest.mark.parametrize(
    ("host", "browser_host"),
    [
        ("127.0.0.1", "127.0.0.1"),
        ("localhost", "localhost"),
        # The README's setting for access from other devices on the LAN. The
        # WebUI listens on every interface; the browser opens 127.0.0.1.
        ("0.0.0.0", "127.0.0.1"),
    ],
)
def test_webui_bat_listens_on_host_and_opens_browser_on_reachable_address(
    tmp_path, host, browser_host
):
    project = _make_project(tmp_path, "MoneyPrinterTurbo")
    _add_venv_with_streamlit_stub(project)
    record = tmp_path / "streamlit_args.json"

    result, port = _run_webui_bat(project, record, host=host)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"WebUI address: http://{browser_host}:{port} *****" in result.stdout
    assert json.loads(record.read_text(encoding="utf-8"))[2:5] == [
        f"--server.address={host}",
        f"--server.port={port}",
        f"--browser.serverAddress={browser_host}",
    ]


def test_webui_bat_drops_the_space_a_cmd_one_liner_leaves_in_the_host(tmp_path):
    # "set MPT_WEBUI_HOST=0.0.0.0 && webui.bat" keeps the space before "&&".
    project = _make_project(tmp_path, "MoneyPrinterTurbo")
    _add_venv_with_streamlit_stub(project)
    record = tmp_path / "streamlit_args.json"

    result, port = _run_webui_bat(project, record, host="0.0.0.0 ")

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(record.read_text(encoding="utf-8"))[2:5] == [
        "--server.address=0.0.0.0",
        f"--server.port={port}",
        "--browser.serverAddress=127.0.0.1",
    ]


@pytest.mark.parametrize(
    "held_on",
    [
        # An earlier WebUI that is still running on the default host.
        "127.0.0.1",
        # Only bound, not listening: listening on 0.0.0.0 can bring up the
        # Windows Firewall prompt, and a bound socket already holds the port.
        "0.0.0.0",
    ],
)
def test_webui_bat_lan_host_skips_a_port_already_in_use(tmp_path, held_on):
    project = _make_project(tmp_path, "MoneyPrinterTurbo")
    _add_venv_with_streamlit_stub(project)
    record = tmp_path / "streamlit_args.json"

    with socket.socket() as other:
        other.bind((held_on, 0))
        if held_on == "127.0.0.1":
            other.listen()
        busy_port = other.getsockname()[1]
        result, _ = _run_webui_bat(project, record, host="0.0.0.0", port=busy_port)

    assert result.returncode == 0, result.stdout + result.stderr
    args = json.loads(record.read_text(encoding="utf-8"))
    port = int(args[3].removeprefix("--server.port="))
    assert port != busy_port, result.stdout
    assert f"Port {busy_port} is unavailable, using {port} instead." in result.stdout
    assert f"WebUI address: http://127.0.0.1:{port} *****" in result.stdout
    assert args[2:5] == [
        "--server.address=0.0.0.0",
        f"--server.port={port}",
        "--browser.serverAddress=127.0.0.1",
    ]
