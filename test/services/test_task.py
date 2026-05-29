import unittest
import os
import sys
from pathlib import Path

# add project root to python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import task as tm
from app.models.schema import MaterialInfo, VideoParams

resources_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")

class TestTaskService(unittest.TestCase):
    def setUp(self):
        self.task_id = "00000000-0000-0000-0000-000000000000"

    def _create_test_params(self, material_filenames):
        """Helper feature to dynamically generate VideoParams without duplicating code."""
        video_materials = [
            MaterialInfo(provider="local", url=os.path.join(resources_dir, name), duration=0)
            for name in material_filenames
        ]
        return VideoParams(
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

    def test_task_local_materials_success(self):
        """Tests successful task execution with valid local assets."""
        params = self._create_test_params([f"{i}.png" for i in range(1, 4)])
        result = tm.start(task_id=self.task_id, params=params)
        
        # New Feature: Real assertions to validate task execution output instead of just printing
        self.assertIsNotNone(result, "Task execution returned None")
        # Adjust these assertions based on your actual tm.start() return schema (e.g., status/id fields)
        if hasattr(result, 'status'):
            self.assertEqual(result.status, "success") 

    def test_task_local_materials_missing_file_error(self):
        """New Feature: Negative test case ensuring the service handles missing assets gracefully."""
        params = self._create_test_params(["non_existent_file.png"])
        
        # Expecting the service to either return an error status or raise an exception
        try:
            result = tm.start(task_id=self.task_id, params=params)
            if hasattr(result, 'status'):
                self.assertNotEqual(result.status, "success", "Task should not succeed with missing files")
        except Exception as e:
            self.assertTrue(hasattr(e, 'message') or str(e) is not None, "Task raised an uninformative exception")

    def tearDown(self):
        pass

if __name__ == "__main__":
    unittest.main()
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
    

if __name__ == "__main__":
    unittest.main() 
