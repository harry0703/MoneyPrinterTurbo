import ast
from pathlib import Path

import pytest

from webui.service_navigation import parse_console_navigation


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://127.0.0.1:8848", "http://127.0.0.1:8848"),
        ("http://localhost:1/console", "http://localhost:1/console"),
        ("http://[::1]:65535/app/", "http://[::1]:65535/app/"),
    ],
)
def test_parser_accepts_explicit_loopback_http_urls(raw, expected):
    result = parse_console_navigation(raw)

    assert result.state == "ENABLED"
    assert result.url == expected
    assert result.warning_code is None


@pytest.mark.parametrize(
    "raw",
    [
        "https://127.0.0.1:8848",
        "file:///tmp/console",
        "http://example.com:8848",
        "http://127.0.0.1",
        "http://user@127.0.0.1:8848",
        "http://127.0.0.1:8848/?token=x",
        "http://127.0.0.1:8848/#fragment",
        "http://127.0.0.1:0",
        "http://127.0.0.1:65536",
        "http://127.0.0.1:8848/../secret",
    ],
)
def test_parser_ignores_invalid_urls_without_echoing_input(raw):
    result = parse_console_navigation(raw)

    assert result.state == "IGNORED"
    assert result.url is None
    assert result.warning_code == "INVALID_CONSOLE_URL"
    assert raw not in repr(result)


def test_parser_treats_missing_value_as_disabled():
    result = parse_console_navigation(None)

    assert result.state == "DISABLED"
    assert result.url is None
    assert result.warning_code is None


def test_main_renders_current_tab_link_without_configuration_writes():
    source = (Path(__file__).parents[2] / "webui" / "Main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "INDEPENDENT_MEDIA_CONSOLE_URL" in source
    assert 'target="_self"' in source
    assert "parse_console_navigation" in source
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"save_config", "update_config"}
        and any(
            isinstance(argument, ast.Constant)
            and argument.value == "INDEPENDENT_MEDIA_CONSOLE_URL"
            for argument in node.args
        )
        for node in ast.walk(tree)
    )
