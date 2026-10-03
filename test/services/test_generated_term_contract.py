from unittest.mock import Mock

import pytest
from app.services import llm


@pytest.mark.parametrize("ordered", [False, True])
def test_generated_terms_are_trimmed_and_bounded_before_material_search(monkeypatch, ordered):
    generate = Mock(return_value='[" ", " forest ", "", "city", "unrequested extra"]')
    monkeypatch.setattr(llm, "_generate_response", generate)
    assert llm.generate_terms("topic", "narration", amount=2, match_script_order=ordered) == ["forest", "city"]
    assert generate.call_count == 1


def test_blank_model_terms_retry_instead_of_reaching_stock_providers(monkeypatch):
    generate = Mock(side_effect=['["", "   "]', '["forest"]'])
    monkeypatch.setattr(llm, "_generate_response", generate)
    assert llm.generate_terms("topic", "narration", amount=2) == ["forest"]
    assert generate.call_count == 2


def test_ordered_repeated_topics_remain_valid(monkeypatch):
    monkeypatch.setattr(llm, "_generate_response", Mock(return_value='["forest", "city", "forest"]'))
    assert llm.generate_terms("topic", "narration", amount=3, match_script_order=True) == ["forest", "city", "forest"]
