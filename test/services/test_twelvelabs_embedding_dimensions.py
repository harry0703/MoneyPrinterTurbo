from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.services import twelvelabs as service


@pytest.mark.parametrize("invalid_vector", [[1.0], [1.0, 0.0, 0.0]])
def test_rerank_preserves_original_order_for_mixed_dimensions(monkeypatch, invalid_vector):
    monkeypatch.setitem(service.config.app, "twelvelabs_api_keys", ["synthetic"])
    monkeypatch.setitem(service.config.app, "twelvelabs_rerank_terms", True)
    vectors = {"subject": [1.0, 0.0], "orthogonal": [0.0, 1.0], "malformed": invalid_vector}

    @contextmanager
    def managed_client():
        yield SimpleNamespace(embed=SimpleNamespace(create=lambda **kw: SimpleNamespace(
            text_embedding=SimpleNamespace(segments=[SimpleNamespace(float_=vectors[kw["text"]])])
        )))

    monkeypatch.setattr(service, "_managed_client", managed_client)
    service._embed_text_cached.cache_clear()
    try:
        terms = ["orthogonal", "malformed"]
        assert service.rerank_terms_by_subject("subject", terms) is terms
    finally:
        service._embed_text_cached.cache_clear()


def test_matching_dimensions_still_rank_by_similarity(monkeypatch):
    monkeypatch.setattr(service, "is_enabled", lambda: True)
    monkeypatch.setitem(service.config.app, "twelvelabs_rerank_terms", True)
    vectors = {"subject": [1.0, 0.0], "orthogonal": [0.0, 1.0], "aligned": [1.0, 0.0]}
    monkeypatch.setattr(service, "embed_text", lambda text, model=None: vectors[text])
    assert service.rerank_terms_by_subject("subject", ["orthogonal", "aligned"]) == ["aligned", "orthogonal"]
