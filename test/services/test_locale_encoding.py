import json

import pytest

from app.utils.utils import load_locales


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_locale_loading_accepts_utf8_with_or_without_bom(tmp_path, encoding):
    content = {"label": "Français", "embedded": "keep\ufeffinside"}
    (tmp_path / "fr.json").write_text(json.dumps(content, ensure_ascii=False), encoding=encoding)
    try:
        assert load_locales(str(tmp_path)) == {"fr": content}
    finally:
        load_locales.cache_clear()
