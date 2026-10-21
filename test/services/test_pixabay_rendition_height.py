from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services import material


@pytest.mark.parametrize("aspect,width,short_height,height", [
    (material.VideoAspect.portrait, 1080, 1200, 1920),
    (material.VideoAspect.landscape, 1920, 800, 1080),
])
def test_pixabay_skips_rendition_that_cannot_fill_output_height(aspect, width, short_height, height):
    response = SimpleNamespace(status_code=200, headers={}, json=lambda: {"hits": [{
        "duration": 8,
        "videos": {
            "small": {"width": width, "height": short_height, "url": "https://example.com/short.mp4"},
            "large": {"width": width, "height": height, "url": "https://example.com/full.mp4"},
        },
    }]})
    with patch.object(material, "get_api_key", return_value="fixture-key"), patch.object(material.requests, "get", return_value=response):
        results = material.search_videos_pixabay("nature", 1, aspect)
    assert [item.url for item in results] == ["https://example.com/full.mp4"]
