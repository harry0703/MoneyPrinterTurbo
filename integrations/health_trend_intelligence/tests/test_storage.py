from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from health_trend_intelligence.storage import DataLayout, PathSafetyError


def test_layout_creates_only_three_data_layers(tmp_path: Path) -> None:
    layout = DataLayout.from_root(tmp_path / "health-trend-intelligence")

    layout.initialize()

    assert sorted(path.name for path in layout.root.iterdir()) == [
        "approved",
        "curated",
        "raw",
    ]


def test_layout_requires_an_absolute_root() -> None:
    with pytest.raises(PathSafetyError):
        DataLayout.from_root(Path("relative-root"))


def test_layout_rejects_lexical_parent_traversal(tmp_path: Path) -> None:
    unsafe_root = tmp_path / "parent" / ".." / "data"

    with pytest.raises(PathSafetyError):
        DataLayout.from_root(unsafe_root)


def test_layout_rejects_symlink_component_before_initializing(tmp_path: Path) -> None:
    actual_parent = tmp_path / "actual"
    actual_parent.mkdir()
    linked_parent = tmp_path / "linked"
    try:
        os.symlink(actual_parent, linked_parent, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"current account cannot create directory symlinks: {error.winerror}")

    with pytest.raises(PathSafetyError):
        DataLayout.from_root(linked_parent / "data")

    assert not (actual_parent / "data").exists()


def test_initialize_fails_closed_if_a_layer_is_replaced_by_symlink(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    try:
        os.symlink(elsewhere, root / "raw", target_is_directory=True)
    except OSError as error:
        pytest.skip(f"current account cannot create directory symlinks: {error.winerror}")

    layout = DataLayout.from_root(root)
    with pytest.raises(PathSafetyError):
        layout.initialize()

    assert not (root / "curated").exists()
    assert not (root / "approved").exists()


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows reparse type")
def test_layout_rejects_junction_component(tmp_path: Path) -> None:
    actual_parent = tmp_path / "junction-target"
    actual_parent.mkdir()
    junction = tmp_path / "junction"
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(actual_parent)],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip("current account cannot create a directory junction")

    with pytest.raises(PathSafetyError):
        DataLayout.from_root(junction / "data")

    assert not (actual_parent / "data").exists()
