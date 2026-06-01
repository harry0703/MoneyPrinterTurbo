import sys
import tempfile
import unittest
from pathlib import Path

# 测试文件直接运行时，也能从仓库根目录导入 app 包。
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import subtitle


class TestSubtitleService(unittest.TestCase):
    def test_correct_ignores_markdown_separator_lines(self):
        """
        Whisper fallback 校正阶段也必须忽略 `---` 这类不可发声脚本行。

        如果这里继续保留 Markdown 分隔符，`correct()` 会认为脚本行数多于
        字幕行数，并补出 `00:00:00,000 --> 00:00:00,000`，剪辑软件会把
        生成的 SRT 判定为不可导入。
        """
        original_srt = (
            "1\n"
            "00:00:00,100 --> 00:00:01,000\n"
            "第一段\n\n"
            "2\n"
            "00:00:01,100 --> 00:00:02,000\n"
            "第二段\n\n"
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "subtitle.srt"
            subtitle_file.write_text(original_srt, encoding="utf-8")

            subtitle.correct(
                subtitle_file=str(subtitle_file),
                video_script="第一段\n---\n第二段",
            )

            corrected_srt = subtitle_file.read_text(encoding="utf-8")

        self.assertIn("第一段", corrected_srt)
        self.assertIn("第二段", corrected_srt)
        self.assertNotIn("---", corrected_srt)
        self.assertNotIn("00:00:00,000 --> 00:00:00,000", corrected_srt)


if __name__ == "__main__":
    unittest.main()
