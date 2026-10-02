from unittest.mock import patch
import pytest
from app.models.schema import VideoParams
from app.services import task as tm
from app.services.state import MemoryState

@pytest.mark.parametrize("terms", [" , ， ", ["", " ", "\t"]])
def test_supplied_empty_search_terms_fail_before_reranking(terms):
    params = VideoParams(video_subject="Coffee", video_terms=terms)
    state = MemoryState()
    with (patch.object(tm.sm, "state", state),
          patch.object(tm.llm, "generate_terms") as generate,
          patch.object(tm.twelvelabs, "rerank_terms_by_subject") as rerank):
        result = tm.generate_terms("task-1", params, "Coffee script")
    assert result is None
    assert state.get_task("task-1")["state"] == tm.const.TASK_STATE_FAILED
    generate.assert_not_called()
    rerank.assert_not_called()

def test_empty_terms_are_removed_without_reordering_valid_terms():
    params = VideoParams(video_subject="Coffee", video_terms=" beans , ， roasting , ")
    with patch.object(tm.twelvelabs, "rerank_terms_by_subject", side_effect=lambda **kwargs: kwargs["search_terms"]) as rerank:
        result = tm.generate_terms("task-1", params, "Coffee script")
    assert result == ["beans", "roasting"]
    assert rerank.call_args.kwargs["search_terms"] == ["beans", "roasting"]
