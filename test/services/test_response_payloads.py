"""The shared API envelope must preserve explicit data values."""

import json

import pytest

from app.utils import utils


@pytest.mark.parametrize("data", [False, 0, "", [], {}])
def test_response_preserves_explicit_falsy_payloads(data):
    response = utils.get_response(200, data=data)
    serialized = json.loads(json.dumps(response))
    assert "data" in serialized
    assert serialized["data"] == data


def test_response_without_data_retains_status_only_contract():
    assert utils.get_response(200) == {"status": 200}
