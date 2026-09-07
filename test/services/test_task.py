import unittest
import os
import sys
from pathlib import Path
from unittest.mock import patch

# add project root to python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import task as tm
from app.models.schema import MaterialInfo, VideoParams

resources_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")

class TestTaskService(unittest.TestCase):
    def setUp(self):
        pass
    
    def tearDown(self):
        pass
    
    def test_task_local_materials(self):
        task_id = "00000000-0000-0000-0000-000000000000"
        video_materials=[]
        for i in range(1, 4):
            video_materials.append(MaterialInfo(
                provider="local",
                url=os.path.join(resources_dir, f"{i}.png"),
                duration=0
            ))

        params = VideoParams(
            video_subject="金钱的作用",
            video_script="金钱不仅是交换媒介，更是社会资源的分配工具。它能满足基本生存需求，如食物和住房，也能提供教育、医疗等提升生活品质的机会。拥有足够的金钱意味着更多选择权，比如职业自由或创业可能。但金钱的作用也有边界，它无法直接购买幸福、健康或真诚的人际关系。过度追逐财富可能导致价值观扭曲，忽视精神层面的需求。理想的状态是理性看待金钱，将其作为实现目标的工具而非终极目的。",
            video_terms="money importance, wealth and society, financial freedom, money and happiness, role of money",
            video_aspect="9:16",
            video_concat_mode="random",
            video_transition_mode="None",
            video_clip_duration=3,
            video_count=1,
            video_source="local",
            video_materials=video_materials,
            video_language="",
            voice_name="zh-CN-XiaoxiaoNeural-Female",
            voice_volume=1.0,
            voice_rate=1.0,
            bgm_type="random",
            bgm_file="",
            bgm_volume=0.2,
            subtitle_enabled=True,
            subtitle_position="bottom",
            custom_position=70.0,
            font_name="MicrosoftYaHeiBold.ttc",
            text_fore_color="#FFFFFF",
            text_background_color=True,
            font_size=60,
            stroke_color="#000000",
            stroke_width=1.5,
            n_threads=2,
            paragraph_number=1
        )
        result = tm.start(task_id=task_id, params=params)
        print(result)

    def test_resolve_effective_clip_duration_returns_manual_value(self):
        params = VideoParams(
            video_subject="Manual duration",
            video_script="Texto corto.",
            video_clip_duration=7,
        )

        self.assertEqual(tm.resolve_effective_clip_duration(params, params.video_script, 40), 7)

    def test_resolve_effective_clip_duration_computes_auto_value(self):
        params = VideoParams(
            video_subject="Auto duration",
            video_script="Primera frase. Segunda frase. Tercera frase.",
            video_clip_duration=0,
        )

        self.assertEqual(tm.resolve_effective_clip_duration(params, params.video_script, 18), 6)

    def test_build_final_video_filename_uses_sanitized_subject(self):
        params = VideoParams(
            video_subject="Hola, Mundo!!! 2026",
            video_script="",
            video_count=1,
        )

        self.assertEqual(tm._build_final_video_filename(params, 1), "hola-mundo-2026.mp4")

    def test_build_final_video_filename_falls_back_when_no_ascii_title(self):
        params = VideoParams(
            video_subject="",
            video_script="你好，世界",
            video_count=2,
        )

        self.assertEqual(tm._build_final_video_filename(params, 2), "video-2.mp4")

    @patch("app.services.task.os.path.exists", return_value=True)
    @patch("app.services.task.generate_with_fallback")
    @patch("app.services.task.material.download_videos")
    def test_get_video_materials_uses_external_fallback_when_empty(
        self, mock_download, mock_fallback, mock_exists
    ):
        mock_download.return_value = []
        mock_fallback.return_value = {
            "success": True,
            "localPath": "/tmp/fallback.mp4",
        }

        params = VideoParams(
            video_subject="Test subject",
            video_script="Test script",
            video_terms="term1, term2",
            video_source="pexels",
            external_provider="getimg",
            external_output_type="video",
        )

        materials = tm.get_video_materials(
            task_id="task-1",
            params=params,
            video_terms=["term1", "term2"],
            audio_duration=10,
        )

        self.assertEqual(materials, ["/tmp/fallback.mp4"])
        mock_fallback.assert_called_once()

    @patch("app.services.task.generate_with_fallback")
    @patch("app.services.task.material.download_videos")
    def test_get_video_materials_returns_empty_when_external_fallback_fails(
        self, mock_download, mock_fallback
    ):
        mock_download.return_value = []
        mock_fallback.return_value = {"success": False}

        params = VideoParams(
            video_subject="Test subject",
            video_script="Test script",
            video_terms="term1, term2",
            video_source="pexels",
            external_provider="getimg",
            external_output_type="video",
        )

        materials = tm.get_video_materials(
            task_id="task-2",
            params=params,
            video_terms=["term1", "term2"],
            audio_duration=10,
        )

        self.assertEqual(materials, [])
        mock_fallback.assert_called_once()
    

if __name__ == "__main__":
    unittest.main() 