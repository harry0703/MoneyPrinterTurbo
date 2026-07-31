import runpy
from pathlib import Path
from unittest.mock import patch

from app.config import config


ROOT_DIR = Path(__file__).resolve().parent.parent


def test_main_starts_uvicorn_with_runtime_config():
    """
    서비스 시작 진입점은 실행 설정을 Uvicorn 에 넘기는 역할만 한다. 여기서 실제 서버 시작을 mock 해
    테스트가 포트를 점유하지 않게 하면서, 수신 주소·포트·핫 리로드 설정이 진입점에서 사라지지 않는지 확인한다.
    """
    with (
        patch.object(config, "listen_host", "127.0.0.1"),
        patch.object(config, "listen_port", 8765),
        patch.object(config, "reload_debug", True),
        patch("uvicorn.run") as run_server,
    ):
        runpy.run_path(str(ROOT_DIR / "main.py"), run_name="__main__")

    run_server.assert_called_once_with(
        app="app.asgi:app",
        host="127.0.0.1",
        port=8765,
        reload=True,
        log_level="warning",
    )
