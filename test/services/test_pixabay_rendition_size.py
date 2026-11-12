from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services import material

# The files of one Pixabay video, in the order the API lists them. The API
# documentation gives these as the usual sizes of a 4K video.
LANDSCAPE_4K = {
    "large": (3840, 2160),
    "medium": (1920, 1080),
    "small": (1280, 720),
    "tiny": (960, 540),
}
PORTRAIT_4K = {name: (height, width) for name, (width, height) in LANDSCAPE_4K.items()}
# Older videos have no 4K file: large is 1920x1080 and medium is 1280x720.
LANDSCAPE_HD = {
    "large": (1920, 1080),
    "medium": (1280, 720),
    "small": (960, 540),
    "tiny": (640, 360),
}


def _search_pixabay(renditions, aspect):
    videos = {
        name: {
            "width": width,
            "height": height,
            "url": f"https://cdn.example/1_{name}.mp4",
        }
        for name, (width, height) in renditions.items()
    }
    response = SimpleNamespace(
        status_code=200,
        headers={},
        json=lambda: {"hits": [{"id": 1, "duration": 12, "videos": videos}]},
    )
    with (
        patch.object(material, "get_api_key", return_value="fixture-key"),
        patch.object(material.requests, "get", return_value=response),
    ):
        return material.search_videos_pixabay("nature", 5, aspect)


@pytest.mark.parametrize(
    "renditions,aspect,expected",
    [
        (PORTRAIT_4K, material.VideoAspect.portrait, "medium"),
        (LANDSCAPE_4K, material.VideoAspect.landscape, "medium"),
        (LANDSCAPE_4K, material.VideoAspect.square, "medium"),
        (LANDSCAPE_HD, material.VideoAspect.landscape, "large"),
    ],
    ids=["portrait-4k", "landscape-4k", "square-4k", "landscape-hd"],
)
def test_pixabay_downloads_the_smallest_file_that_fills_the_video(
    renditions, aspect, expected
):
    results = _search_pixabay(renditions, aspect)

    assert [item.url for item in results] == [f"https://cdn.example/1_{expected}.mp4"]
    width, height = renditions[expected]
    assert results[0].source_info["rendition"] == {
        "id": expected,
        "width": width,
        "height": height,
    }
