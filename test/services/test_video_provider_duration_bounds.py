import importlib
from unittest.mock import patch

import pytest

from app.config import config


@pytest.mark.parametrize(
    "module_name, prefix",
    [
        ("app.services.ofox", "ofox"),
        ("app.services.muapi", "muapi"),
        ("app.services.volcengine_seedance", "volcengine_seedance"),
    ],
)
@pytest.mark.parametrize("bad_value", [float("inf"), float("-inf"), float("nan")])
def test_nonfinite_configured_duration_bounds_fall_back_to_defaults(
    module_name, prefix, bad_value
):
    # TOML can express inf/nan. Invalid bounds must use the documented
    # defaults instead of escaping as a raw OverflowError.
    module = importlib.import_module(module_name)
    settings = {
        f"{prefix}_min_duration": bad_value,
        f"{prefix}_max_duration": bad_value,
    }

    with patch.dict(config.app, settings):
        bounds = module._duration_bounds()

    assert bounds == (
        module.DEFAULT_MIN_DURATION_SECONDS,
        max(module.DEFAULT_MIN_DURATION_SECONDS, module.DEFAULT_MAX_DURATION_SECONDS),
    )
