from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

import pytest

from app.config import config
from app.services import asset_library
from app.services.asset_library import store


def _write_image(path: str, size: tuple[int, int] = (64, 48), color: int = 10) -> str:
    from PIL import Image

    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, (color, color, color)).save(path)
    return path


def _vector(seed: int) -> list[float]:
    values = [0.0] * asset_library.EMBEDDING_DIM
    values[seed % asset_library.EMBEDDING_DIM] = 1.0
    return values


def test_library_is_disabled_without_config() -> None:
    previous = config.app.pop("photo_library_enabled", None)
    try:
        assert asset_library.is_enabled() is False
    finally:
        if previous is not None:
            config.app["photo_library_enabled"] = previous


def test_connection_params_default_to_the_compose_file() -> None:
    keys = (
        "photo_library_db_host",
        "photo_library_db_port",
        "photo_library_db_name",
        "photo_library_db_user",
        "photo_library_db_password",
    )
    previous = {key: config.app.pop(key, None) for key in keys}
    try:
        assert asset_library.connection_params() == {
            "host": "127.0.0.1",
            "port": 5433,
            "dbname": "asset_library",
            "user": "asset_library",
            "password": "",
        }
    finally:
        for key, value in previous.items():
            if value is not None:
                config.app[key] = value


def test_importing_the_package_does_not_import_the_driver() -> None:
    probe = (
        "import sys; import app.services.asset_library as lib; "
        "print('psycopg' in sys.modules or 'pgvector' in sys.modules)"
    )
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"


def test_format_vector_rejects_wrong_dimension() -> None:
    with pytest.raises(ValueError):
        store.format_vector([0.1, 0.2])
    assert store.format_vector(_vector(3)).startswith("[")


def test_library_root_falls_back_to_repo_relative_default() -> None:
    previous = config.app.pop("photo_library_root", None)
    try:
        expected = os.path.join(config.root_dir, "storage", "library")
        assert asset_library.library_root() == expected
        config.app["photo_library_root"] = "  "
        assert asset_library.library_root() == expected
    finally:
        config.app.pop("photo_library_root", None)
        if previous is not None:
            config.app["photo_library_root"] = previous


def test_normalize_tags_lowercases_and_deduplicates() -> None:
    tags = store.normalize_tags(
        [" Spider ", "spider", asset_library.AssetTag("Web", 2.0)]
    )
    assert [(tag.tag, tag.weight) for tag in tags] == [("spider", 1.0), ("web", 2.0)]


def test_init_library_repeats_without_losing_data(
    library_db: str, tmp_path: Any
) -> None:
    source = _write_image(str(tmp_path / "src" / "spider.png"))
    asset_library.ingest_file(source, group="spiders")

    asset_library.init_library()

    assets = asset_library.list_assets()
    assert len(assets) == 1
    with asset_library.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        assert cur.fetchone() is not None
        cur.execute(
            "SELECT indexname FROM pg_indexes WHERE indexname = 'asset_embedding_idx'"
        )
        assert cur.fetchone() is not None
        cur.execute("SELECT count(*) AS total FROM schema_migration")
        assert cur.fetchone()["total"] == 1
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'asset' AND column_name = 'collection'"
        )
        assert cur.fetchone() is None


def test_ingest_copies_file_and_stores_relative_path(
    library_db: str, tmp_path: Any
) -> None:
    source = _write_image(str(tmp_path / "src" / "spider.png"), size=(120, 90))
    result = asset_library.ingest_file(source, group="Spiders")

    assert result.created is True
    asset = result.asset
    assert asset.rel_path == "spiders/spider.png"
    assert not os.path.isabs(asset.rel_path)
    assert asset.width == 120 and asset.height == 90
    assert asset.sha256 == asset_library.file_digest(source)
    assert os.path.isfile(os.path.join(library_db, "spiders", "spider.png"))
    assert os.path.isfile(source)
    assert [(tag.tag, tag.weight) for tag in asset.tags] == [("spiders", 1.0)]


def test_ingest_is_idempotent_and_applies_manual_annotation(
    library_db: str, tmp_path: Any
) -> None:
    source = _write_image(str(tmp_path / "src" / "spider.png"))
    duplicate = _write_image(str(tmp_path / "other" / "copy.png"))
    first = asset_library.ingest_file(source, group="spiders")

    second = asset_library.ingest_file(
        duplicate,
        group="spiders",
        tags=["web"],
        caption="a spider on a web",
        min_display=2.5,
    )

    assert second.created is False
    assert second.asset.id == first.asset.id
    assert second.asset.caption == "a spider on a web"
    assert second.asset.caption_manual is True
    assert second.asset.min_display == pytest.approx(2.5)
    assert set(second.asset.tag_names()) == {"spiders", "web"}
    assert len(asset_library.list_assets()) == 1
    assert sorted(os.listdir(os.path.join(library_db, "spiders"))) == ["spider.png"]


def test_annotation_never_overwrites_manual_values(
    library_db: str, tmp_path: Any
) -> None:
    source = _write_image(str(tmp_path / "src" / "spider.png"))
    asset = asset_library.ingest_file(
        source, group="spiders", tags=["web"], caption="hand written", min_display=3.0
    ).asset

    asset_library.save_annotation(
        asset.id,
        model="annotator-v1",
        caption="model written",
        tags=["macro", "insect"],
        has_text=True,
        min_display=1.0,
    )

    stored = asset_library.get_asset(asset.id)
    assert stored.caption == "hand written"
    assert stored.min_display == pytest.approx(3.0)
    assert stored.has_text is True
    assert stored.annotate_model == "annotator-v1"
    assert set(stored.tag_names()) == {"spiders", "web", "macro", "insect"}

    asset_library.save_annotation(asset.id, model="annotator-v2", tags=["macro"])
    stored = asset_library.get_asset(asset.id)
    assert stored.caption == "hand written"
    assert set(stored.tag_names()) == {"spiders", "web", "macro"}


def test_ingest_directory_tags_by_group_directory(
    library_db: str, tmp_path: Any
) -> None:
    base = tmp_path / "scouted"
    _write_image(str(base / "spiders" / "one.png"), color=11)
    _write_image(str(base / "spiders" / "two.png"), color=12)
    _write_image(str(base / "webs" / "three.png"), color=13)
    _write_image(str(base / "flat.png"), color=14)

    results = asset_library.ingest_directory(str(base), tags=["scouted"])

    assert len(results) == 4
    assert all(result.created for result in results)
    groups = {result.asset.rel_path.split("/")[0] for result in results}
    assert groups == {"spiders", "webs", "scouted"}
    for result in results:
        assert "scouted" in result.asset.tag_names()

    again = asset_library.ingest_directory(str(base))
    assert not any(result.created for result in again)
    assert len(asset_library.list_assets()) == 4


def test_search_ranks_by_cosine_distance_and_filters_tags(
    library_db: str, tmp_path: Any
) -> None:
    ids = {}
    for index, group in enumerate(("spiders", "webs", "cities")):
        source = _write_image(str(tmp_path / "src" / f"{group}.png"), color=20 + index)
        asset = asset_library.ingest_file(source, group=group).asset
        asset_library.save_embedding(asset.id, _vector(index), model="embed-v1")
        ids[group] = asset.id

    found = asset_library.search_assets(_vector(1), limit=3)
    assert [asset.id for asset in found][0] == ids["webs"]
    assert found[0].distance == pytest.approx(0.0, abs=1e-6)

    found = asset_library.search_assets(_vector(1), any_tags=["Spiders", "cities"])
    assert {asset.id for asset in found} == {ids["spiders"], ids["cities"]}

    found = asset_library.search_assets(_vector(1), exclude_tags=["webs"])
    assert ids["webs"] not in {asset.id for asset in found}

    found = asset_library.search_assets(_vector(1), exclude_ids=[ids["webs"]])
    assert ids["webs"] not in {asset.id for asset in found}

    found = asset_library.search_assets(_vector(1), max_distance=0.5)
    assert [asset.id for asset in found] == [ids["webs"]]


def test_search_skips_assets_whose_file_disappeared(
    library_db: str, tmp_path: Any
) -> None:
    source = _write_image(str(tmp_path / "src" / "spider.png"))
    asset = asset_library.ingest_file(source, group="spiders").asset
    asset_library.save_embedding(asset.id, _vector(0), model="embed-v1")
    os.remove(os.path.join(library_db, *asset.rel_path.split("/")))

    assert asset_library.search_assets(_vector(0)) == []
    assert len(asset_library.list_assets()) == 1


def test_search_plan_uses_the_hnsw_index(library_db: str, tmp_path: Any) -> None:
    for index in range(20):
        source = _write_image(str(tmp_path / "src" / f"{index}.png"), color=index)
        asset = asset_library.ingest_file(source, group="bulk").asset
        asset_library.save_embedding(asset.id, _vector(index), model="embed-v1")

    vector = store.format_vector(_vector(3))
    with asset_library.connect() as conn, conn.cursor() as cur:
        # A 20-row table is cheaper to scan than to index; the planner has to be
        # told that seq scan is off the table before the choice means anything.
        cur.execute("SET enable_seqscan = off")
        cur.execute(
            "EXPLAIN SELECT a.id FROM asset a WHERE a.embedding IS NOT NULL "
            "ORDER BY a.embedding <=> %s::vector LIMIT 5",
            (vector,),
        )
        plan = "\n".join(row["QUERY PLAN"] for row in cur.fetchall())
    assert "asset_embedding_idx" in plan
    assert "Seq Scan" not in plan


def test_usage_and_summary_track_the_library(library_db: str, tmp_path: Any) -> None:
    first = asset_library.ingest_file(
        _write_image(str(tmp_path / "src" / "a.png"), color=31), group="spiders"
    ).asset
    second = asset_library.ingest_file(
        _write_image(str(tmp_path / "src" / "b.png"), color=32), group="webs"
    ).asset
    asset_library.save_embedding(second.id, _vector(2), model="embed-v1")
    asset_library.save_annotation(second.id, model="annotator-v1", caption="a web")

    asset_library.record_usage(first.id, "task-1")
    asset_library.record_usage(first.id, "task-2")

    reloaded = asset_library.get_asset(first.id)
    assert reloaded.use_count == 2
    assert reloaded.last_used_at is not None
    with asset_library.connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT task_id FROM asset_usage WHERE asset_id = %s ORDER BY task_id",
            (first.id,),
        )
        assert [row["task_id"] for row in cur.fetchall()] == ["task-1", "task-2"]

    report = asset_library.summary()
    assert report.total == 2
    assert report.without_annotation == 1
    assert report.without_embedding == 1
    assert report.tags == {"spiders": 1, "webs": 1}

    assert [a.id for a in asset_library.assets_missing_annotation()] == [first.id]
    assert [a.id for a in asset_library.assets_missing_embedding()] == [first.id]
    stale = asset_library.assets_missing_embedding(embed_model="embed-v2")
    assert {a.id for a in stale} == {first.id, second.id}


def test_set_tags_replaces_only_its_own_origin(library_db: str, tmp_path: Any) -> None:
    source = _write_image(str(tmp_path / "src" / "spider.png"))
    asset = asset_library.ingest_file(source, group="spiders", tags=["web"]).asset
    asset_library.save_annotation(asset.id, model="annotator-v1", tags=["macro"])

    asset_library.set_tags(
        asset.id, ["arachnid", asset_library.AssetTag("closeup", 0.5)]
    )

    stored = asset_library.get_asset(asset.id)
    assert set(stored.tag_names()) == {"macro", "arachnid", "closeup"}
    weights = {tag.tag: tag.weight for tag in stored.tags}
    assert weights["closeup"] == pytest.approx(0.5)


def test_delete_asset_removes_row_and_file(library_db: str, tmp_path: Any) -> None:
    source = _write_image(str(tmp_path / "src" / "spider.png"))
    asset = asset_library.ingest_file(source, group="spiders").asset
    asset_library.record_usage(asset.id, "task-1")
    stored = os.path.join(library_db, *asset.rel_path.split("/"))

    assert asset_library.delete_asset(asset.id) is True
    assert not os.path.exists(stored)
    assert asset_library.get_asset(asset.id) is None
    assert asset_library.delete_asset(asset.id) is False
    assert asset_library.list_assets() == []
    assert os.path.isfile(source)


def test_list_assets_filters_by_tag_and_pages(library_db: str, tmp_path: Any) -> None:
    for index in range(3):
        source = _write_image(str(tmp_path / "src" / f"{index}.png"), color=40 + index)
        asset_library.ingest_file(source, group="spiders" if index else "webs")

    assert len(asset_library.list_assets(any_tags=["spiders"])) == 2
    assert len(asset_library.list_assets(limit=1)) == 1
    assert len(asset_library.list_assets(limit=10, offset=2)) == 1


def test_ingest_rejects_unknown_extension_and_missing_file(
    library_db: str, tmp_path: Any
) -> None:
    with pytest.raises(ValueError):
        asset_library.ingest_file(str(tmp_path / "note.txt"), group="misc")
    with pytest.raises(ValueError):
        asset_library.ingest_file(str(tmp_path / "gone.png"), group="misc")
    with pytest.raises(ValueError):
        asset_library.ingest_directory(str(tmp_path / "gone"))


def test_ingest_keeps_both_files_when_names_collide(
    library_db: str, tmp_path: Any
) -> None:
    first = _write_image(str(tmp_path / "a" / "shot.png"), color=51)
    second = _write_image(str(tmp_path / "b" / "shot.png"), color=52)

    one = asset_library.ingest_file(first, group="spiders").asset
    two = asset_library.ingest_file(second, group="spiders").asset

    assert one.rel_path == "spiders/shot.png"
    assert two.rel_path.startswith("spiders/shot-")
    assert len(os.listdir(os.path.join(library_db, "spiders"))) == 2


def test_broken_image_is_skipped_by_directory_ingest(
    library_db: str, tmp_path: Any
) -> None:
    base = tmp_path / "scouted"
    _write_image(str(base / "good.png"), color=61)
    (base / "broken.png").write_bytes(b"not an image")

    results = asset_library.ingest_directory(str(base))

    assert len(results) == 1
    assert results[0].asset.rel_path == "scouted/good.png"


def test_search_records_the_origin_of_scouted_assets(
    library_db: str, tmp_path: Any
) -> None:
    source = _write_image(str(tmp_path / "src" / "spider.png"))
    asset = asset_library.ingest_file(
        source,
        group="spiders",
        origin=asset_library.ORIGIN_SEARCH,
        source_query="spider macro",
        source_url="https://example.test/spider.png",
    ).asset

    assert asset.origin == asset_library.ORIGIN_SEARCH
    assert asset.source_query == "spider macro"
    assert asset.source_url == "https://example.test/spider.png"
