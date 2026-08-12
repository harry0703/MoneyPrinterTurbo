import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models.schema import VideoParams
from app.services import klipy, llm, task, video

SRT_SAMPLE = """1
00:00:00,000 --> 00:00:04,120
Ты смотришь на баланс и не понимаешь, куда ушли деньги.

2
00:00:04,120 --> 00:00:09,400
Кофе, доставка, подписки.

3
00:00:09,400 --> 00:00:14,000
За год это превращается в сумму, от которой больно.
"""


class TestGifMomentNormalization(unittest.TestCase):
    def test_drops_out_of_range_and_duplicate_indexes(self):
        """
        模型可能返回越界或重复的行号，直接使用会错位叠加甚至抛出索引异常。
        """
        parsed = [
            {"index": 0, "query": "confused math lady"},
            {"index": 0, "query": "duplicate"},
            {"index": 9, "query": "out of range"},
            {"index": -1, "query": "negative"},
            {"index": 2, "query": "mind blown"},
        ]
        moments = llm._normalize_gif_moments(parsed, line_count=3, amount=5)

        self.assertEqual(
            moments,
            [
                {"index": 0, "query": "confused math lady"},
                {"index": 2, "query": "mind blown"},
            ],
        )

    def test_drops_entries_without_query(self):
        parsed = [
            {"index": 0, "query": "   "},
            {"index": 1},
            {"index": 2, "query": "ok"},
        ]
        moments = llm._normalize_gif_moments(parsed, line_count=3, amount=5)

        self.assertEqual(moments, [{"index": 2, "query": "ok"}])

    def test_respects_requested_amount(self):
        parsed = [{"index": i, "query": f"q{i}"} for i in range(6)]
        moments = llm._normalize_gif_moments(parsed, line_count=6, amount=2)

        self.assertEqual([m["index"] for m in moments], [0, 1])

    def test_non_list_response_is_rejected(self):
        self.assertEqual(llm._normalize_gif_moments({"index": 0}, 3, 5), [])

    def test_empty_subtitle_lines_skip_the_llm_call(self):
        with patch("app.services.llm._generate_response") as mocked:
            self.assertEqual(llm.generate_gif_moments([], amount=5), [])
        mocked.assert_not_called()


class TestSubtitleWindows(unittest.TestCase):
    def test_parses_srt_into_seconds(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            srt_path = os.path.join(tmp_dir, "subtitle.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(SRT_SAMPLE)

            windows = task._subtitle_windows(srt_path)

        self.assertEqual(len(windows), 3)
        self.assertAlmostEqual(windows[0][0][0], 0.0)
        self.assertAlmostEqual(windows[0][0][1], 4.12)
        self.assertAlmostEqual(windows[2][0][0], 9.4)
        self.assertIn("Кофе", windows[1][1])

    def test_skips_lines_with_broken_timing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            srt_path = os.path.join(tmp_dir, "subtitle.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write("1\n00:00:05,000 --> 00:00:02,000\nend before start\n\n")

            self.assertEqual(task._subtitle_windows(srt_path), [])

    def test_srt_time_to_seconds(self):
        self.assertAlmostEqual(task._srt_time_to_seconds("01:02:03,500"), 3723.5)


class TestGifOverlayLayout(unittest.TestCase):
    def setUp(self):
        self.params = VideoParams(video_subject="test")
        self.params.gif_size = 0.42
        self.params.subtitle_enabled = True
        self.params.subtitle_position = "bottom"

    def test_box_keeps_source_aspect_ratio(self):
        clip = SimpleNamespace(w=640, h=408)
        width, height = video._gif_overlay_box(clip, 1080, 1920, 0.42)

        self.assertEqual(width, 453)
        self.assertAlmostEqual(width / height, 640 / 408, places=1)

    def test_tall_gif_is_capped_by_height(self):
        """
        竖版动图如果按宽度缩放，会盖住画面主体甚至压到字幕区域。
        """
        clip = SimpleNamespace(w=200, h=900)
        width, height = video._gif_overlay_box(clip, 1080, 1920, 0.8)

        self.assertLessEqual(height, int(1920 * 0.45))
        self.assertAlmostEqual(width / height, 200 / 900, places=1)

    def _place(self, index, seed="gif.mp4", box_height=289):
        return video._gif_overlay_placement(
            index=index,
            seed=seed,
            box_height=box_height,
            video_width=1080,
            video_height=1920,
            params=self.params,
        )

    def test_overlay_avoids_the_subtitle_band(self):
        _, center_y, _ = self._place(0)

        self.assertLess(center_y + 289 / 2, int(1920 * 0.95))

    def test_overlay_moves_down_when_subtitles_are_on_top(self):
        self.params.subtitle_position = "top"
        _, top_y, _ = self._place(0)

        self.params.subtitle_position = "bottom"
        _, bottom_y, _ = self._place(0)

        self.assertGreater(top_y, bottom_y)

    def test_overlay_stays_inside_the_frame(self):
        _, center_y, _ = self._place(0, box_height=860)
        x, y = video._centered_position(200, center_y, 1000, 860, 1080, 1920)

        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + 1000, 1080)
        self.assertLessEqual(y + 860, 1920)

    def test_consecutive_overlays_alternate_sides(self):
        """
        всё в одной точке смотрится мёртво: соседние вставки должны уходить
        в разные стороны от центра.
        """
        first_x, _, first_angle = self._place(0)
        second_x, _, second_angle = self._place(1)

        self.assertLess(first_x, 1080 / 2)
        self.assertGreater(second_x, 1080 / 2)
        self.assertLess(first_angle * second_angle, 0)

    def test_tilt_leans_towards_the_frame_centre(self):
        """
        Rotate() крутит против часовой на положительном угле, поэтому карточка
        слева от центра должна получить отрицательный угол.
        """
        left_x, _, left_angle = self._place(0)
        right_x, _, right_angle = self._place(1)

        self.assertLess(left_x, 540)
        self.assertLess(left_angle, 0)
        self.assertGreater(right_x, 540)
        self.assertGreater(right_angle, 0)

    def test_tilt_stays_within_a_readable_range(self):
        for index in range(8):
            _, _, angle = self._place(index, seed=f"gif-{index}.mp4")
            self.assertGreaterEqual(abs(angle), video._GIF_TILT_RANGE[0])
            self.assertLessEqual(abs(angle), video._GIF_TILT_RANGE[1])

    def test_placement_is_deterministic_for_the_same_gif(self):
        """
        повторный рендер той же задачи обязан давать ту же раскладку,
        иначе перегенерация ролика молча меняет картинку.
        """
        self.assertEqual(self._place(2, seed="a.mp4"), self._place(2, seed="a.mp4"))

    def test_different_gifs_get_different_offsets(self):
        offsets = {self._place(0, seed=f"gif-{i}.mp4")[0] for i in range(6)}

        self.assertGreater(len(offsets), 1)

    def test_vertical_jitter_varies_between_overlays(self):
        heights = {self._place(i, seed=f"gif-{i}.mp4")[1] for i in range(6)}

        self.assertGreater(len(heights), 1)


class TestGifOverlayPipeline(unittest.TestCase):
    def setUp(self):
        self.params = VideoParams(video_subject="test")
        self.params.gif_enabled = True
        self.params.gif_amount = 2
        self.params.video_aspect = "9:16"

    def test_disabled_flag_skips_every_external_call(self):
        self.params.gif_enabled = False
        with (
            patch("app.services.llm.generate_gif_moments") as mocked_llm,
            patch("app.services.klipy.fetch_gif") as mocked_fetch,
        ):
            overlays = task.generate_gif_overlays("t", self.params, "script", None, "")

        self.assertEqual(overlays, [])
        mocked_llm.assert_not_called()
        mocked_fetch.assert_not_called()

    def test_missing_api_key_does_not_fail_the_task(self):
        """
        用户没有配置 KLIPY Key 时，整条视频任务必须继续，只是没有动图。
        """
        windows = [((0.0, 4.0), "line one"), ((4.0, 9.0), "line two")]
        with (
            patch("app.services.task._gif_timeline", return_value=windows),
            patch(
                "app.services.llm.generate_gif_moments",
                return_value=[{"index": 0, "query": "mind blown"}],
            ),
            patch(
                "app.services.klipy.fetch_gif", side_effect=ValueError("key is not set")
            ),
        ):
            overlays = task.generate_gif_overlays("t", self.params, "script", None, "")

        self.assertEqual(overlays, [])

    def test_overlays_inherit_subtitle_timings(self):
        windows = [((0.0, 4.0), "line one"), ((4.0, 9.0), "line two")]
        gif = klipy.GifInfo(
            slug="s", title="t", url="/tmp/gif.mp4", width=480, height=270
        )
        with (
            patch("app.services.task._gif_timeline", return_value=windows),
            patch(
                "app.services.llm.generate_gif_moments",
                return_value=[{"index": 1, "query": "mind blown"}],
            ),
            patch("app.services.klipy.fetch_gif", return_value=gif),
        ):
            overlays = task.generate_gif_overlays("t", self.params, "script", None, "")

        self.assertEqual(len(overlays), 1)
        self.assertEqual(overlays[0]["start"], 4.0)
        self.assertEqual(overlays[0]["end"], 9.0)
        self.assertEqual(overlays[0]["path"], "/tmp/gif.mp4")

    def test_same_gif_is_not_reused_across_moments(self):
        windows = [((0.0, 4.0), "one"), ((4.0, 9.0), "two")]
        seen_excludes = []

        def fake_fetch(query, min_width, rating, exclude_slugs):
            seen_excludes.append(set(exclude_slugs))
            return klipy.GifInfo(
                slug=f"slug-{len(seen_excludes)}",
                title="t",
                url="/tmp/gif.mp4",
                width=480,
                height=270,
            )

        with (
            patch("app.services.task._gif_timeline", return_value=windows),
            patch(
                "app.services.llm.generate_gif_moments",
                return_value=[
                    {"index": 0, "query": "a"},
                    {"index": 1, "query": "b"},
                ],
            ),
            patch("app.services.klipy.fetch_gif", side_effect=fake_fetch),
        ):
            overlays = task.generate_gif_overlays("t", self.params, "script", None, "")

        self.assertEqual(len(overlays), 2)
        self.assertEqual(seen_excludes[1], {"slug-1"})

    def test_missing_gif_file_is_skipped_when_building_clips(self):
        with patch("app.services.video._open_video_clip_quietly") as mocked_open:
            clips = video._build_gif_overlay_clips(
                [{"path": "/does/not/exist.mp4", "start": 0.0, "end": 3.0}],
                video_width=1080,
                video_height=1920,
                params=self.params,
                clip_stack=SimpleNamespace(enter_context=lambda x: x),
            )

        self.assertEqual(clips, [])
        mocked_open.assert_not_called()


if __name__ == "__main__":
    unittest.main()
