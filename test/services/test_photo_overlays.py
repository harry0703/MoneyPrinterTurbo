import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from PIL import Image

from app.models.schema import VideoParams
from app.services import llm, task, video


def _make_photo_dir(tmp_dir: str, names: list[str]) -> str:
    photo_dir = os.path.join(tmp_dir, "photos")
    os.makedirs(photo_dir)
    for name in names:
        file_path = os.path.join(photo_dir, name)
        if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            Image.new("RGB", (64, 40), (200, 30, 30)).save(file_path)
        else:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("not a photo")
    return photo_dir


class TestPhotoMomentNormalization(unittest.TestCase):
    def test_drops_out_of_range_and_duplicate_indexes(self):
        parsed = [0, 0, 9, -1, 2]
        self.assertEqual(llm._normalize_photo_moments(parsed, 3, 5), [0, 2])

    def test_accepts_dict_entries_with_index_key(self):
        parsed = [{"index": 1}, {"index": "2"}, {"query": "no index"}]
        self.assertEqual(llm._normalize_photo_moments(parsed, 3, 5), [1, 2])

    def test_respects_requested_amount(self):
        self.assertEqual(llm._normalize_photo_moments(list(range(6)), 6, 2), [0, 1])

    def test_non_list_response_is_rejected(self):
        self.assertEqual(llm._normalize_photo_moments({"index": 0}, 3, 5), [])

    def test_empty_subtitle_lines_skip_the_llm_call(self):
        with patch("app.services.llm._generate_response") as mocked:
            self.assertEqual(llm.generate_photo_moments([], amount=5), [])
        mocked.assert_not_called()

    def test_parses_plain_json_array_response(self):
        lines = [((0.0, 2.0), "one"), ((2.0, 4.0), "two"), ((4.0, 6.0), "three")]
        with patch("app.services.llm._generate_response", return_value="[0, 2]"):
            self.assertEqual(llm.generate_photo_moments(lines, amount=5), [0, 2])


class TestPhotoFileDiscovery(unittest.TestCase):
    def test_missing_dir_returns_empty_list(self):
        self.assertEqual(task._list_photo_files("/does/not/exist"), [])
        self.assertEqual(task._list_photo_files(""), [])

    def test_filters_extensions_and_sorts_by_name(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            photo_dir = _make_photo_dir(
                tmp_dir, ["b.png", "a.jpg", "c.webp", "notes.txt"]
            )
            files = task._list_photo_files(photo_dir)

        self.assertEqual(
            [os.path.basename(f) for f in files], ["a.jpg", "b.png", "c.webp"]
        )


class TestPhotoPreflight(unittest.TestCase):
    def setUp(self):
        self.params = VideoParams(video_subject="test")

    def test_disabled_feature_passes(self):
        self.params.photo_enabled = False
        self.assertIsNone(task._validate_photo_overlay_params(self.params))

    def test_empty_dir_setting_fails(self):
        self.params.photo_enabled = True
        self.params.photo_dir = ""
        self.assertIsNotNone(task._validate_photo_overlay_params(self.params))

    def test_missing_dir_fails(self):
        self.params.photo_enabled = True
        self.params.photo_dir = "/does/not/exist"
        self.assertIsNotNone(task._validate_photo_overlay_params(self.params))

    def test_dir_without_photos_fails(self):
        self.params.photo_enabled = True
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.params.photo_dir = _make_photo_dir(tmp_dir, ["notes.txt"])
            self.assertIsNotNone(task._validate_photo_overlay_params(self.params))

    def test_dir_with_photos_passes(self):
        self.params.photo_enabled = True
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.params.photo_dir = _make_photo_dir(tmp_dir, ["a.jpg"])
            self.assertIsNone(task._validate_photo_overlay_params(self.params))


class TestPhotoMomentSpread(unittest.TestCase):
    def test_spread_covers_the_script_evenly(self):
        indexes = task._spread_photo_moments(10, 3)

        self.assertEqual(len(indexes), 3)
        self.assertEqual(indexes, sorted(set(indexes)))
        self.assertTrue(all(0 <= i < 10 for i in indexes))

    def test_single_photo_lands_in_the_middle(self):
        self.assertEqual(task._spread_photo_moments(10, 1), [5])

    def test_amount_is_capped_by_window_count(self):
        indexes = task._spread_photo_moments(2, 5)
        self.assertTrue(all(0 <= i < 2 for i in indexes))


class TestPhotoSelection(unittest.TestCase):
    def test_all_photos_are_used_when_they_fit(self):
        photos = ["a.jpg", "b.jpg"]
        self.assertEqual(task._select_photos(photos, 5), photos)

    def test_sampling_spans_the_whole_directory(self):
        photos = [f"{i:02d}.jpg" for i in range(20)]
        picked = task._select_photos(photos, 4)

        self.assertEqual(len(picked), 4)
        self.assertEqual(picked[0], "00.jpg")
        self.assertGreaterEqual(picked[-1], "15.jpg")

    def test_sampling_keeps_order_and_uniqueness(self):
        photos = [f"{i:02d}.jpg" for i in range(9)]
        picked = task._select_photos(photos, 5)

        self.assertEqual(picked, sorted(set(picked)))


class TestPhotoOverlayPipeline(unittest.TestCase):
    def setUp(self):
        self.params = VideoParams(video_subject="test")
        self.params.photo_enabled = True
        self.params.photo_amount = 5
        self.windows = [
            ((0.0, 4.0), "line one"),
            ((4.0, 9.0), "line two"),
            ((9.0, 12.0), "line three"),
        ]
        theme_plan = patch(
            "app.services.llm.generate_photo_theme_plan", return_value=[]
        )
        self.addCleanup(theme_plan.stop)
        self.mocked_theme_plan = theme_plan.start()

    def test_disabled_flag_skips_every_external_call(self):
        self.params.photo_enabled = False
        with patch("app.services.llm.generate_photo_moments") as mocked_llm:
            overlays = task.generate_photo_overlays("t", self.params, "s", None, "")

        self.assertEqual(overlays, [])
        mocked_llm.assert_not_called()

    def test_empty_photo_dir_skips_the_llm_call(self):
        self.params.photo_dir = "/does/not/exist"
        with patch("app.services.llm.generate_photo_moments") as mocked_llm:
            overlays = task.generate_photo_overlays("t", self.params, "s", None, "")

        self.assertEqual(overlays, [])
        mocked_llm.assert_not_called()

    def test_overlays_start_at_the_picked_line(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.params.photo_dir = _make_photo_dir(tmp_dir, ["a.jpg", "b.jpg"])
            with (
                patch("app.services.task._gif_timeline", return_value=self.windows),
                patch("app.services.llm.generate_photo_moments", return_value=[0, 2]),
            ):
                overlays = task.generate_photo_overlays("t", self.params, "s", None, "")

        self.assertEqual(len(overlays), 2)
        self.assertEqual(overlays[0]["start"], 0.0)
        self.assertEqual(overlays[1]["start"], 9.0)
        self.assertTrue(overlays[0]["path"].endswith("a.jpg"))
        self.assertTrue(overlays[1]["path"].endswith("b.jpg"))

    def test_display_duration_stays_in_the_configured_burst(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.params.photo_dir = _make_photo_dir(tmp_dir, ["a.jpg"])
            with (
                patch("app.services.task._gif_timeline", return_value=self.windows),
                patch("app.services.llm.generate_photo_moments", return_value=[1]),
            ):
                overlays = task.generate_photo_overlays("t", self.params, "s", None, "")

        duration = overlays[0]["end"] - overlays[0]["start"]
        self.assertGreaterEqual(
            duration, self.params.photo_duration - task._PHOTO_DISPLAY_JITTER
        )
        self.assertLessEqual(
            duration, self.params.photo_duration + task._PHOTO_DISPLAY_JITTER
        )

    def test_display_duration_follows_the_configured_value(self):
        self.params.photo_duration = 4.0
        long_windows = [((0.0, 20.0), "only line")]
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.params.photo_dir = _make_photo_dir(tmp_dir, ["a.jpg"])
            with (
                patch("app.services.task._gif_timeline", return_value=long_windows),
                patch("app.services.llm.generate_photo_moments", return_value=[0]),
            ):
                overlays = task.generate_photo_overlays("t", self.params, "s", None, "")

        duration = overlays[0]["end"] - overlays[0]["start"]
        self.assertGreaterEqual(duration, 3.5)
        self.assertLessEqual(duration, 4.5)

    def test_overlays_never_run_at_the_same_time(self):
        self.params.photo_duration = 3.0
        dense_windows = [((float(i), float(i) + 1.0), f"line {i}") for i in range(10)]
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.params.photo_dir = _make_photo_dir(
                tmp_dir, ["a.jpg", "b.jpg", "c.jpg"]
            )
            with (
                patch("app.services.task._gif_timeline", return_value=dense_windows),
                patch(
                    "app.services.llm.generate_photo_moments", return_value=[0, 1, 2]
                ),
            ):
                overlays = task.generate_photo_overlays("t", self.params, "s", None, "")

        self.assertEqual(len(overlays), 3)
        for earlier, later in zip(overlays, overlays[1:]):
            self.assertGreaterEqual(later["start"], earlier["end"])

    def test_dense_picks_stay_on_their_own_line(self):
        self.params.photo_duration = 3.0
        dense_windows = [((float(i), float(i) + 1.0), f"line {i}") for i in range(10)]
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.params.photo_dir = _make_photo_dir(
                tmp_dir, ["a.jpg", "b.jpg", "c.jpg"]
            )
            with (
                patch("app.services.task._gif_timeline", return_value=dense_windows),
                patch(
                    "app.services.llm.generate_photo_moments", return_value=[0, 2, 4]
                ),
            ):
                overlays = task.generate_photo_overlays("t", self.params, "s", None, "")

        self.assertEqual([o["start"] for o in overlays], [0.0, 2.0, 4.0])
        self.assertEqual([o["end"] for o in overlays[:2]], [2.0, 4.0])
        self.assertGreaterEqual(overlays[2]["end"], 6.5)

    def test_picks_too_close_together_are_dropped(self):
        self.params.photo_duration = 3.0
        crowded = [((0.0, 5.0), "one"), ((0.5, 5.0), "two"), ((6.0, 12.0), "three")]
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.params.photo_dir = _make_photo_dir(
                tmp_dir, ["a.jpg", "b.jpg", "c.jpg"]
            )
            with (
                patch("app.services.task._gif_timeline", return_value=crowded),
                patch(
                    "app.services.llm.generate_photo_moments", return_value=[0, 1, 2]
                ),
            ):
                overlays = task.generate_photo_overlays("t", self.params, "s", None, "")

        self.assertEqual([o["start"] for o in overlays], [0.5, 6.0])

    def test_unsorted_llm_moments_stay_chronological(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.params.photo_dir = _make_photo_dir(tmp_dir, ["a.jpg", "b.jpg"])
            with (
                patch("app.services.task._gif_timeline", return_value=self.windows),
                patch("app.services.llm.generate_photo_moments", return_value=[2, 0]),
            ):
                overlays = task.generate_photo_overlays("t", self.params, "s", None, "")

        self.assertEqual([o["start"] for o in overlays], [0.0, 9.0])

    def test_display_window_is_clamped_to_the_timeline_end(self):
        short_windows = [((0.0, 1.0), "only line")]
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.params.photo_dir = _make_photo_dir(tmp_dir, ["a.jpg"])
            with (
                patch("app.services.task._gif_timeline", return_value=short_windows),
                patch("app.services.llm.generate_photo_moments", return_value=[0]),
            ):
                overlays = task.generate_photo_overlays("t", self.params, "s", None, "")

        self.assertEqual(overlays[0]["end"], 1.0)

    def test_llm_failure_falls_back_to_even_spread(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.params.photo_dir = _make_photo_dir(tmp_dir, ["a.jpg", "b.jpg"])
            with (
                patch("app.services.task._gif_timeline", return_value=self.windows),
                patch("app.services.llm.generate_photo_moments", return_value=[]),
            ):
                overlays = task.generate_photo_overlays("t", self.params, "s", None, "")

        self.assertEqual(len(overlays), 2)

    def test_amount_is_capped_by_available_photos(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.params.photo_dir = _make_photo_dir(tmp_dir, ["a.jpg"])
            with (
                patch("app.services.task._gif_timeline", return_value=self.windows),
                patch(
                    "app.services.llm.generate_photo_moments", return_value=[0]
                ) as mocked_llm,
            ):
                overlays = task.generate_photo_overlays("t", self.params, "s", None, "")

        self.assertEqual(len(overlays), 1)
        self.assertEqual(mocked_llm.call_args.kwargs["amount"], 1)


class TestPhotoThemePlanning(unittest.TestCase):
    def setUp(self):
        self.params = VideoParams(video_subject="test")
        self.params.photo_enabled = True
        self.params.photo_amount = 5
        self.windows = [
            ((0.0, 4.0), "about the film"),
            ((4.0, 9.0), "about the actor"),
            ((9.0, 14.0), "about the film again"),
        ]

    def _themed_dir(self, tmp_dir: str) -> str:
        return _make_photo_dir(
            tmp_dir, ["10-film-00.jpg", "10-film-01.jpg", "20-actor-00.jpg"]
        )

    def test_photos_follow_the_matched_theme(self):
        plan = [{"line": 0, "theme": "film"}, {"line": 1, "theme": "actor"}]
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.params.photo_dir = self._themed_dir(tmp_dir)
            with (
                patch("app.services.task._gif_timeline", return_value=self.windows),
                patch("app.services.llm.generate_photo_theme_plan", return_value=plan),
                patch("app.services.llm.generate_photo_moments") as mocked_moments,
            ):
                overlays = task.generate_photo_overlays("t", self.params, "s", None, "")

        self.assertEqual(
            [os.path.basename(o["path"]) for o in overlays],
            ["10-film-00.jpg", "20-actor-00.jpg"],
        )
        self.assertEqual(overlays[0]["start"], 0.0)
        mocked_moments.assert_not_called()

    def test_repeated_theme_walks_through_its_pool(self):
        plan = [{"line": 0, "theme": "film"}, {"line": 2, "theme": "film"}]
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.params.photo_dir = self._themed_dir(tmp_dir)
            with (
                patch("app.services.task._gif_timeline", return_value=self.windows),
                patch("app.services.llm.generate_photo_theme_plan", return_value=plan),
            ):
                overlays = task.generate_photo_overlays("t", self.params, "s", None, "")

        self.assertEqual(
            [os.path.basename(o["path"]) for o in overlays],
            ["10-film-00.jpg", "10-film-01.jpg"],
        )

    def test_exhausted_theme_wraps_instead_of_borrowing_another(self):
        plan = [
            {"line": 0, "theme": "actor"},
            {"line": 1, "theme": "actor"},
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.params.photo_dir = self._themed_dir(tmp_dir)
            with (
                patch("app.services.task._gif_timeline", return_value=self.windows),
                patch("app.services.llm.generate_photo_theme_plan", return_value=plan),
            ):
                overlays = task.generate_photo_overlays("t", self.params, "s", None, "")

        self.assertEqual(
            [os.path.basename(o["path"]) for o in overlays],
            ["20-actor-00.jpg", "20-actor-00.jpg"],
        )

    def test_empty_plan_falls_back_to_line_moments(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.params.photo_dir = self._themed_dir(tmp_dir)
            with (
                patch("app.services.task._gif_timeline", return_value=self.windows),
                patch("app.services.llm.generate_photo_theme_plan", return_value=[]),
                patch(
                    "app.services.llm.generate_photo_moments", return_value=[1]
                ) as mocked_moments,
            ):
                overlays = task.generate_photo_overlays("t", self.params, "s", None, "")

        mocked_moments.assert_called_once()
        self.assertEqual(len(overlays), 1)
        self.assertEqual(overlays[0]["start"], 4.0)

    def test_single_theme_directory_skips_theme_matching(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.params.photo_dir = _make_photo_dir(tmp_dir, ["film-00.jpg"])
            with (
                patch("app.services.task._gif_timeline", return_value=self.windows),
                patch("app.services.llm.generate_photo_theme_plan") as mocked_plan,
                patch("app.services.llm.generate_photo_moments", return_value=[0]),
            ):
                overlays = task.generate_photo_overlays("t", self.params, "s", None, "")

        mocked_plan.assert_not_called()
        self.assertEqual(len(overlays), 1)

    def test_themes_are_described_to_the_llm(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.params.photo_dir = self._themed_dir(tmp_dir)
            with (
                patch("app.services.task._gif_timeline", return_value=self.windows),
                patch(
                    "app.services.llm.generate_photo_theme_plan", return_value=[]
                ) as mocked_plan,
                patch("app.services.llm.generate_photo_moments", return_value=[0]),
            ):
                task.generate_photo_overlays("t", self.params, "s", None, "")

        themes = mocked_plan.call_args.kwargs["themes"]
        self.assertEqual([theme["name"] for theme in themes], ["film", "actor"])
        self.assertEqual(themes[0]["samples"], ["10-film-00.jpg", "10-film-01.jpg"])


class TestPhotoThemePlanNormalization(unittest.TestCase):
    def test_unknown_themes_and_repeated_lines_are_dropped(self):
        parsed = [
            {"line": 1, "theme": "film"},
            {"line": 1, "theme": "actor"},
            {"line": 2, "theme": "nothing"},
            {"line": 9, "theme": "film"},
        ]
        plan = llm._normalize_photo_theme_plan(parsed, 3, ["film", "actor"], 5)

        self.assertEqual(plan, [{"line": 1, "theme": "film"}])

    def test_theme_names_match_case_insensitively(self):
        plan = llm._normalize_photo_theme_plan(
            [{"line": 0, "theme": " FILM "}], 2, ["film"], 5
        )

        self.assertEqual(plan, [{"line": 0, "theme": "film"}])

    def test_plan_is_sorted_and_capped(self):
        parsed = [{"line": i, "theme": "film"} for i in (4, 0, 2)]
        plan = llm._normalize_photo_theme_plan(parsed, 5, ["film"], 2)

        self.assertEqual([entry["line"] for entry in plan], [0, 2])

    def test_non_list_response_is_rejected(self):
        self.assertEqual(
            llm._normalize_photo_theme_plan({"line": 0}, 3, ["film"], 5), []
        )

    def test_missing_themes_skip_the_llm_call(self):
        with patch("app.services.llm._generate_response") as mocked:
            self.assertEqual(
                llm.generate_photo_theme_plan([((0.0, 1.0), "line")], [], amount=3), []
            )
        mocked.assert_not_called()

    def test_parses_plain_json_response(self):
        lines = [((0.0, 2.0), "one"), ((2.0, 4.0), "two")]
        themes = [{"name": "film", "description": "movie stills"}]
        with patch(
            "app.services.llm._generate_response",
            return_value='[{"line": 1, "theme": "film"}]',
        ):
            plan = llm.generate_photo_theme_plan(lines, themes, amount=3)

        self.assertEqual(plan, [{"line": 1, "theme": "film"}])


class TestPhotoAnimationChoice(unittest.TestCase):
    def setUp(self):
        self.params = VideoParams(video_subject="test")

    def test_explicit_animation_is_honoured(self):
        self.params.photo_animation = "slide"
        self.assertEqual(video._pick_photo_animation("a.jpg", self.params), "slide")

    def test_random_choice_is_deterministic_per_photo(self):
        self.params.photo_animation = "random"
        first = video._pick_photo_animation("a.jpg", self.params)
        second = video._pick_photo_animation("a.jpg", self.params)

        self.assertEqual(first, second)
        self.assertIn(first, video._PHOTO_ANIMATIONS)

    def test_random_choice_varies_between_photos(self):
        self.params.photo_animation = "random"
        picks = {
            video._pick_photo_animation(f"photo-{i}.jpg", self.params)
            for i in range(12)
        }

        self.assertGreater(len(picks), 1)

    def test_unknown_value_falls_back_to_random(self):
        self.params.photo_animation = "spiral"
        self.assertIn(
            video._pick_photo_animation("a.jpg", self.params),
            video._PHOTO_ANIMATIONS,
        )


class TestPhotoCardImage(unittest.TestCase):
    def test_card_includes_the_shadow_margin(self):
        photo = Image.new("RGB", (64, 40), (10, 120, 200))
        card = video._photo_card_image(
            photo, box_width=400, box_height=250, radius=20, spread=12, angle=0
        )

        self.assertEqual(card.mode, "RGBA")
        self.assertEqual(card.size, (400 + 24, 250 + 24))

    def test_tilted_card_expands(self):
        photo = Image.new("RGB", (64, 40), (10, 120, 200))
        flat = video._photo_card_image(photo, 400, 250, 20, 12, angle=0)
        tilted = video._photo_card_image(photo, 400, 250, 20, 12, angle=4.0)

        self.assertGreater(tilted.width, flat.width)
        self.assertGreater(tilted.height, flat.height)

    def test_corners_are_transparent(self):
        photo = Image.new("RGB", (64, 40), (10, 120, 200))
        card = video._photo_card_image(photo, 400, 250, 30, 0, angle=0)

        self.assertEqual(card.getpixel((0, 0))[3], 0)
        self.assertGreater(card.getpixel((200, 125))[3], 0)


class TestPhotoOverlayClips(unittest.TestCase):
    def setUp(self):
        self.params = VideoParams(video_subject="test")
        self.params.photo_size = 0.42
        self.clip_stack = SimpleNamespace(
            enter_context=lambda x: x, callback=lambda *a, **k: None
        )

    def _build(self, animation: str, tmp_dir: str):
        self.params.photo_animation = animation
        photo_path = os.path.join(tmp_dir, "a.jpg")
        Image.new("RGB", (64, 40), (200, 30, 30)).save(photo_path)
        return video._build_photo_overlay_clips(
            [{"path": photo_path, "start": 2.0, "end": 4.0}],
            video_width=1080,
            video_height=1920,
            params=self.params,
            clip_stack=self.clip_stack,
        )

    def test_missing_photo_file_is_skipped(self):
        clips = video._build_photo_overlay_clips(
            [{"path": "/does/not/exist.jpg", "start": 0.0, "end": 3.0}],
            video_width=1080,
            video_height=1920,
            params=self.params,
            clip_stack=self.clip_stack,
        )

        self.assertEqual(clips, [])

    def test_pop_animation_builds_a_single_card_clip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            clips = self._build("pop", tmp_dir)

            self.assertEqual(len(clips), 1)
            self.assertEqual(clips[0].start, 2.0)
            # Rendering a frame exercises the resize/position lambdas.
            frame = clips[0].get_frame(0.1)
            self.assertEqual(len(frame.shape), 3)

    def test_slide_animation_starts_off_screen(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            clips = self._build("slide", tmp_dir)

            self.assertEqual(len(clips), 1)
            start_x = clips[0].pos(0)[0]
            settled_x = clips[0].pos(1.0)[0]
            self.assertNotEqual(start_x, settled_x)
            self.assertEqual(clips[0].pos(1.0), clips[0].pos(1.5))

    def test_kenburns_animation_builds_shadow_and_card(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            clips = self._build("kenburns", tmp_dir)

            self.assertEqual(len(clips), 2)
            frame = clips[1].get_frame(0.5)
            self.assertEqual(len(frame.shape), 3)

    def test_broken_photo_does_not_take_the_render_down(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            broken_path = os.path.join(tmp_dir, "broken.jpg")
            with open(broken_path, "w", encoding="utf-8") as f:
                f.write("not an image")

            clips = video._build_photo_overlay_clips(
                [{"path": broken_path, "start": 0.0, "end": 3.0}],
                video_width=1080,
                video_height=1920,
                params=self.params,
                clip_stack=self.clip_stack,
            )

        self.assertEqual(clips, [])


if __name__ == "__main__":
    unittest.main()
