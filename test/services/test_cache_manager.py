import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import cache_manager


class TestVideoCacheManager(unittest.TestCase):
    """验证缓存管理只处理受控文件，并按元数据完成轻量统计与清理。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.temp_dir.name)
        self.storage_patch = patch.object(
            cache_manager.utils,
            "storage_dir",
            return_value=str(self.cache_dir),
        )
        self.storage_patch.start()

    def tearDown(self):
        self.storage_patch.stop()
        self.temp_dir.cleanup()

    def _create_cache_file(self, digest: str, size: int, mtime: float) -> Path:
        path = self.cache_dir / f"vid-{digest}.mp4"
        path.write_bytes(b"x" * size)
        os.utime(path, (mtime, mtime))
        return path

    def test_stats_only_include_managed_top_level_regular_files(self):
        """
        未知文件、嵌套文件和符号链接可能属于用户，不能进入容量统计或清理候选。
        """
        now = 2_000_000_000.0
        self._create_cache_file("a" * 32, 10, now - 40 * 86400)
        self._create_cache_file("b" * 32, 20, now - 2 * 86400)
        (self.cache_dir / "personal.mp4").write_bytes(b"user-video")
        nested_dir = self.cache_dir / "nested"
        nested_dir.mkdir()
        (nested_dir / f"vid-{'c' * 32}.mp4").write_bytes(b"nested")

        symlink_path = self.cache_dir / f"vid-{'d' * 32}.mp4"
        try:
            symlink_path.symlink_to(self.cache_dir / "personal.mp4")
        except (OSError, NotImplementedError):
            # Windows 未开启开发者模式时创建符号链接可能没有权限，不影响其余断言。
            pass

        with patch.object(cache_manager.time, "time", return_value=now):
            total = cache_manager.get_video_cache_stats()
            older_than_30_days = cache_manager.get_video_cache_stats(30)

        self.assertEqual(total.file_count, 2)
        self.assertEqual(total.total_size, 30)
        self.assertEqual(older_than_30_days.file_count, 1)
        self.assertEqual(older_than_30_days.total_size, 10)

    def test_cleanup_rescans_and_preserves_new_or_unknown_files(self):
        now = 2_000_000_000.0
        old_file = self._create_cache_file("a" * 32, 10, now - 40 * 86400)
        new_file = self._create_cache_file("b" * 32, 20, now - 2 * 86400)
        unknown_file = self.cache_dir / "keep-me.mp4"
        unknown_file.write_bytes(b"user-video")

        with patch.object(cache_manager.time, "time", return_value=now):
            result = cache_manager.clean_video_cache(30)

        self.assertEqual(result.deleted_count, 1)
        self.assertEqual(result.deleted_size, 10)
        self.assertEqual(result.failed_count, 0)
        self.assertFalse(old_file.exists())
        self.assertTrue(new_file.exists())
        self.assertTrue(unknown_file.exists())

    def test_cleanup_continues_when_one_file_cannot_be_deleted(self):
        first = self._create_cache_file("a" * 32, 10, 1_000_000_000.0)
        second = self._create_cache_file("b" * 32, 20, 1_000_000_000.0)
        real_unlink = os.unlink

        def unlink_with_failure(path):
            if os.path.basename(path) == first.name:
                raise PermissionError("file is busy")
            return real_unlink(path)

        with patch.object(cache_manager.os, "unlink", side_effect=unlink_with_failure):
            result = cache_manager.clean_video_cache()

        self.assertEqual(result.deleted_count, 1)
        self.assertEqual(result.deleted_size, 20)
        self.assertEqual(result.failed_count, 1)
        self.assertTrue(first.exists())
        self.assertFalse(second.exists())

    def test_invalid_cleanup_age_is_rejected(self):
        with self.assertRaises(ValueError):
            cache_manager.get_video_cache_stats(0)
        with self.assertRaises(ValueError):
            cache_manager.clean_video_cache(-1)
        with self.assertRaises(ValueError):
            cache_manager.clean_video_cache(1.5)
