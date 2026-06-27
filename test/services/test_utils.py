import sys
import unittest
from pathlib import Path

# 测试文件直接运行时，也能从仓库根目录导入 app 包。
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.utils import utils


class TestUtils(unittest.TestCase):
    def test_strip_markdown_removes_common_script_formatting(self):
        source = (
            "# Launch Plan\n"
            "\n"
            "Opening with **bold** energy.\n"
            "\n"
            "---\n"
            "\n"
            "- First beat\n"
            "1. Second beat"
        )

        self.assertEqual(
            utils.strip_markdown(source),
            "Launch Plan\n\nOpening with bold energy.\n\nFirst beat\nSecond beat",
        )

    def test_strip_markdown_leaves_plain_text_unchanged(self):
        source = "First line.\nSecond line with 1.5 values.\nNo markdown tokens here."

        self.assertEqual(utils.strip_markdown(source), source)

    def test_strip_markdown_handles_empty_and_whitespace_only_text(self):
        self.assertEqual(utils.strip_markdown(""), "")
        self.assertEqual(utils.strip_markdown(" \n\t\n "), "")

    def test_strip_markdown_cleans_links_and_images(self):
        source = (
            "Read [the docs](https://example.com/docs) before recording.\n"
            "![cover image](https://example.com/cover.png)\n"
            "Keep [reference label][ref]."
        )

        cleaned = utils.strip_markdown(source)

        self.assertEqual(
            cleaned,
            "Read the docs before recording.\n\nKeep reference label.",
        )
        self.assertNotIn("https://example.com", cleaned)


if __name__ == "__main__":
    unittest.main()
