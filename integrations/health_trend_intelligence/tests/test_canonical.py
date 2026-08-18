import hashlib

import pytest

from health_trend_intelligence.canonical import (
    canonical_json_bytes,
    canonical_jsonl_bytes,
    load_unique_json,
    sha256_bytes,
)


def test_unique_json_rejects_duplicate_keys() -> None:
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_unique_json(b'{"schema":"a","schema":"b"}')


def test_canonical_json_is_nfc_sorted_compact_utf8_and_single_lf() -> None:
    result = canonical_json_bytes({"z": "e\u0301", "a": ["\u4f60\u597d"]})
    assert result == b'{"a":["\xe4\xbd\xa0\xe5\xa5\xbd"],"z":"\xc3\xa9"}\n'
    assert result.endswith(b"\n")
    assert not result.endswith(b"\n\n")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_json_rejects_nonfinite_numbers(value: float) -> None:
    with pytest.raises(ValueError):
        canonical_json_bytes({"value": value})


def test_canonical_jsonl_sorts_by_stable_key_and_uses_one_lf_per_record() -> None:
    records = ({"id": "b", "value": 2}, {"id": "a", "value": 1})
    assert canonical_jsonl_bytes(records, stable_key=lambda record: record["id"]) == (
        b'{"id":"a","value":1}\n{"id":"b","value":2}\n'
    )


def test_canonical_jsonl_rejects_non_object_records() -> None:
    with pytest.raises(ValueError, match="object"):
        canonical_jsonl_bytes(("not an object",), stable_key=lambda record: record)


def test_unique_json_loads_utf8_bytes_and_sha256_hashes_exact_bytes() -> None:
    payload = b'{"a":1}'
    assert load_unique_json(payload) == {"a": 1}
    assert sha256_bytes(payload) == hashlib.sha256(payload).hexdigest()
