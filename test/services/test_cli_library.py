import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import cli
from app.services.asset_embed import TextEmbedding
from app.services.asset_library import Asset, AssetTag, IngestResult, LibrarySummary
from app.services.asset_retrieval import ScoredCandidate
from app.services.asset_vision import AssetAnnotation


def _asset(**overrides) -> Asset:
    defaults = dict(
        id=1,
        sha256="a" * 64,
        rel_path="misc/photo.jpg",
        width=1080,
        height=1920,
        caption="a caption",
        origin="manual",
        tags=[AssetTag(tag="misc", weight=1.0, manual=True)],
    )
    defaults.update(overrides)
    return Asset(**defaults)


class TestCliLibraryRouting(unittest.TestCase):
    def test_library_argv_routes_to_library_cli(self):
        with (
            patch("cli.run_library_cli", return_value=0) as run_library,
            patch("cli.parse_args") as parse_args,
        ):
            code = cli.run_cli(["library", "stats"])

        self.assertEqual(code, 0)
        run_library.assert_called_once_with(["stats"])
        parse_args.assert_not_called()

    def test_non_library_argv_routes_to_flat_parser(self):
        with (
            patch("cli.run_library_cli") as run_library,
            patch("app.services.task.start", return_value={"script": "ok"}),
            patch("app.utils.utils.get_uuid", return_value="task-123"),
            patch("builtins.print"),
        ):
            code = cli.run_cli(["--video-subject", "test", "--stop-at", "script"])

        self.assertEqual(code, 0)
        run_library.assert_not_called()

    def test_library_routing_uses_sys_argv_when_argv_is_none(self):
        with (
            patch.object(sys, "argv", ["cli.py", "library", "list"]),
            patch("cli.run_library_cli", return_value=0) as run_library,
        ):
            code = cli.run_cli()

        self.assertEqual(code, 0)
        run_library.assert_called_once_with(["list"])


class TestCliLibraryEnablement(unittest.TestCase):
    def test_disabled_library_is_a_clean_argument_error(self):
        with (
            patch("app.services.asset_library.is_enabled", return_value=False),
            patch.object(cli.logger, "error") as log_error,
        ):
            code = cli.run_library_cli(["stats"])

        self.assertEqual(code, 2)
        log_error.assert_called_once()
        self.assertIn("disabled", str(log_error.call_args))


class TestCliLibraryAdd(unittest.TestCase):
    def test_add_file_applies_manual_tags_and_reports_creation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            photo = Path(tmp_dir) / "photo.jpg"
            photo.write_bytes(b"fake-image")

            created_asset = _asset(id=7, rel_path="manual/photo.jpg")
            with (
                patch("app.services.asset_library.is_enabled", return_value=True),
                patch("app.services.asset_library.init_library") as init_library,
                patch(
                    "app.services.asset_library.ingest_file",
                    return_value=IngestResult(asset=created_asset, created=True),
                ) as ingest_file,
                redirect_stdout(io.StringIO()) as out,
            ):
                code = cli.run_library_cli(
                    [
                        "add",
                        str(photo),
                        "--tags",
                        "beach, sunset",
                        "--caption",
                        "a beach",
                        "--min-display",
                        "3.5",
                        "--group",
                        "vacation",
                    ]
                )

        self.assertEqual(code, 0)
        init_library.assert_called_once()
        ingest_file.assert_called_once_with(
            str(photo),
            group="vacation",
            tags=["beach", "sunset"],
            caption="a beach",
            min_display=3.5,
        )
        self.assertIn("created id=7", out.getvalue())

    def test_add_file_default_group_when_omitted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            photo = Path(tmp_dir) / "photo.jpg"
            photo.write_bytes(b"fake-image")

            with (
                patch("app.services.asset_library.is_enabled", return_value=True),
                patch("app.services.asset_library.init_library"),
                patch(
                    "app.services.asset_library.ingest_file",
                    return_value=IngestResult(asset=_asset(), created=False),
                ) as ingest_file,
                redirect_stdout(io.StringIO()) as out,
            ):
                code = cli.run_library_cli(["add", str(photo)])

        self.assertEqual(code, 0)
        self.assertEqual(ingest_file.call_args.kwargs["group"], "manual")
        self.assertIn("exists id=", out.getvalue())

    def test_add_directory_ingests_recursively_and_ignores_group(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            results = [
                IngestResult(asset=_asset(id=1), created=True),
                IngestResult(asset=_asset(id=2), created=False),
            ]
            with (
                patch("app.services.asset_library.is_enabled", return_value=True),
                patch("app.services.asset_library.init_library"),
                patch(
                    "app.services.asset_library.ingest_directory",
                    return_value=results,
                ) as ingest_directory,
                redirect_stdout(io.StringIO()) as out,
            ):
                code = cli.run_library_cli(
                    ["add", tmp_dir, "--tags", "beach", "--group", "ignored"]
                )

        self.assertEqual(code, 0)
        ingest_directory.assert_called_once_with(
            tmp_dir, tags=["beach"], caption=None, min_display=None
        )
        output = out.getvalue()
        self.assertIn("created id=1", output)
        self.assertIn("exists id=2", output)
        self.assertIn("ingested 2 file(s): 1 created, 1 already existed", output)

    def test_add_rejects_nonexistent_path_as_argument_error(self):
        with patch("app.services.asset_library.is_enabled", return_value=True):
            with self.assertRaises(SystemExit) as cm:
                cli.run_library_cli(["add", "/does/not/exist"])
        self.assertEqual(cm.exception.code, 2)


class TestCliLibraryListTagRm(unittest.TestCase):
    def test_list_filters_by_tags_and_formats_fields(self):
        assets = [
            _asset(
                id=3,
                caption="a dog",
                has_text=False,
                min_display=2.5,
                tags=[AssetTag(tag="dog", weight=0.9, manual=True)],
            )
        ]
        with (
            patch("app.services.asset_library.is_enabled", return_value=True),
            patch(
                "app.services.asset_library.list_assets", return_value=assets
            ) as list_assets,
            redirect_stdout(io.StringIO()) as out,
        ):
            code = cli.run_library_cli(["list", "--tags", "dog,cat"])

        self.assertEqual(code, 0)
        list_assets.assert_called_once_with(any_tags=["dog", "cat"])
        output = out.getvalue()
        self.assertIn("id=3", output)
        self.assertIn("caption=a dog", output)
        self.assertIn("has_text=False", output)
        self.assertIn("min_display=2.5", output)
        self.assertIn("tags=[dog]", output)

    def test_list_reports_no_assets(self):
        with (
            patch("app.services.asset_library.is_enabled", return_value=True),
            patch("app.services.asset_library.list_assets", return_value=[]),
            redirect_stdout(io.StringIO()) as out,
        ):
            code = cli.run_library_cli(["list"])

        self.assertEqual(code, 0)
        self.assertIn("no assets found", out.getvalue())

    def test_tag_replaces_manual_tags(self):
        with (
            patch("app.services.asset_library.is_enabled", return_value=True),
            patch("app.services.asset_library.get_asset", return_value=_asset(id=5)),
            patch("app.services.asset_library.set_tags") as set_tags,
            redirect_stdout(io.StringIO()) as out,
        ):
            code = cli.run_library_cli(["tag", "5", "--tags", "beach,sunset"])

        self.assertEqual(code, 0)
        set_tags.assert_called_once_with(5, ["beach", "sunset"], manual=True)
        self.assertIn("tagged id=5", out.getvalue())

    def test_tag_missing_asset_is_an_argument_error(self):
        with (
            patch("app.services.asset_library.is_enabled", return_value=True),
            patch("app.services.asset_library.get_asset", return_value=None),
            patch.object(cli.logger, "error") as log_error,
        ):
            code = cli.run_library_cli(["tag", "99", "--tags", "beach"])

        self.assertEqual(code, 2)
        log_error.assert_called_once()

    def test_rm_deletes_existing_asset(self):
        with (
            patch("app.services.asset_library.is_enabled", return_value=True),
            patch("app.services.asset_library.delete_asset", return_value=True),
            redirect_stdout(io.StringIO()) as out,
        ):
            code = cli.run_library_cli(["rm", "5"])

        self.assertEqual(code, 0)
        self.assertIn("deleted id=5", out.getvalue())

    def test_rm_missing_asset_is_an_argument_error(self):
        with (
            patch("app.services.asset_library.is_enabled", return_value=True),
            patch("app.services.asset_library.delete_asset", return_value=False),
            patch.object(cli.logger, "error") as log_error,
        ):
            code = cli.run_library_cli(["rm", "99"])

        self.assertEqual(code, 2)
        log_error.assert_called_once()


class TestCliLibraryStats(unittest.TestCase):
    def test_stats_prints_totals_and_tag_breakdown(self):
        summary = LibrarySummary(
            total=10,
            without_annotation=2,
            without_embedding=3,
            tags={"dog": 4, "cat": 6},
        )
        with (
            patch("app.services.asset_library.is_enabled", return_value=True),
            patch("app.services.asset_library.summary", return_value=summary),
            redirect_stdout(io.StringIO()) as out,
        ):
            code = cli.run_library_cli(["stats"])

        self.assertEqual(code, 0)
        output = out.getvalue()
        self.assertIn("total=10", output)
        self.assertIn("without_annotation=2", output)
        self.assertIn("without_embedding=3", output)
        self.assertIn("cat: 6", output)


class TestCliLibraryBackfill(unittest.TestCase):
    def test_backfill_only_processes_assets_missing_annotation_or_embedding(self):
        annotate_target = _asset(id=1, caption="")
        embed_target = _asset(id=2, caption="already annotated")
        annotation = AssetAnnotation(
            caption="a dog on a beach",
            tags={"dog": 0.8, "beach": 0.4},
            has_text=False,
            min_display=2.0,
            model="gemini-2.5-flash",
        )
        embedding = TextEmbedding(vector=[0.1] * 768, model="gemini-embedding-001")

        with (
            patch("app.services.asset_library.is_enabled", return_value=True),
            patch(
                "app.services.asset_library.assets_missing_annotation",
                return_value=[annotate_target],
            ) as missing_annotation,
            patch(
                "app.services.asset_library.assets_missing_embedding",
                return_value=[embed_target],
            ) as missing_embedding,
            patch("app.services.asset_library.asset_path", return_value="/lib/1.jpg"),
            patch(
                "app.services.asset_vision.annotate_image", return_value=annotation
            ) as annotate_image,
            patch("app.services.asset_library.save_annotation") as save_annotation,
            patch(
                "app.services.asset_embed.embed_text", return_value=embedding
            ) as embed_text,
            patch("app.services.asset_library.save_embedding") as save_embedding,
            redirect_stdout(io.StringIO()) as out,
        ):
            code = cli.run_library_cli(["backfill", "--limit", "10"])

        self.assertEqual(code, 0)
        missing_annotation.assert_called_once_with(limit=10)
        missing_embedding.assert_called_once_with(limit=10)
        annotate_image.assert_called_once_with("/lib/1.jpg")
        save_annotation.assert_called_once()
        self.assertEqual(save_annotation.call_args.kwargs["model"], "gemini-2.5-flash")
        tag_args = save_annotation.call_args.kwargs["tags"]
        self.assertEqual(
            {t.tag: t.weight for t in tag_args}, {"dog": 0.8, "beach": 0.4}
        )
        embed_text.assert_called_once_with("already annotated")
        save_embedding.assert_called_once_with(
            2, embedding.vector, model=embedding.model
        )
        self.assertIn("backfill done: 1 annotated, 1 embedded", out.getvalue())

    def test_backfill_continues_after_a_single_asset_failure(self):
        first = _asset(id=1)
        second = _asset(id=2)
        annotation = AssetAnnotation(
            caption="cat",
            tags={"cat": 0.5},
            has_text=False,
            min_display=1.5,
            model="gemini-2.5-flash",
        )

        with (
            patch("app.services.asset_library.is_enabled", return_value=True),
            patch(
                "app.services.asset_library.assets_missing_annotation",
                return_value=[first, second],
            ),
            patch(
                "app.services.asset_library.assets_missing_embedding", return_value=[]
            ),
            patch("app.services.asset_library.asset_path", return_value="/lib/x.jpg"),
            patch(
                "app.services.asset_vision.annotate_image",
                side_effect=[RuntimeError("boom"), annotation],
            ),
            patch("app.services.asset_library.save_annotation") as save_annotation,
            patch.object(cli.logger, "warning") as log_warning,
            redirect_stdout(io.StringIO()) as out,
        ):
            code = cli.run_library_cli(["backfill"])

        self.assertEqual(code, 0)
        log_warning.assert_called_once()
        save_annotation.assert_called_once()
        self.assertEqual(save_annotation.call_args.args[0], 2)
        self.assertIn("backfill done: 1 annotated, 0 embedded", out.getvalue())


class TestCliLibraryCalibrate(unittest.TestCase):
    def _candidates(self) -> list:
        # Distinct digits per field so a dropped column can't hide behind a
        # coincidentally matching substring from another field.
        asset_a = _asset(id=10)
        asset_b = _asset(id=11)
        return [
            ScoredCandidate(
                asset=asset_a,
                cosine=0.811,
                tag_score=0.522,
                recency_penalty=0.133,
                score=0.744,
            ),
            ScoredCandidate(
                asset=asset_b,
                cosine=0.422,
                tag_score=0.211,
                recency_penalty=0.011,
                score=0.400,
            ),
        ]

    def test_calibrate_prints_score_breakdown_for_a_plain_text_script(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            script = Path(tmp_dir) / "script.txt"
            script.write_text("first line\nsecond line\n", encoding="utf-8")

            briefs = [{"index": 0, "brief": "собака на пляже"}]
            with (
                patch("app.services.asset_library.is_enabled", return_value=True),
                patch(
                    "app.services.llm.generate_photo_briefs", return_value=briefs
                ) as generate_briefs,
                patch(
                    "app.services.asset_retrieval.rank_candidates",
                    return_value=self._candidates(),
                ) as rank_candidates,
                patch(
                    "app.services.asset_retrieval.score_verdict",
                    side_effect=["accept", "gray"],
                ),
                redirect_stdout(io.StringIO()) as out,
            ):
                code = cli.run_library_cli(
                    [
                        "calibrate",
                        "--script",
                        str(script),
                        "--subject",
                        "test video",
                        "--top",
                        "5",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertTrue(generate_briefs.called)
        subject_arg, lines_arg, amount_arg = generate_briefs.call_args.args[:3]
        self.assertEqual(subject_arg, "test video")
        self.assertEqual([line[1] for line in lines_arg], ["first line", "second line"])
        self.assertEqual(amount_arg, 5)
        rank_candidates.assert_called_once_with("собака на пляже", limit=5)

        output = out.getvalue()
        self.assertIn("cosine", output)
        self.assertIn("tag", output)
        self.assertIn("recency", output)
        self.assertIn("score", output)
        self.assertIn("verdict", output)
        self.assertIn("accept", output)
        self.assertIn("gray", output)
        # Every scored component must reach stdout individually, not just the
        # column headers, so a dropped field fails this test.
        self.assertIn("0.811", output)
        self.assertIn("0.522", output)
        self.assertIn("0.133", output)
        self.assertIn("0.744", output)
        self.assertIn("0.422", output)
        self.assertIn("0.211", output)
        self.assertIn("0.011", output)
        self.assertIn("0.400", output)
        self.assertIn("margin(top1-top2)=0.344", output)

    def test_calibrate_parses_srt_script_via_subtitle_module(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            script = Path(tmp_dir) / "script.srt"
            script.write_text("placeholder", encoding="utf-8")

            srt_entries = [
                (1, "00:00:00,000 --> 00:00:02,000", "первая строка"),
                (2, "00:00:02,000 --> 00:00:04,000", "вторая строка"),
            ]
            with (
                patch("app.services.asset_library.is_enabled", return_value=True),
                patch(
                    "app.services.subtitle.file_to_subtitles", return_value=srt_entries
                ) as file_to_subtitles,
                patch(
                    "app.services.llm.generate_photo_briefs", return_value=[]
                ) as generate_briefs,
                redirect_stdout(io.StringIO()) as out,
            ):
                code = cli.run_library_cli(["calibrate", "--script", str(script)])

        self.assertEqual(code, 0)
        file_to_subtitles.assert_called_once_with(str(script))
        lines_arg = generate_briefs.call_args.args[1]
        self.assertEqual(
            [line[1] for line in lines_arg], ["первая строка", "вторая строка"]
        )
        self.assertEqual(lines_arg[0][0], (0.0, 2.0))
        self.assertIn("no visual briefs were generated", out.getvalue())


if __name__ == "__main__":
    unittest.main()
