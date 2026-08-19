import os
import tempfile
import unittest
from datetime import timedelta
from types import SimpleNamespace

from app.services import subtitle, voice


def _cue(content: str, start: float, end: float):
    return SimpleNamespace(
        content=content, start=timedelta(seconds=start), end=timedelta(seconds=end)
    )


def _sub_maker(cues):
    return SimpleNamespace(cues=cues)


def _read_cues(path: str):
    """返回 [(text, start, end)]，便于断言分组和时间轴。"""
    entries = []
    for _, time_range, text in subtitle.file_to_subtitles(path):
        start, end = [part.strip() for part in time_range.split("-->")]
        entries.append((text, start, end))
    return entries


class WordLimitedSubtitleTest(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "subtitle.srt")

    def test_word_level_cues_keep_their_exact_timings(self):
        """每条 cue 一个词时不应引入任何估算，时间轴必须原样保留。"""
        cues = [
            _cue("Sunlight", 0.0, 1.0),
            _cue("looks", 1.0, 2.0),
            _cue("white", 2.0, 3.0),
            _cue("but", 3.0, 4.0),
        ]
        voice.create_subtitle(
            sub_maker=_sub_maker(cues), text="Sunlight looks white but",
            subtitle_file=self.path, max_words=3,
        )
        entries = _read_cues(self.path)
        self.assertEqual(entries[0][0], "Sunlight looks white")
        self.assertEqual(entries[0][1], "00:00:00,000")
        self.assertEqual(entries[0][2], "00:00:03,000")

    def test_never_exceeds_the_requested_word_count(self):
        cues = [_cue(f"word{index}", index, index + 1) for index in range(10)]
        voice.create_subtitle(
            sub_maker=_sub_maker(cues), text="x", subtitle_file=self.path, max_words=3
        )
        for text, _, _ in _read_cues(self.path):
            self.assertLessEqual(len(text.split()), 3)

    def test_trailing_words_are_not_dropped(self):
        """10 个词按 3 个一组，最后剩下的 1 个词也必须出现。"""
        cues = [_cue(f"word{index}", index, index + 1) for index in range(10)]
        voice.create_subtitle(
            sub_maker=_sub_maker(cues), text="x", subtitle_file=self.path, max_words=3
        )
        words = [word for text, _, _ in _read_cues(self.path) for word in text.split()]
        self.assertEqual(len(words), 10)
        self.assertEqual(words[-1], "word9")

    def test_sentence_level_cue_is_interpolated(self):
        """
        部分语音只返回整句边界。此时必须在句内插值，否则同一句的所有分组
        会共用起止时间，字幕在整句期间完全静止。
        """
        cues = [_cue("one two three four five six", 0.0, 6.0)]
        voice.create_subtitle(
            sub_maker=_sub_maker(cues), text="x", subtitle_file=self.path, max_words=3
        )
        entries = _read_cues(self.path)
        self.assertEqual(len(entries), 2)
        self.assertNotEqual(entries[0][2], entries[1][2])
        self.assertEqual(entries[0][1], "00:00:00,000")

    def test_cues_are_chronological_and_do_not_overlap(self):
        cues = [_cue("alpha beta gamma delta", 0.0, 4.0), _cue("epsilon", 4.0, 5.0)]
        voice.create_subtitle(
            sub_maker=_sub_maker(cues), text="x", subtitle_file=self.path, max_words=2
        )
        entries = _read_cues(self.path)
        for previous, current in zip(entries, entries[1:]):
            self.assertLessEqual(previous[2], current[1])

    def test_zero_keeps_punctuation_based_behaviour(self):
        """max_words=0 必须完全走原有路径，不能改变既有用户的字幕观感。"""
        cues = [_cue("Hello world.", 0.0, 2.0)]
        voice.create_subtitle(
            sub_maker=_sub_maker(cues), text="Hello world.",
            subtitle_file=self.path, max_words=0,
        )
        entries = _read_cues(self.path)
        self.assertEqual(len(entries), 1)
        self.assertIn("Hello world", entries[0][0])


class WhisperReChunkTest(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "subtitle.srt")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(
                "1\n00:00:00,000 --> 00:00:06,000\n"
                "one two three four five six\n\n"
                "2\n00:00:06,000 --> 00:00:08,000\nseven eight\n"
            )

    def test_existing_file_is_split_to_the_word_limit(self):
        self.assertTrue(subtitle.limit_words_per_cue(self.path, 3))
        entries = _read_cues(self.path)
        self.assertEqual([text for text, _, _ in entries][:2],
                         ["one two three", "four five six"])
        for text, _, _ in entries:
            self.assertLessEqual(len(text.split()), 3)

    def test_original_span_is_preserved(self):
        """重新切分不能改变整体时间范围，否则字幕会与配音脱节。"""
        subtitle.limit_words_per_cue(self.path, 3)
        entries = _read_cues(self.path)
        self.assertEqual(entries[0][1], "00:00:00,000")
        self.assertEqual(entries[-1][2], "00:00:08,000")

    def test_zero_is_a_no_op(self):
        before = open(self.path, encoding="utf-8").read()
        self.assertFalse(subtitle.limit_words_per_cue(self.path, 0))
        self.assertEqual(open(self.path, encoding="utf-8").read(), before)


if __name__ == "__main__":
    unittest.main()
