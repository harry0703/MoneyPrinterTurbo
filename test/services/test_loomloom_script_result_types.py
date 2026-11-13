import json
from unittest.mock import patch

import pytest

from app.services.loomloom import LoomLoomScriptBackend, LoomLoomSettings


@pytest.mark.parametrize("field,value", [
    ("script", None), ("script", False), ("script", 42), ("script", {"text": "Hello"}),
    ("videoTerms", [None]), ("videoTerms", [False]), ("videoTerms", [42]),
    ("videoTerms", [{"term": "ocean"}]),
])
def test_nontext_script_results_become_row_errors(field, value):
    backend = LoomLoomScriptBackend(LoomLoomSettings.from_mapping({"loomloom_api_token": "fixture"}))
    payload = {"script": "Ocean narration", "videoTerms": ["ocean waves"]}
    payload[field] = value
    row = {"rowIndex": 0, "status": "completed", "artifacts": [
        {"portName": "output", "inlineText": json.dumps(payload)}
    ]}
    with patch.object(backend, "_list_all_result_rows", return_value=[row]):
        result = backend.get_script_results("fixture-run")
    assert result.candidates == ()
    assert len(result.errors) == 1
    assert result.errors[0].row_index == 0


def test_valid_text_script_and_search_terms_remain_usable():
    backend = LoomLoomScriptBackend(LoomLoomSettings.from_mapping({"loomloom_api_token": "fixture"}))
    row = {"artifacts": [{"portName": "output", "inlineText": json.dumps({
        "script": " Ocean narration ", "videoTerms": [" ocean waves ", ""]
    })}]}
    candidate = backend._parse_candidate(0, row)
    assert candidate.script == "Ocean narration"
    assert candidate.video_terms == ("ocean waves",)
