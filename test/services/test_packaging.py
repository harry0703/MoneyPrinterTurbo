"""验证安装入口、可写目录与资源初始化的关键边界。"""

from concurrent.futures import ThreadPoolExecutor
import errno
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app import launcher, paths


def test_source_checkout_keeps_legacy_paths(monkeypatch):
    monkeypatch.delenv("MPT_HOME", raising=False)
    assert paths.runtime_root() == paths.SOURCE_ROOT
    assert paths.resource_directory("fonts") == paths.SOURCE_ROOT / "resource/fonts"


@pytest.mark.parametrize("platform", ["darwin", "win32", "linux"])
def test_installed_data_is_in_user_directory(monkeypatch, tmp_path, platform):
    monkeypatch.setattr(paths, "is_source_checkout", lambda: False)
    monkeypatch.setattr(paths.sys, "platform", platform)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for key in ("MPT_HOME", "LOCALAPPDATA", "XDG_DATA_HOME"):
        monkeypatch.delenv(key, raising=False)
    expected = {
        "darwin": tmp_path / "Library/Application Support/MoneyPrinterTurbo",
        "win32": tmp_path / "AppData/Local/MoneyPrinterTurbo",
        "linux": tmp_path / ".local/share/MoneyPrinterTurbo",
    }
    assert paths.runtime_root() == expected[platform]


def test_explicit_home_and_linux_xdg_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("MPT_HOME", str(tmp_path / "explicit"))
    assert paths.runtime_root() == tmp_path / "explicit"
    monkeypatch.delenv("MPT_HOME")
    monkeypatch.setattr(paths, "is_source_checkout", lambda: False)
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert paths.runtime_root() == tmp_path / "xdg/MoneyPrinterTurbo"


def test_concurrent_resource_seeding_preserves_existing_files(monkeypatch, tmp_path):
    bundle = tmp_path / "bundle"
    fonts = bundle / "resource/fonts"
    fonts.mkdir(parents=True)
    (fonts / "default.ttf").write_bytes(b"complete font" * 10000)
    (fonts / "custom.ttf").write_bytes(b"bundled original")
    home = tmp_path / "user"
    target = home / "resource/fonts"
    target.mkdir(parents=True)
    (target / "custom.ttf").write_bytes(b"user font")
    monkeypatch.setattr(paths, "is_source_checkout", lambda: False)
    monkeypatch.setattr(paths, "BUNDLED_ROOT", bundle)
    monkeypatch.setenv("MPT_HOME", str(home))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: paths.resource_directory("fonts"), range(8)))
    assert results == [target] * 8
    assert (target / "default.ttf").read_bytes() == (fonts / "default.ttf").read_bytes()
    assert (target / "custom.ttf").read_bytes() == b"user font"
    assert not list(target.glob(".resource-*"))


def _prepare_seeding_fixture(monkeypatch, tmp_path):
    """构造安装版补齐场景：指向独立运行目录与一份内置字体。"""
    bundle = tmp_path / "bundle"
    fonts = bundle / "resource/fonts"
    fonts.mkdir(parents=True)
    (fonts / "default.ttf").write_bytes(b"bundled font" * 5000)
    home = tmp_path / "user"
    monkeypatch.setattr(paths, "is_source_checkout", lambda: False)
    monkeypatch.setattr(paths, "BUNDLED_ROOT", bundle)
    monkeypatch.setenv("MPT_HOME", str(home))
    return fonts / "default.ttf", home / "resource/fonts"


def _refuse_hard_links(source, destination, *args, **kwargs):
    # link(2) 对没有硬链接的文件系统（Linux vfat/exfat 为 EPERM，macOS
    # exFAT/MS-DOS 为 ENOTSUP）返回相应 errno；这里模拟内核的拒绝。
    raise PermissionError(errno.EPERM, "Operation not permitted")


def test_resource_seeding_falls_back_without_hard_links(monkeypatch, tmp_path):
    """exFAT/FAT 盘或部分网络挂载作为运行目录时，补齐仍应完成而不是抛异常。"""
    source_file, target_dir = _prepare_seeding_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(os, "link", _refuse_hard_links)

    target = paths.resource_directory("fonts")

    assert (target / "default.ttf").read_bytes() == source_file.read_bytes()
    assert not list(target.glob(".resource-*"))


def test_fallback_keeps_a_concurrent_winner(monkeypatch, tmp_path):
    """占位独占创建遇到并发胜者时，必须保留胜者文件且不视为失败。"""
    _, target_dir = _prepare_seeding_fixture(monkeypatch, tmp_path)
    winner = target_dir / "default.ttf"
    target_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(os, "link", _refuse_hard_links)
    real_open = os.open

    def winner_claims_the_name(path, flags, *args, **kwargs):
        # 独占创建执行前，另一个进程发布了同名文件：真实 os.open 随即
        # 返回 EEXIST，本次补齐应当放弃而不是覆盖它。
        if os.fspath(path) == str(winner) and flags & os.O_EXCL:
            winner.write_bytes(b"winner font")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", winner_claims_the_name)

    target = paths.resource_directory("fonts")

    assert (target / "default.ttf").read_bytes() == b"winner font"
    assert not list(target.glob(".resource-*"))


def test_fallback_cleans_up_when_the_swap_fails(monkeypatch, tmp_path):
    """独占占位后换入失败时，目标名不能留下空文件，错误必须向上抛出。"""
    source_file = tmp_path / "source.ttf"
    source_file.write_bytes(b"bundled font")
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    target_file = target_dir / "default.ttf"
    monkeypatch.setattr(os, "link", _refuse_hard_links)

    def failing_swap(source, destination, *args, **kwargs):
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(os, "replace", failing_swap)

    with pytest.raises(OSError) as excinfo:
        paths._copy_missing_resource(source_file, target_file)

    assert excinfo.value.errno == errno.EIO
    assert not target_file.exists()
    assert not list(target_dir.glob(".resource-*"))


def test_cli_preserves_arguments_and_exit_status(monkeypatch):
    import cli

    seen = []
    monkeypatch.setattr(cli, "run_cli", lambda args: seen.append(args) or 2)
    assert launcher.main(["cli", "--video-script", "中文", "--stop-at", "script"]) == 2
    assert seen == [["--video-script", "中文", "--stop-at", "script"]]


def test_webui_launch_uses_current_python_and_bundled_ui(monkeypatch):
    called = []
    monkeypatch.setattr(launcher, "_available_port", lambda host: 8504)
    monkeypatch.setattr(launcher.subprocess, "call", lambda command: called.append(command) or 0)
    assert launcher.main(["webui", "--headless"]) == 0
    command = called[0]
    assert command[:3] == [launcher.sys.executable, "-m", "streamlit"]
    assert Path(command[4]) == paths.SOURCE_ROOT / "webui/Main.py"
    assert "--server.address=127.0.0.1" in command
    assert "--server.port=8504" in command
    assert "--server.headless=true" in command


def test_explicit_webui_port_does_not_auto_switch(monkeypatch):
    monkeypatch.setattr(launcher, "_available_port", lambda _: pytest.fail("unexpected scan"))
    monkeypatch.setattr(launcher.subprocess, "call", lambda command: 1)
    assert launcher.main(["webui", "--port", "8501"]) == 1


@pytest.mark.parametrize("port", ["0", "65536", "invalid"])
def test_invalid_port_is_rejected(port):
    with pytest.raises(SystemExit) as exc:
        launcher.main(["webui", "--port", port])
    assert exc.value.code == 2


def test_sdist_and_wheel_allowlists_exclude_private_files():
    import tomllib

    project = tomllib.loads((paths.SOURCE_ROOT / "pyproject.toml").read_text())
    build = project["tool"]["hatch"]["build"]["targets"]
    assert project["project"]["scripts"]["mpt"] == "app.launcher:main"
    assert build["wheel"]["force-include"]["cli.py"] == "app/cli.py"
    for entry in build["sdist"]["include"]:
        assert entry not in ("/config.toml", "/storage", "/AGENTS.md", "/.env")
    assert "app" in build["wheel"]["packages"]
    assert "webui" in build["wheel"]["packages"]


def test_cli_stdout_contains_only_json(tmp_path):
    env = os.environ.copy()
    env["MPT_HOME"] = str(tmp_path / "data")
    result = subprocess.run(
        [sys.executable, str(paths.SOURCE_ROOT / "cli.py"), "--video-script", "本地测试",
         "--stop-at", "script"],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["result"]["script"] == "本地测试"
    assert "load config" in result.stderr


@pytest.mark.parametrize("media_type", ["image/png", "audio/mpeg", "video/mp4"])
def test_streamlit_media_responses_keep_valid_asgi_headers(media_type):
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Route
    from starlette.testclient import TestClient
    from streamlit.web.server.starlette.starlette_gzip_middleware import SelectiveGZipMiddleware

    async def media(request):
        return Response(b"media payload" * 200, media_type=media_type)

    app = SelectiveGZipMiddleware(Starlette(routes=[Route("/media", media)]))
    with TestClient(app) as client:
        result = client.get("/media", headers={"Accept-Encoding": "gzip"})
    assert result.status_code == 200
    assert result.content == b"media payload" * 200
