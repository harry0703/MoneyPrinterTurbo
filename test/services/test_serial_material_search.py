from unittest.mock import Mock, patch

import pytest
from app.models.schema import MaterialInfo, VideoAspect
from app.services import material


@pytest.mark.parametrize("workers", [1, 2])
def test_failed_term_does_not_abort_remaining_stock_search(monkeypatch, workers):
    monkeypatch.setattr(material, "_get_material_concurrency", lambda: workers)
    healthy = MaterialInfo(url="https://example.test/clip.mp4", duration=5)
    def find_term(search_term, *args, **kwargs):
        if search_term == "bad term":
            raise ValueError("malformed provider response")
        return [healthy]

    search = Mock(side_effect=find_term)
    result = material._search_terms_in_parallel(
        ["bad term", "healthy term"], search, 5, VideoAspect.portrait
    )
    assert result == [("bad term", []), ("healthy term", [healthy])]
    assert search.call_count == 2


@pytest.mark.parametrize("workers", [1, 2])
def test_failed_term_log_keeps_the_error_detail(monkeypatch, workers):
    monkeypatch.setattr(material, "_get_material_concurrency", lambda: workers)
    monkeypatch.delitem(material.config.app, "pexels_api_keys", raising=False)
    with patch.object(material.logger, "error") as error:
        result = material._search_terms_in_parallel(
            ["ocean", "beach"], material.search_videos_pexels, 5, VideoAspect.portrait
        )
    assert result == [("ocean", []), ("beach", [])]
    assert error.call_count == 2
    for call in error.call_args_list:
        assert "pexels_api_keys is not set" in call.args[0]


def test_serial_success_preserves_order_and_empty_results(monkeypatch):
    monkeypatch.setattr(material, "_get_material_concurrency", lambda: 1)
    healthy = MaterialInfo(url="https://example.test/clip.mp4", duration=5)
    assert material._search_terms_in_parallel(
        ["empty", "healthy"], Mock(side_effect=[[], [healthy]]), 5, VideoAspect.portrait
    ) == [("empty", []), ("healthy", [healthy])]
