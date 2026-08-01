import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models.schema import VideoParams
from app.services import task_artifacts


class TestTaskArtifacts(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.task_dir = Path(self.temp_dir.name)
        self.task_dir_patch = patch(
            "app.services.task_artifacts.utils.task_dir",
            return_value=str(self.task_dir),
        )
        self.task_dir_patch.start()

    def tearDown(self):
        self.task_dir_patch.stop()
        self.temp_dir.cleanup()

    def test_patch_preserves_existing_script_fields(self):
        """소재 출처를 덧붙일 때 지난 작업 복원에 필요한 대본, 키워드, 파라미터를 덮어써서는 안 된다."""
        original = {
            "script": "existing script",
            "search_terms": ["nature"],
            "params": {"video_source": "pixabay"},
        }
        task_artifacts.write_script_data("task-1", original)

        updated = task_artifacts.patch_script_data(
            "task-1",
            material_sources=[
                {
                    "provider": "pixabay",
                    "asset_id": "123",
                    "local_file": "vid-123.mp4",
                }
            ],
        )
        payload = json.loads((self.task_dir / "script.json").read_text())

        self.assertTrue(updated)
        self.assertEqual(payload["script"], original["script"])
        self.assertEqual(payload["search_terms"], original["search_terms"])
        self.assertEqual(payload["params"], original["params"])
        self.assertEqual(payload["material_sources"][0]["asset_id"], "123")
        self.assertEqual(list(self.task_dir.glob(".script.json.*.tmp")), [])

    def test_write_script_data_serializes_video_params(self):
        """원자적 쓰기로 예전 구현을 대체한 뒤에도 작업 주 흐름이 넘기는 Pydantic 파라미터와 완전히 호환돼야 한다."""
        params = VideoParams(
            video_subject="test subject",
            video_terms=["city", "night"],
        )

        task_artifacts.write_script_data(
            "task-params",
            {
                "script": "test script",
                "search_terms": ["city"],
                "params": params,
            },
        )
        payload = json.loads((self.task_dir / "script.json").read_text())

        self.assertEqual(payload["params"]["video_subject"], "test subject")
        self.assertEqual(payload["params"]["video_terms"], ["city", "night"])
        self.assertEqual(payload["params"]["video_source"], "pexels")

    def test_patch_missing_script_is_non_blocking(self):
        """소재 다운로드를 단독으로 호출하면 작업 매니페스트가 없으므로, 불완전한 JSON 을 만들지 말고 조용히 건너뛰어야 한다."""
        updated = task_artifacts.patch_script_data(
            "standalone",
            material_sources=[],
        )

        self.assertFalse(updated)
        self.assertFalse((self.task_dir / "script.json").exists())

    def test_patch_invalid_script_returns_false_without_overwrite(self):
        """예전 JSON 이 손상됐다면 원본 파일을 남기고 오류를 기록하되, 영상 주 흐름은 계속되게 해야 한다."""
        target = self.task_dir / "script.json"
        target.write_text("{invalid-json", encoding="utf-8")

        with patch.object(task_artifacts.logger, "warning") as warning:
            updated = task_artifacts.patch_script_data(
                "task-1",
                material_sources=[],
            )

        self.assertFalse(updated)
        self.assertEqual(target.read_text(encoding="utf-8"), "{invalid-json")
        self.assertTrue(warning.called)


if __name__ == "__main__":
    unittest.main()


class TestEffectiveFontRecording(unittest.TestCase):
    """실제로 사용된 자막 글꼴이 작업 기록에 남아야 한다."""

    def test_pipeline_records_the_font_that_was_actually_used(self):
        """
        매니페스트는 생성 전에 쓰이는데 글꼴 교체는 생성 중에 일어난다. 요청값만
        남으면 작업을 다시 불러왔을 때 실제 결과와 어긋난다.
        """
        import ast
        from pathlib import Path

        source = (
            Path(__file__).parent.parent.parent / "app" / "services" / "task.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)

        recorded = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if getattr(func, "attr", "") != "patch_script_data":
                continue
            if any(kw.arg == "effective_font_name" for kw in node.keywords):
                recorded = True
                break

        self.assertTrue(
            recorded, "실제 사용된 글꼴이 작업 기록에 반영되지 않는다"
        )


class TestHeadlineRecording(unittest.TestCase):
    """영상에 그려진 헤드라인이 작업 기록에도 남아야 한다."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.task_dir_patch = patch(
            "app.services.task_artifacts.utils.task_dir",
            return_value=self.temp_dir.name,
        )
        self.task_dir_patch.start()

    def tearDown(self):
        self.task_dir_patch.stop()
        self.temp_dir.cleanup()

    def test_pipeline_records_the_generated_headline(self):
        """
        매니페스트는 헤드라인이 만들어지기 전에 쓰인다. 보완하지 않으면 영상에는
        문구가 있는데 기록에는 빈 값이 남아, 같은 작업을 다시 돌릴 때마다 다른
        문구가 나온다.
        """
        from app.services import task as tm

        params = VideoParams(video_subject="Coffee", layout="card")

        with (
            patch.object(tm, "generate_script", return_value="generated script"),
            patch.object(tm, "generate_terms", return_value=["coffee"]),
            patch.object(
                tm, "generate_audio", return_value=("audio.mp3", 5, object())
            ),
            patch.object(tm, "generate_subtitle", return_value="subtitle.srt"),
            patch.object(tm, "get_video_materials", return_value=["clip.mp4"]),
            patch.object(
                tm,
                "generate_final_videos",
                return_value=(["final.mp4"], ["combined.mp4"], []),
            ),
            patch.object(
                tm.llm, "generate_headline", return_value="첫 줄\n둘째 줄"
            ),
            patch.object(
                tm.upload_post.upload_post_service, "is_configured", return_value=False
            ),
            patch.object(tm.sm.state, "update_task"),
        ):
            tm.start("headline-artifact", params)

        recorded = json.loads(
            (Path(self.temp_dir.name) / "script.json").read_text(encoding="utf-8")
        )
        self.assertEqual(recorded["headline"], "첫 줄\n둘째 줄")
