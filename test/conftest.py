from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from app.config import config
from app.services import asset_library

LIBRARY_IMAGE = "pgvector/pgvector:pg17"


def docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
    except Exception:
        return False
    return True


@pytest.fixture(scope="session")
def library_container() -> Iterator[Any]:
    if not docker_available():
        pytest.skip("docker is not available")
    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer(
        LIBRARY_IMAGE,
        username="asset_library",
        password="asset_library",
        dbname="asset_library",
    )
    with container as running:
        yield running


@pytest.fixture
def library_db(library_container: Any, tmp_path: Any) -> Iterator[str]:
    """Empty library on a throwaway file root, wired into `config.app`."""
    previous = {
        key: config.app.get(key)
        for key in (
            "photo_library_enabled",
            "photo_library_db_host",
            "photo_library_db_port",
            "photo_library_db_name",
            "photo_library_db_user",
            "photo_library_db_password",
            "photo_library_root",
        )
    }
    root = tmp_path / "library"
    config.app["photo_library_enabled"] = True
    config.app["photo_library_db_host"] = library_container.get_container_host_ip()
    config.app["photo_library_db_port"] = int(library_container.get_exposed_port(5432))
    config.app["photo_library_db_name"] = "asset_library"
    config.app["photo_library_db_user"] = "asset_library"
    config.app["photo_library_db_password"] = "asset_library"
    config.app["photo_library_root"] = str(root)

    with asset_library.connect() as conn, conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    asset_library.init_library()

    yield str(root)

    for key, value in previous.items():
        if value is None:
            config.app.pop(key, None)
        else:
            config.app[key] = value
