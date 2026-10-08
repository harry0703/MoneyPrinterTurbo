from unittest.mock import MagicMock, patch
import pytest
from app.models.schema import VideoAspect
from app.services import material


@pytest.mark.parametrize(
    "aspect,width,height",
    [
        (VideoAspect.portrait, 2160, 3840),
        (VideoAspect.landscape, 3840, 2160),
        (VideoAspect.square, 1920, 1080),
        (VideoAspect.square, 1080, 1920),
    ],
)
def test_pexels_retains_usable_high_resolution_and_square_crop_sources(
    aspect, width, height
):
    response = MagicMock()
    response.json.return_value = {
        "videos": [
            {
                "id": 1,
                "duration": 10,
                "video_files": [
                    {
                        "id": 2,
                        "width": width,
                        "height": height,
                        "link": "https://example.test/source.mp4",
                    }
                ],
            }
        ]
    }
    with (
        patch.object(material, "get_api_key", return_value="fake-key"),
        patch.object(material.requests, "get", return_value=response),
    ):
        found = material.search_videos_pexels("coffee", 5, aspect)
    assert len(found) == 1
    assert found[0].url == "https://example.test/source.mp4"
    assert found[0].source_info["rendition"]["width"] == width


def test_pexels_still_rejects_wrong_orientation_and_insufficient_dimensions():
    response = MagicMock()
    response.json.return_value = {
        "videos": [
            {
                "id": 1,
                "duration": 10,
                "video_files": [
                    {
                        "width": 1920,
                        "height": 1080,
                        "link": "https://example.test/landscape.mp4",
                    },
                    {
                        "width": 720,
                        "height": 1280,
                        "link": "https://example.test/small.mp4",
                    },
                ],
            }
        ]
    }
    with (
        patch.object(material, "get_api_key", return_value="fake-key"),
        patch.object(material.requests, "get", return_value=response),
    ):
        assert material.search_videos_pexels("coffee", 5, VideoAspect.portrait) == []


def test_pexels_prefers_smallest_adequate_rendition():
    response = MagicMock()
    response.json.return_value = {
        "videos": [
            {
                "duration": 10,
                "video_files": [
                    {
                        "width": 2160,
                        "height": 3840,
                        "link": "https://example.test/4k.mp4",
                    },
                    {
                        "width": 1080,
                        "height": 1920,
                        "link": "https://example.test/hd.mp4",
                    },
                ],
            }
        ]
    }
    with (
        patch.object(material, "get_api_key", return_value="fake-key"),
        patch.object(material.requests, "get", return_value=response),
    ):
        found = material.search_videos_pexels("coffee", 5, VideoAspect.portrait)
    assert found[0].url == "https://example.test/hd.mp4"


def test_square_search_does_not_exclude_crop_compatible_orientations():
    from urllib.parse import parse_qs, urlsplit

    response = MagicMock()
    response.json.return_value = {"videos": []}
    with (
        patch.object(material, "get_api_key", return_value="fake-key"),
        patch.object(material.requests, "get", return_value=response) as request,
    ):
        material.search_videos_pexels("coffee", 5, VideoAspect.square)
    assert "orientation" not in parse_qs(urlsplit(request.call_args.args[0]).query)
