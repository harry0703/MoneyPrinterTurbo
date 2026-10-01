from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from app.models.schema import VideoAspect
from app.services import material_cache


@pytest.mark.parametrize('duration', ['1e309', 'Infinity', '-Infinity', 'NaN', '0.5'])
def test_corrupted_duration_is_a_cache_miss(duration):
    with TemporaryDirectory() as directory, patch.object(material_cache.utils, 'storage_dir', return_value=directory):
        cache_path = material_cache._cache_path('pixabay', 'nature', 5, VideoAspect.portrait)
        cache_path.write_text(
            '{"version":2,"items":[{"provider":"pixabay","url":"https://example.com/clip.mp4",'
            '"source_info":{"provider":"pixabay"},"duration":' + duration + '}]}'
        )
        assert material_cache.load_material_search_cache('pixabay', 'nature', 5, VideoAspect.portrait) is None
        assert not Path(cache_path).exists()


def test_legacy_finite_float_duration_remains_usable():
    with TemporaryDirectory() as directory, patch.object(material_cache.utils, 'storage_dir', return_value=directory):
        cache_path = material_cache._cache_path('pixabay', 'nature', 5, VideoAspect.portrait)
        cache_path.write_text(
            '{"version":2,"items":[{"provider":"pixabay","url":"https://example.com/clip.mp4",'
            '"source_info":{"provider":"pixabay"},"duration":12.5}]}'
        )
        items = material_cache.load_material_search_cache('pixabay', 'nature', 5, VideoAspect.portrait)
        assert items[0].duration == 12
