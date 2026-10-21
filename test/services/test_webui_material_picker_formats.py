"""Execute the real WebUI picker expressions without starting the full app."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import material_upload


def _picker_types():
    source = Path(__file__).parents[2] / "webui" / "Main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names = {"LOCAL_MATERIAL_EXTENSIONS", "local_file_types"}
    assignments = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)
    ]
    uploader = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "file_uploader"
        and any(keyword.arg == "key" and isinstance(keyword.value, ast.Constant)
                and keyword.value.value == "local_video_materials_uploader"
                for keyword in node.keywords)
    )
    namespace = {
        "material_upload_service": material_upload,
        "st": SimpleNamespace(file_uploader=MagicMock()),
        "tr": lambda text: text,
    }
    statements = sorted(assignments, key=lambda node: node.lineno)
    module = ast.fix_missing_locations(ast.Module(
        body=[*statements, ast.Expr(value=uploader)], type_ignores=[]
    ))
    exec(compile(module, str(source), "exec"), namespace)
    return namespace["st"].file_uploader.call_args.kwargs["type"]


@pytest.mark.parametrize("extension", [".bmp", ".webm"])
def test_local_picker_accepts_formats_supported_by_upload_service(extension):
    assert material_upload.sanitize_material_filename("local" + extension)
    picker = _picker_types()
    assert extension[1:] in picker
    assert extension[1:].upper() in picker


def test_picker_tracks_service_formats_without_duplicates():
    picker = _picker_types()
    expected = {
        value.removeprefix(".")
        for value in material_upload.SUPPORTED_MATERIAL_EXTENSIONS
    }
    assert set(picker) == expected | {value.upper() for value in expected}
    assert len(picker) == len(set(picker))
