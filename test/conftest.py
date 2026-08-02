"""테스트가 사용자 설정 파일을 건드리지 않게 한다.

WebUI 테스트는 실제 페이지를 끝까지 실행하고, 페이지 마지막에는 `config.save_config()`
가 있다. 그대로 두면 위젯 초기값이 사용자의 `config.toml` 에 그대로 기록되어, 테스트를
한 번 돌릴 때마다 글꼴·언어·자막 설정이 조용히 바뀐다.
"""

import shutil
import tempfile
from pathlib import Path

import pytest

from app.config import config as config_module


# 프로세스 전역으로 살아 있는 설정 섹션. 파일만 격리하면 이 값들은 테스트 사이를
# 그대로 넘어가, 앞 테스트가 남긴 값 때문에 뒤 테스트가 실패한다.
_SHARED_CONFIG_SECTIONS = ("app", "ui", "azure", "siliconflow", "elevenlabs", "chatterbox")


@pytest.fixture(autouse=True)
def isolate_user_config(monkeypatch):
    original = Path(config_module.config_file)
    snapshots = {
        name: dict(getattr(config_module, name)) for name in _SHARED_CONFIG_SECTIONS
    }
    with tempfile.TemporaryDirectory() as work_dir:
        sandbox = Path(work_dir) / "config.toml"
        if original.is_file():
            shutil.copyfile(original, sandbox)
        monkeypatch.setattr(config_module, "config_file", str(sandbox))
        monkeypatch.setattr(config_module, "root_dir", work_dir)
        try:
            yield
        finally:
            for name, snapshot in snapshots.items():
                section = getattr(config_module, name)
                section.clear()
                section.update(snapshot)
