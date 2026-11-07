import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models.schema import MaterialInfo, TaskVideoRequest, VideoAspect, VideoParams
from app.models.scene_quality import MediaQualityReport
from app.models.video_plan import Scene, SceneTiming, Shot, VideoPlan, VisualBrief
from app.services import material, scene_media


def make_scene(scene_id="scene-001", order=0, subject="Saturn"):
    return Scene(
        scene_id=scene_id,
        order=order,
        narration_text=f"{subject} is known for its visible rings.",
        timing=SceneTiming(estimated_duration_ms=5000, confidence=0.8),
        visual=VisualBrief(
            subject=[subject],
            action="rotates with its rings visible",
            context="outer solar system",
            description=f"A close view of {subject} and its rings against dark space.",
            shot_type="close_up",
            visual_prompt=f"Documentary video of {subject} and its rings",
            search_queries=[f"{subject} rings close up", f"{subject} planet in space"],
            recommended_material_type=["stock_video"],
            avoid=["galaxies", "nebulae"],
        ),
        shots=[Shot(shot_id=f"{scene_id}-shot-001")],
    )


def make_plan(scenes=None):
    scenes = scenes or [make_scene()]
    return VideoPlan(
        plan_id="plan-test-123456",
        script_sha256=hashlib.sha256("test script".encode()).hexdigest(),
        subject="Astronomy",
        language="en",
        scenes=scenes,
    )


def candidate(provider="pexels", asset_id="saturn-1", query="Saturn rings close up", url=None):
    return MaterialInfo(
        provider=provider,
        url=url or f"https://cdn.example.test/{asset_id}.mp4",
        duration=12,
        source_info={
            "provider": provider,
            "search_term": query,
            "asset_id": asset_id,
            "source_page": f"https://example.test/{asset_id}",
            "rendition": {"width": 1920, "height": 1080},
        },
    )


def visual_assessment(description, *, subject=True, action=True, context=True, confidence=0.92, observations=None):
    import json

    return json.dumps(
        {
            "subject_visible": subject,
            "action_matches": action,
            "context_matches": context,
            "confidence": confidence,
            "description": description,
            "mismatch_reasons": [],
            "observations": observations or [
                {
                    "position": position,
                    "subject_visible": subject,
                    "action_matches": action,
                    "context_matches": context,
                    "description": description,
                }
                for position in ("beginning", "middle", "end")
            ],
            "temporal_consistency": confidence,
            "technical_quality": 0.9,
        }
    )


class TestSceneMedia(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.task_dir_patch = patch(
            "app.services.scene_media.utils.task_dir",
            return_value=str(self.temp_path),
        )
        self.task_dir_patch.start()
        self.quality_patch = patch.object(
            scene_media.scene_quality,
            "inspect_media_file",
            side_effect=lambda file_path, **_kwargs: MediaQualityReport(
                asset_sha256=hashlib.sha256(str(file_path).encode()).hexdigest(),
                media_type="video",
                result="accepted",
                duration_seconds=12,
                width=1920,
                height=1080,
                resolution_score=1,
                aspect_score=1,
                technical_quality=1,
            ),
        )
        self.quality_patch.start()

    def tearDown(self):
        self.task_dir_patch.stop()
        self.quality_patch.stop()
        self.temp_dir.cleanup()

    def test_search_queries_include_specific_scene_context(self):
        scene = make_scene()
        queries = scene_media._queries_for_scene(scene, 8)

        self.assertIn("Saturn rings close up", queries)
        self.assertIn("Saturn rotates with its rings visible", queries)
        self.assertTrue(all("Saturn" in query for query in queries))

    def test_astronomy_subjects_require_the_named_object(self):
        samples = (
            ("Sun", "The Sun shines as a star."),
            ("Jupiter", "Jupiter appears with its cloud bands."),
            ("Saturn", "Saturn and its rings are visible."),
            ("Mars", "The surface of Mars appears in the frame."),
            ("Voyager probes", "Voyager 1 is traveling beyond the heliosphere."),
            ("Oort cloud", "The Oort cloud surrounds the distant solar system."),
        )
        for order, (subject, visible_description) in enumerate(samples):
            with self.subTest(subject=subject):
                scene = make_scene(f"scene-{order + 1:03d}", order, subject)
                self.assertTrue(scene_media._subject_match(visible_description, scene))
                self.assertFalse(
                    scene_media._subject_match("A spiral galaxy fills the view.", scene)
                )

    def test_existing_stock_provider_adapter_maps_all_supported_sources(self):
        expected = ["pexels", "pixabay", "coverr"]
        with patch.object(material, "_search_videos_with_cache", return_value=[]) as cached:
            for provider in expected:
                self.assertEqual(
                    material.search_stock_videos(
                        provider, "Saturn rings", 1, VideoAspect.landscape
                    ),
                    [],
                )
                self.assertEqual(cached.call_args.kwargs["provider"], provider)
            with self.assertRaises(ValueError):
                material.search_stock_videos("wavespeed", "Saturn rings", 1)

    def test_duplicate_query_results_are_collapsed_and_audited(self):
        item = candidate()
        ranked = scene_media._build_candidates(
            make_scene(),
            [("pexels", "Saturn rings close up", item), ("pexels", "Saturn planet", item)],
            VideoAspect.landscape,
            8,
        )

        self.assertEqual(len(ranked), 1)
        self.assertEqual(
            ranked[0][2].matched_queries,
            ["Saturn rings close up", "Saturn planet"],
        )

    def test_all_configured_stock_sources_are_eligible(self):
        with patch.object(
            scene_media.config,
            "app",
            {
                "pexels_api_keys": ["pexels-key"],
                "pixabay_api_keys": ["pixabay-key"],
                "coverr_api_keys": ["coverr-key"],
            },
        ):
            self.assertEqual(
                scene_media._configured_providers(), ["pexels", "pixabay", "coverr"]
            )

    def test_search_failure_in_one_provider_does_not_block_other_providers(self):
        def search(provider, _query, _minimum, _aspect):
            if provider == "pexels":
                raise RuntimeError("provider offline")
            return [candidate("pixabay")]

        with (
            patch.object(scene_media, "_configured_providers", return_value=["pexels", "pixabay"]),
            patch.object(
                scene_media.material,
                "search_stock_videos",
                side_effect=search,
            ),
            patch.object(
                scene_media.task_artifacts,
                "read_scene_media_manifest",
                return_value=None,
            ),
            patch.object(scene_media.task_artifacts, "write_scene_media_manifest") as write,
        ):
            manifest = scene_media.select_plan_materials("task-search-fallback", make_plan())

        assignment = manifest.assignments[0]
        self.assertEqual(assignment.status, "pending_review")
        self.assertEqual(assignment.candidates[0].provider, "pixabay")
        self.assertTrue(any("pexels" in error for error in assignment.provider_errors))
        write.assert_called_once()

    def test_no_visual_evaluation_never_claims_or_selects_a_visual_match(self):
        with (
            patch.object(scene_media, "_configured_providers", return_value=["pexels"]),
            patch.object(scene_media.material, "search_stock_videos", return_value=[candidate()]),
            patch.object(scene_media.twelvelabs, "analyze_clip") as analyze,
            patch.object(
                scene_media.task_artifacts,
                "read_scene_media_manifest",
                return_value=None,
            ),
            patch.object(scene_media.task_artifacts, "write_scene_media_manifest"),
        ):
            manifest = scene_media.select_plan_materials("task-no-qa", make_plan())

        assignment = manifest.assignments[0]
        self.assertEqual(assignment.status, "pending_review")
        self.assertIsNone(assignment.selected_candidate)
        self.assertEqual(assignment.candidates[0].visual_validation, "not_requested")
        self.assertIsNone(assignment.candidates[0].scores.visual_subject_match)
        analyze.assert_not_called()

    def test_visual_subject_validation_selects_specific_candidate_and_downloads_it(self):
        irrelevant = candidate(asset_id="galaxy-2", query="Saturn rings close up")
        relevant = candidate(asset_id="saturn-rings-3", query="Saturn planet in space")

        def search(_provider, query, _minimum, _aspect):
            return [irrelevant] if "close up" in query else [relevant]

        with (
            patch.object(scene_media, "_configured_providers", return_value=["pexels"]),
            patch.object(scene_media.material, "search_stock_videos", side_effect=search),
            patch.object(scene_media.twelvelabs, "is_enabled", return_value=True),
            patch.object(
                scene_media.twelvelabs,
                "analyze_clip",
                side_effect=lambda url, **_kwargs: (
                    visual_assessment(
                        "A spiral galaxy fills the view.",
                        subject=False,
                        action=False,
                        context=False,
                    )
                    if "galaxy" in url
                    else visual_assessment("Saturn and its rings rotate in space.")
                ),
            ),
            patch.object(
                scene_media.material,
                "save_video",
                return_value=str(self.temp_path / "saturn.mp4"),
            ) as save,
            patch.object(
                scene_media.utils,
                "storage_dir",
                return_value=str(self.temp_path / "cache_videos"),
            ),
            patch.object(
                scene_media.task_artifacts,
                "read_scene_media_manifest",
                return_value=None,
            ),
            patch.object(scene_media.task_artifacts, "write_scene_media_manifest"),
        ):
            manifest = scene_media.select_plan_materials(
                "task-visual-qa", make_plan(), video_aspect="16:9", visual_validation=True
            )

        assignment = manifest.assignments[0]
        self.assertEqual(assignment.status, "selected")
        self.assertEqual(assignment.selected_candidate.original_asset_id, "saturn-rings-3")
        self.assertEqual(assignment.selected_candidate.visual_validation, "passed")
        self.assertEqual(assignment.selected_candidate.local_path, "saturn.mp4")
        self.assertTrue(
            any(
                "required subject" in reason
                for item in assignment.candidates
                for reason in item.discard_reasons
            )
        )
        save.assert_called_once_with(relevant.url, str(self.temp_path / "cache_videos"))

    def test_same_resource_is_not_assigned_to_multiple_scenes(self):
        plan = make_plan([make_scene(), make_scene("scene-002", 1, "Jupiter")])
        with (
            patch.object(scene_media, "_configured_providers", return_value=["pexels"]),
            patch.object(
                scene_media.material,
                "search_stock_videos",
                return_value=[candidate(url="https://cdn.example.test/shared.mp4")],
            ),
            patch.object(scene_media.twelvelabs, "is_enabled", return_value=True),
            patch.object(
                scene_media.twelvelabs,
                "analyze_clip",
                return_value=visual_assessment(
                    "Saturn and Jupiter are visible with planetary rings."
                ),
            ),
            patch.object(
                scene_media.material,
                "save_video",
                return_value=str(self.temp_path / "shared.mp4"),
            ),
            patch.object(
                scene_media.utils,
                "storage_dir",
                return_value=str(self.temp_path / "cache_videos"),
            ),
            patch.object(
                scene_media.task_artifacts,
                "read_scene_media_manifest",
                return_value=None,
            ),
            patch.object(scene_media.task_artifacts, "write_scene_media_manifest"),
        ):
            manifest = scene_media.select_plan_materials(
                "task-dedupe", plan, visual_validation=True
            )

        self.assertEqual(manifest.assignments[0].status, "selected")
        self.assertEqual(manifest.assignments[1].status, "pending_review")
        self.assertEqual(
            manifest.assignments[1].candidates[0].duplicate_of,
            "scene-001",
        )

    def test_semantically_wrong_candidates_remain_pending_without_download(self):
        with (
            patch.object(scene_media, "_configured_providers", return_value=["pexels"]),
            patch.object(scene_media.material, "search_stock_videos", return_value=[candidate()]),
            patch.object(scene_media.twelvelabs, "is_enabled", return_value=True),
            patch.object(
                scene_media.twelvelabs,
                "analyze_clip",
                return_value=visual_assessment(
                    "Saturn is visible without the requested close ring view.",
                    subject=True,
                    action=False,
                    context=False,
                ),
            ),
            patch.object(scene_media.material, "save_video") as save,
            patch.object(
                scene_media.task_artifacts,
                "read_scene_media_manifest",
                return_value=None,
            ),
            patch.object(scene_media.task_artifacts, "write_scene_media_manifest"),
        ):
            manifest = scene_media.select_plan_materials(
                "task-wrong-visual", make_plan(), visual_validation=True
            )

        assignment = manifest.assignments[0]
        self.assertEqual(assignment.status, "pending_review")
        self.assertEqual(assignment.candidates[0].visual_validation, "mismatched")
        self.assertIsNone(assignment.selected_candidate)
        self.assertIn(
            "visual analysis did not confirm the requested action",
            assignment.candidates[0].discard_reasons,
        )
        save.assert_not_called()

    def test_coverr_candidate_is_not_auto_downloaded_for_visual_validation(self):
        with (
            patch.object(scene_media, "_configured_providers", return_value=["coverr"]),
            patch.object(
                scene_media.material,
                "search_stock_videos",
                return_value=[candidate("coverr")],
            ),
            patch.object(scene_media.twelvelabs, "is_enabled", return_value=True),
            patch.object(
                scene_media.twelvelabs,
                "analyze_clip",
                return_value=visual_assessment("Saturn and its rings rotate in space."),
            ),
            patch.object(scene_media.material, "save_video") as save,
            patch.object(
                scene_media.task_artifacts,
                "read_scene_media_manifest",
                return_value=None,
            ),
            patch.object(scene_media.task_artifacts, "write_scene_media_manifest"),
        ):
            manifest = scene_media.select_plan_materials(
                "task-coverr-license", make_plan(), visual_validation=True
            )

        self.assertEqual(manifest.assignments[0].status, "pending_review")
        self.assertTrue(
            any(
                "license download event" in reason
                for reason in manifest.assignments[0].candidates[0].discard_reasons
            )
        )
        save.assert_not_called()

    def test_pegasus_is_not_called_for_local_or_subsecond_video_urls(self):
        for url, duration in (
            ("file:///tmp/video.mp4", 8),
            ("https://cdn.example.test/short.mp4", 0.5),
        ):
            with self.subTest(url=url, duration=duration):
                item = candidate(url=url)
                item.duration = duration
                with (
                    patch.object(scene_media, "_configured_providers", return_value=["pexels"]),
                    patch.object(scene_media.material, "search_stock_videos", return_value=[item]),
                    patch.object(scene_media.twelvelabs, "is_enabled", return_value=True),
                    patch.object(scene_media.twelvelabs, "analyze_clip") as analyze,
                    patch.object(
                        scene_media.task_artifacts,
                        "read_scene_media_manifest",
                        return_value=None,
                    ),
                    patch.object(scene_media.task_artifacts, "write_scene_media_manifest"),
                ):
                    result = scene_media.select_plan_materials(
                        f"task-pegasus-limit-{duration}",
                        make_plan(),
                        visual_validation=True,
                    )

                self.assertEqual(result.assignments[0].status, "pending_review")
                analyze.assert_not_called()

    def test_validation_requested_without_twelvelabs_key_stays_pending(self):
        with (
            patch.object(scene_media, "_configured_providers", return_value=["pexels"]),
            patch.object(scene_media.material, "search_stock_videos", return_value=[candidate()]),
            patch.object(scene_media.twelvelabs, "is_enabled", return_value=False),
            patch.object(scene_media.twelvelabs, "analyze_clip") as analyze,
            patch.object(
                scene_media.task_artifacts,
                "read_scene_media_manifest",
                return_value=None,
            ),
            patch.object(scene_media.task_artifacts, "write_scene_media_manifest"),
        ):
            manifest = scene_media.select_plan_materials(
                "task-no-twelvelabs", make_plan(), visual_validation=True
            )

        self.assertEqual(manifest.assignments[0].status, "pending_review")
        self.assertIn("TwelveLabs is not configured", manifest.assignments[0].warnings[0])
        analyze.assert_not_called()

    def test_paid_video_sources_are_not_called_as_implicit_fallbacks(self):
        with (
            patch.object(scene_media, "_configured_providers", return_value=[]),
            patch.object(scene_media.material, "search_stock_videos") as stock,
            patch.object(scene_media.material, "generate_videos_wavespeed") as wavespeed,
            patch.object(scene_media.material, "generate_images_openai") as image_gen,
                    patch.object(
                        scene_media.task_artifacts,
                        "read_scene_media_manifest",
                        return_value=None,
                    ),
            patch.object(scene_media.task_artifacts, "write_scene_media_manifest"),
        ):
            result = scene_media.select_plan_materials(
                "task-no-paid-fallback", make_plan()
            )

        self.assertEqual(result.assignments[0].status, "no_candidates")
        stock.assert_not_called()
        wavespeed.assert_not_called()
        image_gen.assert_not_called()

    def test_retrying_one_scene_preserves_other_assignments_and_increments_attempt(self):
        plan = make_plan([make_scene(), make_scene("scene-002", 1, "Jupiter")])
        old_manifest = scene_media.SceneMediaManifest(
            plan_id=plan.plan_id,
            script_sha256=plan.script_sha256,
            assignments=[
                scene_media.SceneMediaAssignment(
                    scene_id="scene-001",
                    status="no_candidates",
                    search_queries=["prior Saturn search"],
                    warnings=["old result"],
                    attempts=2,
                ),
                scene_media.SceneMediaAssignment(
                    scene_id="scene-002",
                    status="pending_review",
                    warnings=["preserve this"],
                ),
            ],
        )
        with (
            patch.object(scene_media, "_configured_providers", return_value=[]),
            patch.object(
                scene_media.task_artifacts,
                "read_scene_media_manifest",
                return_value=old_manifest.model_dump(mode="json"),
            ),
            patch.object(scene_media.task_artifacts, "write_scene_media_manifest"),
        ):
            manifest = scene_media.select_plan_materials(
                "task-retry", plan, scene_ids=["scene-001"]
            )

        self.assertEqual(manifest.assignments[0].attempts, 3)
        self.assertEqual(manifest.assignments[1].warnings, ["preserve this"])
        self.assertEqual(len(manifest.assignments[0].search_history), 1)
        self.assertEqual(
            manifest.assignments[0].search_history[0].search_queries,
            ["prior Saturn search"],
        )

    def test_same_plan_id_with_different_script_hash_resets_old_results(self):
        original = make_plan()
        old_manifest = scene_media.SceneMediaManifest(
            plan_id=original.plan_id,
            script_sha256="b" * 64,
            assignments=[
                scene_media.SceneMediaAssignment(
                    scene_id="scene-001",
                    status="no_candidates",
                    warnings=["stale content"],
                )
            ],
        )
        with (
            patch.object(scene_media, "_configured_providers", return_value=[]),
            patch.object(
                scene_media.task_artifacts,
                "read_scene_media_manifest",
                return_value=old_manifest.model_dump(mode="json"),
            ),
            patch.object(scene_media.task_artifacts, "write_scene_media_manifest"),
        ):
            result = scene_media.select_plan_materials("task-script-change", original)

        self.assertNotIn("stale content", result.assignments[0].warnings)

    def test_scene_mode_configuration_is_opt_in_and_visual_validation_defaults_off(self):
        params = VideoParams(video_subject="Astronomy")
        request = TaskVideoRequest(
            video_subject="Astronomy",
            video_pipeline="scene",
            scene_media_visual_validation=True,
        )
        self.assertEqual(params.video_pipeline, "legacy")
        self.assertFalse(params.scene_media_visual_validation)
        self.assertEqual(request.video_pipeline, "scene")
        self.assertTrue(request.scene_media_visual_validation)


if __name__ == "__main__":
    unittest.main()
