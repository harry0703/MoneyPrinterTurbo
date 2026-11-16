import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# 测试文件直接运行时，也能从仓库根目录导入 app 包。
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import subtitle


class TestSubtitleService(unittest.TestCase):
    def test_concurrent_subtitles_initialize_whisper_once(self):
        """Concurrent jobs must not load the large Whisper model twice."""
        first_constructor_started = threading.Event()
        release_constructor = threading.Event()
        second_constructor_started = threading.Event()
        constructor_calls = []

        class FakeWhisperModel:
            def __init__(self, **_kwargs):
                constructor_calls.append(1)
                if len(constructor_calls) == 1:
                    first_constructor_started.set()
                else:
                    second_constructor_started.set()
                release_constructor.wait(timeout=2)

            def transcribe(self, _audio_file, **_kwargs):
                return [], SimpleNamespace(language="en", language_probability=1.0)

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(subtitle, "model", None),
                patch.object(subtitle, "WhisperModel", FakeWhisperModel),
            ):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    first = executor.submit(
                        subtitle.create, "audio-1.mp3", str(Path(temp_dir) / "1.srt")
                    )
                    self.assertTrue(first_constructor_started.wait(timeout=1))
                    second = executor.submit(
                        subtitle.create, "audio-2.mp3", str(Path(temp_dir) / "2.srt")
                    )
                    try:
                        duplicate_load = second_constructor_started.wait(timeout=0.2)
                    finally:
                        release_constructor.set()
                    first.result(timeout=2)
                    second.result(timeout=2)

        self.assertFalse(duplicate_load, "Whisper was loaded twice")
        self.assertEqual(len(constructor_calls), 1)

    def test_file_to_subtitles_returns_empty_for_missing_input(self):
        """空路径和不存在的文件都应安全返回空列表。"""
        self.assertEqual(subtitle.file_to_subtitles(""), [])
        with tempfile.TemporaryDirectory() as tmp_dir:
            missing_file = Path(tmp_dir) / "missing.srt"
            self.assertEqual(subtitle.file_to_subtitles(str(missing_file)), [])

    def test_transcribe_audio_bytes_returns_editable_text_and_cleans_temps(self):
        temporary_paths = []

        def fake_create(audio_file, subtitle_file, word_level=False, log_details=True):
            self.assertFalse(word_level)
            self.assertFalse(log_details)
            temporary_paths.extend([Path(audio_file), Path(subtitle_file)])
            self.assertEqual(Path(audio_file).read_bytes(), b"wav-audio")
            Path(subtitle_file).write_text(
                "1\n00:00:00,000 --> 00:00:01,000\n第一句\n\n"
                "2\n00:00:01,000 --> 00:00:02,000\nOpen A I\n\n",
                encoding="utf-8",
            )

        with patch.object(subtitle, "create", side_effect=fake_create):
            transcript = subtitle.transcribe_audio_bytes(b"wav-audio")

        self.assertEqual(transcript, "第一句 Open A I")
        self.assertTrue(all(not path.exists() for path in temporary_paths))

    def test_transcribe_audio_bytes_returns_empty_when_whisper_fails(self):
        with patch.object(subtitle, "create", return_value=""):
            self.assertEqual(subtitle.transcribe_audio_bytes(b"wav-audio"), "")

    def test_create_can_hide_sensitive_paths_and_recognized_text(self):
        class _FakeWhisperModel:
            def __init__(self, **_kwargs):
                pass

            def transcribe(self, _audio_file, **_kwargs):
                word = SimpleNamespace(start=0.0, end=0.5, word="private transcript.")
                segment = SimpleNamespace(start=0.0, end=0.5, words=[word])
                info = SimpleNamespace(language="en", language_probability=0.99)
                return [segment], info

        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "private-reference.srt"
            with (
                patch.object(subtitle, "model", None),
                patch.object(subtitle, "WhisperModel", _FakeWhisperModel),
                patch.object(subtitle.logger, "info") as info,
                patch.object(subtitle.logger, "debug") as debug,
            ):
                subtitle.create(
                    str(Path(tmp_dir) / "private-reference.wav"),
                    str(subtitle_file),
                    log_details=False,
                )

        logged = " ".join(str(call) for call in info.call_args_list)
        self.assertNotIn("private-reference", logged)
        self.assertNotIn("private transcript", logged)
        debug.assert_not_called()

    def test_levenshtein_distance_and_similarity_cover_common_boundaries(self):
        """
        字幕校正依赖编辑距离选择是否继续合并相邻字幕，因此覆盖空字符串、
        参数交换、大小写忽略和明显不相似四种边界，防止算法调整后误合并。
        """
        self.assertEqual(subtitle.levenshtein_distance("kitten", "sitting"), 3)
        self.assertEqual(subtitle.levenshtein_distance("a", "longer"), 6)
        self.assertEqual(subtitle.levenshtein_distance("hello", ""), 5)
        self.assertEqual(subtitle.similarity("Hello", "hello"), 1.0)
        self.assertLess(subtitle.similarity("hello", "world"), 0.5)

    def test_create_returns_empty_when_whisper_is_unavailable(self):
        """可选 Whisper 依赖未安装时应跳过，而不是在任务线程中抛异常。"""
        with patch.object(subtitle, "WhisperModel", None):
            self.assertEqual(subtitle.create("audio.mp3"), "")

    def test_create_returns_none_when_whisper_model_cannot_load(self):
        """模型下载或初始化失败时必须返回失败结果，并允许任务层更新状态。"""
        with patch.object(subtitle, "model", None), patch.object(
            subtitle,
            "WhisperModel",
            side_effect=RuntimeError("model unavailable"),
        ):
            self.assertIsNone(subtitle.create("audio.mp3"))

    def test_create_writes_punctuated_and_trailing_segments(self):
        """
        使用假的 Whisper 模型覆盖逐词时间戳处理，不访问网络也不加载真实模型。
        一个 segment 同时包含标点断句和末尾无标点文本，可验证两条关键写入路径。
        """

        class _FakeWhisperModel:
            def __init__(self, **kwargs):
                self.init_kwargs = kwargs

            def transcribe(self, audio_file, **kwargs):
                words = [
                    SimpleNamespace(start=0.0, end=0.4, word="Hello"),
                    SimpleNamespace(start=0.4, end=0.9, word=" world."),
                    SimpleNamespace(start=1.0, end=1.5, word="Again"),
                ]
                segment = SimpleNamespace(
                    start=0.0,
                    end=1.8,
                    words=words,
                )
                info = SimpleNamespace(language="en", language_probability=0.99)
                return [segment], info

        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "generated.srt"
            with patch.object(subtitle, "model", None), patch.object(
                subtitle,
                "WhisperModel",
                _FakeWhisperModel,
            ):
                subtitle.create("audio.mp3", str(subtitle_file))

            items = subtitle.file_to_subtitles(str(subtitle_file))

        self.assertEqual([item[2] for item in items], ["Hello world", "Again"])

    def test_create_preserves_numeric_punctuation_and_sentence_timing(self):
        words = [
            SimpleNamespace(start=0.0, end=0.2, word="Value"),
            SimpleNamespace(start=0.2, end=0.5, word=" 3.14"),
            SimpleNamespace(start=0.5, end=0.8, word=" costs"),
            SimpleNamespace(start=0.8, end=1.1, word=" 1,000"),
            SimpleNamespace(start=1.1, end=1.4, word=" dollars."),
            SimpleNamespace(start=1.5, end=1.8, word="Next!"),
        ]
        fake_model = SimpleNamespace(
            transcribe=lambda *_args, **_kwargs: (
                [SimpleNamespace(start=0.0, end=1.8, words=words)],
                SimpleNamespace(language="en", language_probability=0.99),
            )
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "numeric.srt"
            with patch.object(subtitle, "model", fake_model), patch.object(
                subtitle, "WhisperModel", object()
            ):
                subtitle.create("audio.mp3", str(output))
            items = subtitle.file_to_subtitles(str(output))
        self.assertEqual(
            items,
            [
                (1, "00:00:00,000 --> 00:00:01,400", "Value 3.14 costs 1,000 dollars"),
                (2, "00:00:01,500 --> 00:00:01,800", "Next"),
            ],
        )

    def test_create_removes_only_trailing_sentence_punctuation(self):
        words = [
            SimpleNamespace(start=0.0, end=0.3, word="3.14?!"),
            SimpleNamespace(start=0.4, end=0.7, word="1,000"),
        ]
        fake_model = SimpleNamespace(
            transcribe=lambda *_args, **_kwargs: (
                [SimpleNamespace(start=0.0, end=0.7, words=words)],
                SimpleNamespace(language="en", language_probability=0.99),
            )
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "suffix.srt"
            with patch.object(subtitle, "model", fake_model), patch.object(
                subtitle, "WhisperModel", object()
            ):
                subtitle.create("audio.mp3", str(output))
            items = subtitle.file_to_subtitles(str(output))
        self.assertEqual([item[2] for item in items], ["3.14", "1,000"])

    def test_create_word_level_writes_each_whisper_word_with_its_timing(self):
        """逐词模式应保留 Whisper 的每个词及其独立起止时间。"""
        transcribe_kwargs = {}

        class _FakeWhisperModel:
            def __init__(self, **_kwargs):
                pass

            def transcribe(self, _audio_file, **kwargs):
                transcribe_kwargs.update(kwargs)
                words = [
                    SimpleNamespace(start=0.1, end=0.4, word="Hello"),
                    SimpleNamespace(start=0.4, end=0.8, word=" world"),
                ]
                segment = SimpleNamespace(start=0.1, end=0.8, words=words)
                info = SimpleNamespace(language="en", language_probability=0.99)
                return [segment], info

        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "word-level.srt"
            with patch.object(subtitle, "model", None), patch.object(
                subtitle,
                "WhisperModel",
                _FakeWhisperModel,
            ):
                subtitle.create(
                    "audio.mp3",
                    str(subtitle_file),
                    word_level=True,
                )

            items = subtitle.file_to_subtitles(str(subtitle_file))

        self.assertEqual([item[2] for item in items], ["Hello", "world"])
        self.assertIs(transcribe_kwargs["word_timestamps"], True)
        self.assertIs(transcribe_kwargs["vad_filter"], True)
        self.assertIn("00:00:00,100 --> 00:00:00,400", items[0][1])
        self.assertIn("00:00:00,400 --> 00:00:00,800", items[1][1])

    def test_create_falls_back_to_segment_when_word_alignment_is_missing(self):
        """Whisper may return a segment with no aligned words in either mode."""

        class FakeWhisperModel:
            def __init__(self, **_kwargs):
                pass

            def transcribe(self, _audio_file, **_kwargs):
                segments = [
                    SimpleNamespace(start=0.1, end=0.8, text="Hello", words=None),
                    SimpleNamespace(start=0.9, end=1.4, text="world", words=[]),
                ]
                info = SimpleNamespace(language="en", language_probability=0.99)
                return segments, info

        for word_level in (False, True):
            with self.subTest(word_level=word_level):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    subtitle_file = Path(tmp_dir) / "unaligned.srt"
                    with (
                        patch.object(subtitle, "model", None),
                        patch.object(subtitle, "WhisperModel", FakeWhisperModel),
                    ):
                        subtitle.create(
                            "audio.mp3", str(subtitle_file), word_level=word_level
                        )
                    items = subtitle.file_to_subtitles(str(subtitle_file))

                self.assertEqual([item[2] for item in items], ["Hello", "world"])
                self.assertIn("00:00:00,100 --> 00:00:00,800", items[0][1])

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

    def test_correct_ignores_symbol_only_scene_break_lines(self):
        """
        Scene breaks made only of symbols, such as `* * *` or `———`, are never
        spoken either. Kept as script lines, they took the next caption's time
        and pushed that caption to `00:00:00,000 --> 00:00:00,000`.
        """
        original_srt = (
            "1\n00:00:00,100 --> 00:00:01,000\nWelcome to the show\n\n"
            "2\n00:00:01,100 --> 00:00:02,000\nLet us begin\n\n"
        )

        for separator in [
            "* * *",
            "\u2014\u2014\u2014",
            "\u2022 \u2022 \u2022",
            "= = =",
        ]:
            with self.subTest(separator=separator):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    subtitle_file = Path(tmp_dir) / "subtitle.srt"
                    subtitle_file.write_text(original_srt, encoding="utf-8")

                    subtitle.correct(
                        subtitle_file=str(subtitle_file),
                        video_script=f"Welcome to the show.\n{separator}\nLet us begin.",
                    )

                    items = subtitle.file_to_subtitles(str(subtitle_file))

                self.assertEqual(
                    [(item[1], item[2]) for item in items],
                    [
                        ("00:00:00,100 --> 00:00:01,000", "Welcome to the show"),
                        ("00:00:01,100 --> 00:00:02,000", "Let us begin"),
                    ],
                )

    def test_correct_merges_adjacent_subtitles_for_one_script_sentence(self):
        """
        Whisper 可能把一句文案拆成多个时间块。校正逻辑应合并时间范围并恢复
        原始脚本文本，避免最终字幕出现不必要的碎片。
        """
        original_srt = (
            "1\n00:00:00,100 --> 00:00:01,000\nHello\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nworld\n\n"
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "subtitle.srt"
            subtitle_file.write_text(original_srt, encoding="utf-8")

            subtitle.correct(str(subtitle_file), "Hello world")
            items = subtitle.file_to_subtitles(str(subtitle_file))

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][1], "00:00:00,100 --> 00:00:02,000")
        self.assertEqual(items[0][2], "Hello world")

    def test_correct_removes_transcription_after_script_ends(self):
        """Whisper's trailing hallucinations must not appear as final captions."""
        original_srt = (
            "1\n00:00:00,100 --> 00:00:01,000\nHello world\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nUnspoken words\n\n"
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "subtitle.srt"
            subtitle_file.write_text(original_srt, encoding="utf-8")

            subtitle.correct(str(subtitle_file), "Hello world")
            items = subtitle.file_to_subtitles(str(subtitle_file))

        self.assertEqual([item[2] for item in items], ["Hello world"])

    def test_correct_preserves_transcription_when_script_outlasts_cues(self):
        """An incomplete alignment must not overwrite usable timed captions."""
        original_srt = "1\n00:00:00,100 --> 00:00:01,000\nWrong text\n\n"

        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "subtitle.srt"
            subtitle_file.write_text(original_srt, encoding="utf-8")

            subtitle.correct(str(subtitle_file), "Expected sentence. Extra sentence.")
            self.assertEqual(subtitle_file.read_text(encoding="utf-8"), original_srt)

    def test_correct_preserves_comma_split_transcription(self):
        # Cutting the first cue between the two lines it holds still leaves the
        # last sentence of the script without a cue, so the transcription is kept.
        original_srt = (
            "1\n00:00:00,100 --> 00:00:02,000\nIt runs as you so it can change memory\n\n"
            "2\n00:00:02,500 --> 00:00:04,000\nThat is the gate\n\n"
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "subtitle.srt"
            subtitle_file.write_text(original_srt, encoding="utf-8")
            subtitle.correct(
                str(subtitle_file),
                "It runs as you, so it can change memory. That is the gate. Stay safe.",
            )
            self.assertEqual(subtitle_file.read_text(encoding="utf-8"), original_srt)

    def test_correct_rolls_back_merges_when_alignment_exhausts_cues(self):
        # Even equal initial counts can run out of cues after a fuzzy merge.
        original_srt = (
            "1\n00:00:00,100 --> 00:00:01,000\nHello\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nworld\n\n"
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "subtitle.srt"
            subtitle_file.write_text(original_srt, encoding="utf-8")
            subtitle.correct(str(subtitle_file), "Hello world. Another sentence.")
            self.assertEqual(subtitle_file.read_text(encoding="utf-8"), original_srt)

    def test_correct_does_not_fabricate_cues_without_transcription(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "subtitle.srt"
            subtitle_file.write_text("", encoding="utf-8")
            subtitle.correct(str(subtitle_file), "A sentence with no timing.")
            self.assertEqual(subtitle_file.read_bytes(), b"")

    def test_correct_still_replaces_mismatch_with_available_timing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "subtitle.srt"
            subtitle_file.write_text(
                "1\n00:00:00,100 --> 00:00:01,000\nWrong text\n\n",
                encoding="utf-8",
            )
            subtitle.correct(str(subtitle_file), "Expected sentence.")
            self.assertEqual(
                subtitle.file_to_subtitles(str(subtitle_file)),
                [(1, "00:00:00,100 --> 00:00:01,000", "Expected sentence")],
            )

    def test_correct_does_not_split_thai_script_at_sentence_spaces(self):
        """
        create() does not end a Whisper segment at the space that ends a Thai
        sentence, so one segment can hold two sentences. Split there, the script
        would have more lines than segments, and its last sentences would get the
        00:00:00,000 placeholder.
        """
        sentences = [
            "กาแฟเป็นเครื่องดื่มที่ได้รับความนิยมทั่วโลก",
            "ทุกเช้าผู้คนนับล้านเริ่มต้นวันด้วยกาแฟหนึ่งแก้ว",
            "กาแฟช่วยให้ร่างกายตื่นตัวและมีสมาธิมากขึ้น",
            "แต่การดื่มมากเกินไปอาจทำให้นอนไม่หลับ",
        ]
        original_srt = (
            f"1\n00:00:00,100 --> 00:00:04,650\n{sentences[0]} {sentences[1]}\n\n"
            f"2\n00:00:04,650 --> 00:00:09,588\n{sentences[2]} {sentences[3]}\n\n"
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "subtitle.srt"
            subtitle_file.write_text(original_srt, encoding="utf-8")

            subtitle.correct(str(subtitle_file), " ".join(sentences))
            items = subtitle.file_to_subtitles(str(subtitle_file))

        self.assertEqual(
            [(item[1], item[2]) for item in items],
            [("00:00:00,100 --> 00:00:09,588", " ".join(sentences))],
        )

    def _correct_cues(self, cues, script):
        original_srt = "".join(
            f"{i}\n{times}\n{text}\n\n" for i, (times, text) in enumerate(cues, 1)
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "subtitle.srt"
            subtitle_file.write_text(original_srt, encoding="utf-8")
            subtitle.correct(str(subtitle_file), script)
            items = subtitle.file_to_subtitles(str(subtitle_file))
        return [(item[1], item[2]) for item in items]

    def test_correct_shares_a_cue_that_holds_the_next_script_line(self):
        """
        Whisper can leave out a comma that the script has. One cue then holds
        two script lines: the first line got the whole cue and every later line
        the cue of the line after it, until the cues ran out and the
        transcription was kept.
        """
        cues = [
            (
                "00:00:00,000 --> 00:00:06,800",
                "Risky calls are held before they run and reads pass straight through",
            ),
            ("00:00:07,000 --> 00:00:08,000", "That is the gate"),
        ]

        self.assertEqual(
            self._correct_cues(
                cues,
                "Risky calls are held before they run, and reads pass straight "
                "through. That is the gate.",
            ),
            [
                ("00:00:00,000 --> 00:00:03,600", "Risky calls are held before they run"),
                ("00:00:03,600 --> 00:00:06,800", "and reads pass straight through"),
                ("00:00:07,000 --> 00:00:08,000", "That is the gate"),
            ],
        )

    def test_correct_shares_a_cue_between_several_script_lines(self):
        """Without the commas of the script, one cue can hold three lines."""
        cues = [("00:00:00,000 --> 00:00:03,400", "今天天气很好我们去公园散步然后回家")]

        self.assertEqual(
            self._correct_cues(cues, "今天天气很好，我们去公园散步，然后回家。"),
            [
                ("00:00:00,000 --> 00:00:01,200", "今天天气很好"),
                ("00:00:01,200 --> 00:00:02,600", "我们去公园散步"),
                ("00:00:02,600 --> 00:00:03,400", "然后回家"),
            ],
        )

    def test_correct_shares_a_cue_after_a_turkish_line_with_dotted_capital_i(self):
        """
        "İ".lower() has two characters. The cue is still cut where the line
        ends, not one character later for each İ.
        """
        cues = [
            (
                "00:00:00,000 --> 00:00:04,700",
                "İzmir'e İlknur ve İsmail ile gittik çok güzeldi",
            )
        ]

        self.assertEqual(
            self._correct_cues(cues, "İzmir'e İlknur ve İsmail ile gittik, çok güzeldi."),
            [
                ("00:00:00,000 --> 00:00:03,500", "İzmir'e İlknur ve İsmail ile gittik"),
                ("00:00:03,500 --> 00:00:04,700", "çok güzeldi"),
            ],
        )

    def test_correct_gives_the_next_line_the_rest_of_a_cue_and_its_own_cue(self):
        """A cue can end inside the next line, which then goes on in the next cue."""
        cues = [
            (
                "00:00:00,000 --> 00:00:05,100",
                "Risky calls are held before they run and reads pass",
            ),
            ("00:00:05,200 --> 00:00:06,000", "straight through"),
        ]

        self.assertEqual(
            self._correct_cues(
                cues,
                "Risky calls are held before they run, and reads pass straight through.",
            ),
            [
                ("00:00:00,000 --> 00:00:03,600", "Risky calls are held before they run"),
                ("00:00:03,600 --> 00:00:06,000", "and reads pass straight through"),
            ],
        )

    def test_correct_keeps_a_cue_whose_extra_words_are_not_the_next_line(self):
        """Words that Whisper added, and that do not start the next line, keep the cue."""
        cues = [
            ("00:00:00,000 --> 00:00:03,000", "Welcome back thank you for watching"),
            ("00:00:03,500 --> 00:00:05,000", "Today we cook rice"),
        ]

        self.assertEqual(
            self._correct_cues(cues, "Welcome back. Today we cook rice."),
            [
                ("00:00:00,000 --> 00:00:03,000", "Welcome back"),
                ("00:00:03,500 --> 00:00:05,000", "Today we cook rice"),
            ],
        )

    def test_correct_keeps_a_cue_whose_last_words_the_next_cue_repeats(self):
        """
        Whisper can write the start of the next line at the end of a cue and
        again at the start of the next cue. The next line keeps its own cue.
        """
        cues = [
            ("00:00:00,100 --> 00:00:01,500", "We went home and then we"),
            ("00:00:01,600 --> 00:00:03,000", "and then we slept"),
            ("00:00:03,200 --> 00:00:04,000", "Good night"),
        ]

        self.assertEqual(
            self._correct_cues(cues, "We went home, and then we slept. Good night."),
            [
                ("00:00:00,100 --> 00:00:01,500", "We went home"),
                ("00:00:01,600 --> 00:00:03,000", "and then we slept"),
                ("00:00:03,200 --> 00:00:04,000", "Good night"),
            ],
        )

    def test_correct_keeps_a_cue_whose_last_word_has_an_extra_letter(self):
        """
        "Hello worlds" for "Hello world" ends with the first letter of the next
        line. That line has its own cue, so the cue is not cut before the "s".
        """
        cues = [
            ("00:00:00,100 --> 00:00:01,300", "Hello worlds"),
            ("00:00:01,700 --> 00:00:02,500", "So we went"),
        ]

        self.assertEqual(
            self._correct_cues(cues, "Hello world. So we went."),
            [
                ("00:00:00,100 --> 00:00:01,300", "Hello world"),
                ("00:00:01,700 --> 00:00:02,500", "So we went"),
            ],
        )

    def test_correct_keeps_a_cue_whose_extra_line_the_next_cue_repeats(self):
        """
        Whisper can also write the whole next line twice: at the end of a cue
        and as the next cue. The next line keeps its own cue.
        """
        cues = [
            ("00:00:00,100 --> 00:00:01,500", "We went home and then we slept"),
            ("00:00:01,600 --> 00:00:03,000", "and then we slept"),
            ("00:00:03,200 --> 00:00:04,000", "Good night"),
        ]

        self.assertEqual(
            self._correct_cues(cues, "We went home, and then we slept. Good night."),
            [
                ("00:00:00,100 --> 00:00:01,500", "We went home"),
                ("00:00:01,600 --> 00:00:03,000", "and then we slept"),
                ("00:00:03,200 --> 00:00:04,000", "Good night"),
            ],
        )

    def test_correct_keeps_a_cue_whose_extra_short_line_the_next_cue_repeats(self):
        """
        The script is split at every comma, so a line that Whisper writes twice
        can be two words long.
        """
        cues = [
            ("00:00:00,000 --> 00:00:01,500", "I opened the door and saw"),
            ("00:00:01,600 --> 00:00:02,200", "and saw"),
            ("00:00:02,500 --> 00:00:03,000", "Then left"),
        ]

        self.assertEqual(
            self._correct_cues(cues, "I opened the door, and saw. Then left."),
            [
                ("00:00:00,000 --> 00:00:01,500", "I opened the door"),
                ("00:00:01,600 --> 00:00:02,200", "and saw"),
                ("00:00:02,500 --> 00:00:03,000", "Then left"),
            ],
        )

    def test_correct_keeps_cues_when_a_line_written_twice_has_a_wrong_letter(self):
        """
        "Hello world" looks like "Hello" and the start of "world", but "wurld"
        is "world" again with one letter wrong. Cut, the first cue would give
        "world" 0.909-2 s, and "Next line" the cue "wurld" too, from 5 s.
        """
        cues = [
            ("00:00:00,000 --> 00:00:02,000", "Hello world"),
            ("00:00:05,000 --> 00:00:06,000", "wurld"),
            ("00:00:07,000 --> 00:00:08,000", "Next line"),
        ]

        self.assertEqual(
            self._correct_cues(cues, "Hello, world. Next line."),
            [
                ("00:00:00,000 --> 00:00:02,000", "Hello"),
                ("00:00:05,000 --> 00:00:06,000", "world"),
                ("00:00:07,000 --> 00:00:08,000", "Next line"),
            ],
        )

    def test_correct_keeps_cues_when_a_long_line_follows_a_line_written_twice(self):
        """
        As in the test above, but the line after the copy is long enough to
        start "wurld This is the next line of the script" as well. Cut, the
        first cue would give that line 5-9 s instead of its own cue at 7-9 s,
        so the cut is not used. The same with "nov" for "now", and in Chinese.
        """
        cases = [
            (
                "Hello, world. This is the next line of the script.",
                [
                    ("00:00:00,000 --> 00:00:02,000", "Hello world", "Hello"),
                    ("00:00:05,000 --> 00:00:06,000", "wurld", "world"),
                    (
                        "00:00:07,000 --> 00:00:09,000",
                        "This is the next line of the script",
                        "This is the next line of the script",
                    ),
                ],
            ),
            (
                "Okay, now. Let us look at an example.",
                [
                    ("00:00:00,000 --> 00:00:01,000", "Okay now", "Okay"),
                    ("00:00:01,200 --> 00:00:01,500", "nov", "now"),
                    (
                        "00:00:01,800 --> 00:00:04,000",
                        "Let us look at an example",
                        "Let us look at an example",
                    ),
                ],
            ),
            (
                "大家好，朋友。今天我们一起来做一顿简单的晚饭吧。",
                [
                    ("00:00:00,000 --> 00:00:02,000", "大家好朋友", "大家好"),
                    ("00:00:02,500 --> 00:00:03,200", "朋有", "朋友"),
                    (
                        "00:00:03,600 --> 00:00:07,000",
                        "今天我们一起来做一顿简单的晚饭吧",
                        "今天我们一起来做一顿简单的晚饭吧",
                    ),
                ],
            ),
        ]

        for script, cues in cases:
            with self.subTest(script=script):
                self.assertEqual(
                    self._correct_cues([(times, cue) for times, cue, _ in cues], script),
                    [(times, line) for times, _, line in cues],
                )

    def test_correct_keeps_the_transcription_when_a_cut_moves_a_matched_line(self):
        """
        With one more sentence, the cues run out without cuts, so the
        transcription is kept. With cuts, the cues would cover the script, but
        "This is the next line of the script" would get 5-9 s, as in the test
        above, so the transcription is still kept.
        """
        cues = [
            ("00:00:00,000 --> 00:00:02,000", "Hello world"),
            ("00:00:05,000 --> 00:00:06,000", "wurld"),
            ("00:00:07,000 --> 00:00:09,000", "This is the next line of the script"),
            ("00:00:09,500 --> 00:00:11,000", "And then we stop"),
        ]

        self.assertEqual(
            self._correct_cues(
                cues,
                "Hello, world. This is the next line of the script. And then, we stop.",
            ),
            cues,
        )

    def test_correct_keeps_cues_when_the_line_after_a_copy_has_more_in_its_cue(self):
        """
        As in the tests above, but the cue of the long line holds more than the
        line: the start of the last line, which the last cue has again, or two
        words that Whisper added. The long line is then 80% or less like its
        cue, but it starts it. Cut after "Hello", the first cue would give the
        long line the cue "wurld" too, from 5 s, and in Chinese, with "朋有" for
        "朋友", the cue "朋有" from 2.5 s. As on main, each line keeps its own cue.
        """
        cases = [
            (
                "Hello, world. This is the next line of the script, and then we stop.",
                [
                    ("00:00:00,000 --> 00:00:02,000", "Hello world", "Hello"),
                    ("00:00:05,000 --> 00:00:06,000", "wurld", "world"),
                    (
                        "00:00:07,000 --> 00:00:09,900",
                        "This is the next line of the script and then",
                        "This is the next line of the script",
                    ),
                    (
                        "00:00:10,200 --> 00:00:11,500",
                        "and then we stop",
                        "and then we stop",
                    ),
                ],
            ),
            (
                "大家好，朋友。今天我们一起来做一顿简单的晚饭吧，然后一起去公园散步。",
                [
                    ("00:00:00,000 --> 00:00:02,000", "大家好朋友", "大家好"),
                    ("00:00:02,500 --> 00:00:03,200", "朋有", "朋友"),
                    (
                        "00:00:03,600 --> 00:00:07,200",
                        "今天我们一起来做一顿简单的晚饭吧然后一起",
                        "今天我们一起来做一顿简单的晚饭吧",
                    ),
                    (
                        "00:00:07,400 --> 00:00:09,500",
                        "然后一起去公园散步",
                        "然后一起去公园散步",
                    ),
                ],
            ),
            (
                "Hello, world. This is the next line of the script.",
                [
                    ("00:00:00,000 --> 00:00:02,000", "Hello world", "Hello"),
                    ("00:00:05,000 --> 00:00:06,000", "wurld", "world"),
                    (
                        "00:00:07,000 --> 00:00:10,000",
                        "This is the next line of the script thank you",
                        "This is the next line of the script",
                    ),
                ],
            ),
        ]

        for script, cues in cases:
            with self.subTest(script=script):
                self.assertEqual(
                    self._correct_cues([(times, cue) for times, cue, _ in cues], script),
                    [(times, line) for times, _, line in cues],
                )

    def test_correct_keeps_the_transcription_when_a_cut_moves_a_line_onto_a_copy(self):
        """
        As in the first case of the test above, but Whisper also left out the
        comma after the long line, so its cue holds the last line too, and the
        cues run out without cuts. Cut after "Hello", the first cue would give
        "world" 0.909-2 s and the long line 5-9.692 s. As on main, the
        transcription is kept.
        """
        cues = [
            ("00:00:00,000 --> 00:00:02,000", "Hello world"),
            ("00:00:05,000 --> 00:00:06,000", "wurld"),
            (
                "00:00:07,000 --> 00:00:11,000",
                "This is the next line of the script and then we stop",
            ),
        ]

        self.assertEqual(
            self._correct_cues(
                cues,
                "Hello, world. This is the next line of the script, and then we stop.",
            ),
            cues,
        )

    def test_correct_keeps_cues_when_a_one_character_line_is_written_twice(self):
        """
        "出发吧走" looks like "出发吧" and the line "走", and "奏" can be "走"
        written again with one character wrong. A line of one character is one
        edit off any text, so "奏" does not count as a copy of it. Cut after
        "出发吧", the first cue would give the last line "奏" too, from 2 s, but
        that line starts its own cue, which holds two words that Whisper added,
        better. As on main, each line keeps its own cue.
        """
        cues = [
            ("00:00:00,000 --> 00:00:01,500", "出发吧走"),
            ("00:00:02,000 --> 00:00:02,400", "奏"),
            ("00:00:02,800 --> 00:00:06,000", "今天我们一起去公园散步就是说那个"),
        ]

        self.assertEqual(
            self._correct_cues(cues, "出发吧，走。今天我们一起去公园散步。"),
            [
                ("00:00:00,000 --> 00:00:01,500", "出发吧"),
                ("00:00:02,000 --> 00:00:02,400", "走"),
                ("00:00:02,800 --> 00:00:06,000", "今天我们一起去公园散步"),
            ],
        )

    def test_correct_keeps_cues_when_a_cut_leaves_cues_unused(self):
        """
        A Chinese cue can end inside a word. Cut after "今天天气很好", its rest "我"
        does not take in the next cue "们", so the last two lines would get
        2.571-3 s and 3-3.3 s, and the last two cues would be dropped.
        """
        cues = [
            ("00:00:00,000 --> 00:00:03,000", "今天天气很好我"),
            ("00:00:03,000 --> 00:00:03,300", "们"),
            ("00:00:03,300 --> 00:00:06,000", "去公园散步"),
            ("00:00:06,500 --> 00:00:08,000", "然后一起回家"),
        ]

        self.assertEqual(
            self._correct_cues(cues, "今天天气很好，我们去公园散步。然后一起回家。"),
            [
                ("00:00:00,000 --> 00:00:03,000", "今天天气很好"),
                ("00:00:03,000 --> 00:00:06,000", "我们去公园散步"),
                ("00:00:06,500 --> 00:00:08,000", "然后一起回家"),
            ],
        )

    def test_correct_keeps_a_cue_when_the_next_line_is_said_again(self):
        """
        The second line and the third are both "come here", so "come hare come
        here" starts each of them alike: the first cue can hold the first two
        lines, or Whisper wrote the second line twice. No cue is cut then. As on
        main, the two cues do not cover the three lines, so the transcription is
        kept. Cut, the first cue would give the second line 0.711-1.5 s; left
        whole, the last cue would be cut between the last two lines.
        """
        cues = [
            ("00:00:00,000 --> 00:00:01,500", "Come here come here"),
            ("00:00:01,600 --> 00:00:03,200", "come hare come here"),
        ]

        self.assertEqual(self._correct_cues(cues, "Come here, come here, come here."), cues)

    def test_correct_keeps_a_cue_when_the_line_after_next_starts_the_next_line(self):
        """
        "音乐" is the start of "音乐公园", so "音乐公园嗯音乐" starts both lines
        alike, and no cue is cut. Cut, the first cue would give "音乐公园"
        0.5-1 s and "音乐" the second cue. As on main, the two cues do not cover
        the three lines, so the transcription is kept.
        """
        cues = [
            ("00:00:00,000 --> 00:00:01,000", "问题方法音乐公园"),
            ("00:00:01,050 --> 00:00:02,400", "音乐公园嗯音乐"),
        ]

        self.assertEqual(self._correct_cues(cues, "问题方法，音乐公园，音乐。"), cues)

    def test_correct_keeps_a_cue_when_the_next_line_starts_the_line_after_it(self):
        """
        "run" is the start of "Run to the door", so the second cue starts both
        lines alike, and no cue is cut. Left whole, the first cue would move the
        two lines after it one cue late: "run" would get 1.2-2.2 s, where "Run to
        the door" is said, and "Run to the door" 2.4-3.426 s, where Whisper wrote
        it again before "now". As on main, the three cues do not cover the four
        lines, so the transcription is kept.
        """
        cues = [
            ("00:00:00,000 --> 00:00:00,800", "Run run"),
            ("00:00:01,200 --> 00:00:02,200", "Run to the door"),
            ("00:00:02,400 --> 00:00:03,700", "run to the door now"),
        ]

        self.assertEqual(self._correct_cues(cues, "Run, run. Run to the door. Now."), cues)

    def test_correct_keeps_a_cue_when_a_misheard_letter_could_tip_a_tie(self):
        """
        As in the test above, with "Run ran" for "Run, run.": "ran" is "run"
        with one letter wrong, so it can still be the second line, and no cue is
        cut. Left whole, the first cue would give "run" 1.2-2.2 s, where "Run to
        the door" is said, and "Run to the door" 2.4-3.426 s. As on main, the
        transcription is kept.
        """
        cues = [
            ("00:00:00,000 --> 00:00:00,800", "Run ran"),
            ("00:00:01,200 --> 00:00:02,200", "Run to the door"),
            ("00:00:02,400 --> 00:00:03,700", "run to the door now"),
        ]

        self.assertEqual(self._correct_cues(cues, "Run, run. Run to the door. Now."), cues)

    def test_correct_keeps_a_cue_when_the_next_cue_starts_two_lines_nearly_alike(self):
        """
        Whisper wrote the third line twice, each time with one character wrong:
        at the end of the first cue, and at the start of the second, before the
        last line "一次". The second cue starts the third line one character
        less well than "一次", so the first cue can hold the third line or a
        copy of it, and it is not cut after the second line. Cut, the third line
        would get 3.699-4.895 s, and "一次" the whole second cue from 4.903 s. As
        on main, the transcription is kept.
        """
        cues = [
            (
                "00:00:00,112 --> 00:00:04,895",
                "很好走吧快走对天气很好走吧快走后天气好的一公公园一次回家我们再的",
            ),
            ("00:00:04,903 --> 00:00:07,217", "一次好家我们再来一次"),
        ]

        self.assertEqual(
            self._correct_cues(
                cues,
                "很好走吧快走对天气，很好走吧快走对天气好的一起公园，一次回家我们再来，一次。",
            ),
            cues,
        )

    def test_file_to_subtitles_keeps_last_block_without_trailing_newline(self):
        """
        The final subtitle must be parsed even when the SRT file does not end
        with a trailing blank line. Many tools omit it, and previously the last
        block was silently dropped because only a blank line flushed a block.
        """
        srt_without_trailing_blank = (
            "1\n"
            "00:00:00,000 --> 00:00:01,000\n"
            "Hello\n\n"
            "2\n"
            "00:00:01,000 --> 00:00:02,000\n"
            "World"
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "subtitle.srt"
            subtitle_file.write_text(srt_without_trailing_blank, encoding="utf-8")

            items = subtitle.file_to_subtitles(str(subtitle_file))

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0][2], "Hello")
        self.assertEqual(items[1][2], "World")

    def test_file_to_subtitles_parses_blocks_with_trailing_newline(self):
        """A normal SRT ending in a blank line still parses all blocks."""
        srt_with_trailing_blank = (
            "1\n"
            "00:00:00,000 --> 00:00:01,000\n"
            "Hello\n\n"
            "2\n"
            "00:00:01,000 --> 00:00:02,000\n"
            "World\n\n"
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "subtitle.srt"
            subtitle_file.write_text(srt_with_trailing_blank, encoding="utf-8")

            items = subtitle.file_to_subtitles(str(subtitle_file))

        self.assertEqual([item[2] for item in items], ["Hello", "World"])

    def test_file_to_subtitles_preserves_timestamps_in_cue_text(self):
        """Timestamp examples in narration must not replace a cue's timing."""
        for text in (
            "Jump to 00:01:23,456 in the recording.",
            "00:01:23,456",
            "00:01:23,456 --> 00:01:24,000",
        ):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp_dir:
                subtitle_file = Path(tmp_dir) / "subtitle.srt"
                subtitle_file.write_text(
                    "1\n00:00:00,000 --> 00:00:02,000\n"
                    f"Timestamp example:\n{text}\nContinue watching.\n\n"
                    "2\n00:00:02,000 --> 00:00:03,000\nNext cue",
                    encoding="utf-8",
                )

                items = subtitle.file_to_subtitles(str(subtitle_file))

                self.assertEqual(
                    items,
                    [
                        (
                            1,
                            "00:00:00,000 --> 00:00:02,000",
                            f"Timestamp example:\n{text}\nContinue watching.",
                        ),
                        (2, "00:00:02,000 --> 00:00:03,000", "Next cue"),
                    ],
                )


if __name__ == "__main__":
    unittest.main()
