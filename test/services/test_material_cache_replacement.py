import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.models.schema import VideoAspect
from app.services import material_cache


_NOW = 2_000_000_000
_PAYLOAD = (
    '{"version":2,"items":[{"provider":"pixabay","url":"https://example.com/clip.mp4",'
    '"duration":12,"source_info":{"provider":"pixabay"}}]}'
)


def _replacement(path):
    replacement = path.with_suffix('.replacement')
    replacement.write_text(_PAYLOAD, encoding='utf-8')
    os.utime(replacement, (_NOW, _NOW))
    os.replace(replacement, path)


def test_expired_reader_preserves_replacement_published_after_stat():
    with TemporaryDirectory() as directory, patch.object(material_cache.utils, 'storage_dir', return_value=directory):
        cache_path = material_cache._cache_path('pixabay', 'nature', 5, VideoAspect.portrait)
        cache_path.write_text('expired', encoding='utf-8')
        old = _NOW - material_cache.MATERIAL_SEARCH_CACHE_TTL_SECONDS - 1
        os.utime(cache_path, (old, old))
        stat = Path.stat
        published = False

        def replace_after_stat(path, *args, **kwargs):
            nonlocal published
            result = stat(path, *args, **kwargs)
            if path == cache_path and not published:
                published = True
                _replacement(cache_path)
            return result

        with patch.object(Path, 'stat', replace_after_stat):
            assert material_cache.load_material_search_cache('pixabay', 'nature', 5, VideoAspect.portrait, now=_NOW) is None
        assert cache_path.read_text() == _PAYLOAD


def test_corrupt_reader_preserves_replacement_published_after_parse():
    with TemporaryDirectory() as directory, patch.object(material_cache.utils, 'storage_dir', return_value=directory):
        cache_path = material_cache._cache_path('pixabay', 'nature', 5, VideoAspect.portrait)
        cache_path.write_text('{broken', encoding='utf-8')
        os.utime(cache_path, (_NOW, _NOW))
        remove_invalid = material_cache._remove_invalid_cache

        def publish_before_removal(path, *args, **kwargs):
            _replacement(path)
            return remove_invalid(path, *args, **kwargs)

        with patch.object(material_cache, '_remove_invalid_cache', side_effect=publish_before_removal):
            assert material_cache.load_material_search_cache('pixabay', 'nature', 5, VideoAspect.portrait, now=_NOW) is None
        assert cache_path.read_text() == _PAYLOAD


def test_ttl_cleanup_preserves_replacement_since_directory_scan():
    with TemporaryDirectory() as directory, patch.object(material_cache.utils, 'storage_dir', return_value=directory):
        cache_path = Path(directory, 'a' * 64 + '.json')
        cache_path.write_text('expired', encoding='utf-8')
        old = _NOW - material_cache.MATERIAL_SEARCH_CACHE_TTL_SECONDS - 1
        os.utime(cache_path, (old, old))
        scan = os.scandir

        class ScannedEntries:
            def __enter__(self):
                with scan(directory) as entries:
                    self.entries = list(entries)
                    for entry in self.entries:
                        entry.stat(follow_symlinks=False)
                _replacement(cache_path)
                return iter(self.entries)

            def __iter__(self):
                return iter(self.entries)

            def __exit__(self, *args):
                return False

        with patch.object(material_cache.os, 'scandir', return_value=ScannedEntries()):
            assert material_cache.cleanup_expired_material_search_cache(now=_NOW, force=True) == 0
        assert cache_path.exists()


def test_cleanup_keeps_future_dated_active_temporary_file():
    with TemporaryDirectory() as directory, patch.object(material_cache.utils, 'storage_dir', return_value=directory):
        temporary = Path(directory, '.' + 'a' * 64 + '-worker.tmp')
        temporary.write_text('active incomplete upload', encoding='utf-8')
        # A clock rollback can leave an actively written file in the future.
        os.utime(temporary, (_NOW + 60, _NOW + 60))
        assert material_cache.cleanup_expired_material_search_cache(now=_NOW, force=True) == 0
        assert temporary.exists()
