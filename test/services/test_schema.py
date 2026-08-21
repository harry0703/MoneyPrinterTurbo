import sys
import unittest
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models.schema import (
    BgmItemData,
    BgmRetrieveData,
    BgmRetrieveResponse,
    BgmUploadData,
    BgmUploadResponse,
    MaterialInfo,
    TaskDeletionData,
    TaskDeletionResponse,
    TaskResponse,
    TaskResponseData,
    VideoAspect,
    VideoMaterialItemData,
    VideoMaterialRetrieveData,
    VideoMaterialRetrieveResponse,
    VideoMaterialUploadData,
    VideoMaterialUploadResponse,
    VideoParams,
    VideoScriptData,
    VideoScriptResponse,
    VideoSocialMetadataData,
    VideoSocialMetadataResponse,
    VideoTermsData,
    VideoTermsResponse,
)


class TestVideoAspect(unittest.TestCase):
    def test_to_resolution_known_aspects(self):
        self.assertEqual(VideoAspect.landscape.to_resolution(), (1920, 1080))
        self.assertEqual(VideoAspect.portrait.to_resolution(), (1080, 1920))
        self.assertEqual(VideoAspect.square.to_resolution(), (1080, 1080))

    def test_to_resolution_rejects_unsupported_value(self):
        with self.assertRaises(ValueError):
            VideoAspect.to_resolution("4:5")


class TestVideoParams(unittest.TestCase):
    def test_rejects_non_positive_generation_counts(self):
        for field_name in ("video_clip_duration", "video_count"):
            for value in (0, -1, None):
                with (
                    self.subTest(field_name=field_name, value=value),
                    self.assertRaises(ValidationError),
                ):
                    VideoParams(video_subject="Coffee", **{field_name: value})

    def test_accepts_positive_generation_counts(self):
        params = VideoParams(
            video_subject="Coffee", video_clip_duration=1, video_count=1
        )

        self.assertEqual(params.video_clip_duration, 1)
        self.assertEqual(params.video_count, 1)


class TestMaterialInfo(unittest.TestCase):
    def test_material_info_dataclass_arbitrary_types(self):
        class CustomObject:
            pass

        info = MaterialInfo(
            provider="pexels",
            url="https://example.com/video.mp4",
            duration=10,
            source_info={"custom": CustomObject()},
        )
        self.assertEqual(info.provider, "pexels")
        self.assertEqual(info.duration, 10)
        self.assertIsInstance(info.source_info["custom"], CustomObject)


class TestResponseSchemas(unittest.TestCase):
    def test_task_response_typed_data(self):
        resp = TaskResponse(
            status=200, message="success", data={"task_id": "test-123"}
        )
        self.assertIsInstance(resp.data, TaskResponseData)
        self.assertEqual(resp.data.task_id, "test-123")
        schema = TaskResponse.model_json_schema()
        self.assertIn("data", schema["properties"])
        self.assertIn("TaskResponseData", schema["$defs"])

    def test_task_deletion_response_typed_data(self):
        resp = TaskDeletionResponse(
            status=200,
            message="success",
            data={"state": 1, "progress": 100, "videos": ["/path/v1.mp4"]},
        )
        self.assertIsInstance(resp.data, TaskDeletionData)
        self.assertEqual(resp.data.state, 1)
        self.assertEqual(resp.data.progress, 100)
        schema = TaskDeletionResponse.model_json_schema()
        self.assertIn("TaskDeletionData", schema["$defs"])

    def test_video_script_response_typed_data(self):
        resp = VideoScriptResponse(
            status=200, message="success", data={"video_script": "test script"}
        )
        self.assertIsInstance(resp.data, VideoScriptData)
        self.assertEqual(resp.data.video_script, "test script")
        schema = VideoScriptResponse.model_json_schema()
        self.assertIn("VideoScriptData", schema["$defs"])

    def test_video_terms_response_typed_data(self):
        resp = VideoTermsResponse(
            status=200, message="success", data={"video_terms": ["apple", "banana"]}
        )
        self.assertIsInstance(resp.data, VideoTermsData)
        self.assertEqual(resp.data.video_terms, ["apple", "banana"])
        schema = VideoTermsResponse.model_json_schema()
        self.assertIn("VideoTermsData", schema["$defs"])

    def test_video_social_metadata_response_typed_data(self):
        resp = VideoSocialMetadataResponse(
            status=200,
            message="success",
            data={
                "title": "Title",
                "caption": "Caption",
                "hashtags": ["#shorts"],
            },
        )
        self.assertIsInstance(resp.data, VideoSocialMetadataData)
        self.assertEqual(resp.data.title, "Title")
        schema = VideoSocialMetadataResponse.model_json_schema()
        self.assertIn("VideoSocialMetadataData", schema["$defs"])

    def test_bgm_responses_typed_data(self):
        retrieve_resp = BgmRetrieveResponse(
            status=200,
            message="success",
            data={
                "files": [{"name": "track1.mp3", "size": 1024, "file": "track1.mp3"}]
            },
        )
        self.assertIsInstance(retrieve_resp.data, BgmRetrieveData)
        self.assertEqual(len(retrieve_resp.data.files), 1)
        self.assertIsInstance(retrieve_resp.data.files[0], BgmItemData)

        upload_resp = BgmUploadResponse(
            status=200, message="success", data={"file": "uploaded.mp3"}
        )
        self.assertIsInstance(upload_resp.data, BgmUploadData)
        self.assertEqual(upload_resp.data.file, "uploaded.mp3")

    def test_video_material_responses_typed_data(self):
        retrieve_resp = VideoMaterialRetrieveResponse(
            status=200,
            message="success",
            data={
                "files": [{"name": "clip.mp4", "size": 2048, "file": "clip.mp4"}]
            },
        )
        self.assertIsInstance(retrieve_resp.data, VideoMaterialRetrieveData)
        self.assertEqual(len(retrieve_resp.data.files), 1)
        self.assertIsInstance(retrieve_resp.data.files[0], VideoMaterialItemData)

        upload_resp = VideoMaterialUploadResponse(
            status=200, message="success", data={"file": "new_clip.mp4"}
        )
        self.assertIsInstance(upload_resp.data, VideoMaterialUploadData)
        self.assertEqual(upload_resp.data.file, "new_clip.mp4")


if __name__ == "__main__":
    unittest.main()
