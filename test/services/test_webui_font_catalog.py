"""Font choices must resolve to the file the recursive UI catalog discovered."""

import ast
import os
from pathlib import Path
import shutil

from PIL import ImageFont
import pytest

from app.utils.file_security import resolve_path_within_directory

ROOT = Path(__file__).parents[2]


def _catalog(font_dir):
    # Follow the existing headless WebUI tests: execute the actual helper body
    # without running the full page or retaining the 30-second UI cache.
    source = ROOT / "webui" / "Main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_all_fonts"
    )
    function.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    namespace = {"os": os, "font_dir": str(font_dir)}
    exec(compile(module, str(source), "exec"), namespace)
    return namespace["get_all_fonts"]()


def _copy_font(destination, style):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "resource" / "fonts" / f"Charm-{style}.ttf", destination)


def test_nested_font_option_reaches_native_renderer(tmp_path):
    font_dir = tmp_path / "fonts"
    nested = font_dir / "Brand" / "OnlyNested.ttf"
    _copy_font(nested, "Bold")
    options = _catalog(font_dir)
    assert len(options) == 1
    selected_path = resolve_path_within_directory(str(font_dir), options[0])
    assert Path(selected_path) == nested.resolve()
    assert ImageFont.truetype(selected_path, 30).getname() == ("Charm", "Bold")


def test_duplicate_basenames_keep_distinct_faces_and_root_choice(tmp_path):
    font_dir = tmp_path / "fonts"
    root_font = font_dir / "Shared.ttf"
    nested_font = font_dir / "Brand" / "Shared.ttf"
    _copy_font(root_font, "Regular")
    _copy_font(nested_font, "Bold")
    options = _catalog(font_dir)
    assert "Shared.ttf" in options  # Existing root-level selections stay valid.
    assert len(options) == len(set(options)) == 2
    faces = {
        ImageFont.truetype(
            resolve_path_within_directory(str(font_dir), option), 30
        ).getname()
        for option in options
    }
    assert faces == {("Charm", "Regular"), ("Charm", "Bold")}


def test_nested_catalog_choice_keeps_renderer_containment(tmp_path):
    font_dir = tmp_path / "fonts"
    outside = tmp_path / "outside.ttf"
    _copy_font(outside, "Bold")
    nested = font_dir / "Brand" / "Linked.ttf"
    nested.parent.mkdir(parents=True)
    try:
        nested.symlink_to(outside)
    except OSError:
        pytest.skip("This host does not allow fixture symlinks")
    options = _catalog(font_dir)
    assert len(options) == 1
    with pytest.raises(ValueError):
        resolve_path_within_directory(str(font_dir), options[0])
