import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.utils import utils


def test_normalize_returns_default_for_none():
    assert utils.normalize_clip_speed(None) == 1.0


def test_normalize_clamps_below_min():
    assert utils.normalize_clip_speed(0.1) == 0.5


def test_normalize_clamps_above_max():
    assert utils.normalize_clip_speed(5.0) == 2.0


def test_normalize_passes_valid_value():
    assert utils.normalize_clip_speed(1.3) == 1.3


def test_normalize_rejects_non_numeric_and_non_positive():
    assert utils.normalize_clip_speed("abc") == 1.0
    assert utils.normalize_clip_speed(0) == 1.0
    assert utils.normalize_clip_speed(-2) == 1.0
