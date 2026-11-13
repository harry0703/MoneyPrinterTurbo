"""Comma-separated stock-media API keys must never store blank entries."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


def _save_material_api_keys():
    # Execute the actual helper body without running the Streamlit page.
    source = ROOT / "webui" / "Main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_save_material_api_keys"
    )
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    saved = {}

    def set_runtime_config(section, key, value):
        saved[(section, key)] = value

    namespace = {"_set_runtime_config": set_runtime_config}
    exec(compile(module, str(source), "exec"), namespace)
    return namespace["_save_material_api_keys"], saved


@pytest.mark.parametrize(
    "typed, expected",
    [
        ("key-one, key-two,", ["key-one", "key-two"]),
        ("key-one,,key-two", ["key-one", "key-two"]),
        (",key-one", ["key-one"]),
        ("key-one", ["key-one"]),
        ("", []),
        (" , ", []),
    ],
)
def test_material_api_keys_drop_blank_entries(typed, expected):
    # material.get_api_key rotates through this list, so a blank entry would
    # periodically send a request without credentials.
    save, saved = _save_material_api_keys()

    save("pexels_api_keys", typed)

    assert saved[("app", "pexels_api_keys")] == expected
