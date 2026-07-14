import unittest
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# add project root to python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import task as tm
from app.models.schema import MaterialInfo, VideoParams
from app.utils import utils

resources_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")
RUN_INTEGRATION_TESTS = os.environ.get("MPT_RUN_INTEGRATION_TESTS", "").lower() in {
    "1",
    "true",
    "yes",
}

class TestTaskService(unittest.TestCase):
    def setUp(self):
        pass
    
    def tearDown(self):
        pass

    def test_generate_script_forwards_advanced_prompt_options(self):
        """
        任务生成入口和 WebUI/API 共用 VideoParams。这里验证自动生成文案时，
        高级提示词参数会继续传到 LLM 服务层，避免只在 /scripts 接口生效。
        """
        params = VideoParams(
            video_subject="咖啡",
            video_script="",
            video_language="zh-CN",
            paragraph_number=2,
            video_script_prompt="语气轻松",
            custom_system_prompt="Only write short narration.",
        )

        with patch.object(tm.llm, "generate_script", return_value="生成的文案") as generate:
            result = tm.generate_script("task-id", params)

        self.assertEqual(result, "生成的文案")
        generate.assert_called_once_with(
            video_subject="咖啡",
            language="zh-CN",
            paragraph_number=2,
            video_script_prompt="语气轻松",
            custom_system_prompt="Only write short narration.",
        )

    def test_generate_final_videos_forwards_clip_speed(self):
        """任务编排层必须把用户选择的画面速度传给视频合成服务。"""
        params = VideoParams(
            video_subject="test",
            video_count=1,
            video_clip_speed=1.25,
        )

        with (
            patch.object(tm.video, "combine_videos") as combine_videos,
            patch.object(tm.video, "generate_video"),
            patch.object(tm.sm.state, "update_task"),
        ):
            tm.generate_final_videos(
                task_id="clip-speed-task",
                params=params,
                downloaded_videos=["material.mp4"],
                audio_file="audio.mp3",
                subtitle_path="",
                audio_duration=5,
            )

        self.assertEqual(combine_videos.call_args.kwargs["clip_speed"], 1.25)

    def test_generate_final_videos_uses_generated_sonilo_music(self):
        """Sonilo 必须针对每条拼接后的视频生成配乐，并传给最终混音。"""
        params = VideoParams(
            video_subject="test",
            video_count=1,
            bgm_type="sonilo",
            sonilo_bgm_prompt="warm acoustic",
        )

        with (
            patch.object(tm.video, "combine_videos"),
            patch.object(
                tm.sonilo,
                "generate_bgm",
                side_effect=lambda **kwargs: kwargs["output_path"],
            ) as generate_bgm,
            patch.object(tm.video, "generate_video") as generate_video,
            patch.object(tm.sm.state, "update_task"),
        ):
            _, _, warnings = tm.generate_final_videos(
                task_id="sonilo-task",
                params=params,
                downloaded_videos=["material.mp4"],
                audio_file="audio.mp3",
                subtitle_path="",
                audio_duration=5,
            )

        self.assertEqual(warnings, [])
        self.assertEqual(generate_bgm.call_args.kwargs["video_duration"], 5)
        self.assertEqual(generate_bgm.call_args.kwargs["prompt"], "warm acoustic")
        self.assertTrue(
            generate_video.call_args.kwargs["bgm_file_override"].endswith(
                "sonilo-bgm-1.m4a"
            )
        )

    def test_generate_final_videos_falls_back_without_bgm_on_sonilo_failure(self):
        """第三方配乐失败时应完成视频并返回可见警告，而不是丢弃所有产物。"""
        params = VideoParams(video_subject="test", bgm_type="sonilo")

        with (
            patch.object(tm.video, "combine_videos"),
            patch.object(
                tm.sonilo,
                "generate_bgm",
                side_effect=tm.sonilo.SoniloError("temporary outage"),
            ),
            patch.object(tm.video, "generate_video") as generate_video,
            patch.object(tm.sm.state, "update_task"),
        ):
            final_paths, _, warnings = tm.generate_final_videos(
                task_id="sonilo-fallback",
                params=params,
                downloaded_videos=["material.mp4"],
                audio_file="audio.mp3",
                subtitle_path="",
                audio_duration=5,
            )

        self.assertEqual(len(final_paths), 1)
        self.assertEqual(
            warnings, [{"code": "sonilo_bgm_failed", "video_index": 1}]
        )
        self.assertEqual(generate_video.call_args.kwargs["bgm_file_override"], "")

    def test_generate_final_videos_skips_sonilo_when_volume_is_zero(self):
        """0 音量必须完全跳过 Sonilo 生成，并显式禁用残留背景音乐。"""
        params = VideoParams(
            video_subject="test",
            bgm_type="sonilo",
            bgm_volume=0.0,
            bgm_file="stale-custom-bgm.mp3",
        )

        with (
            patch.object(tm.video, "combine_videos"),
            patch.object(tm.sonilo, "generate_bgm") as generate_bgm,
            patch.object(tm.video, "generate_video", return_value=True) as generate,
            patch.object(tm.sm.state, "update_task"),
        ):
            final_paths, _, warnings = tm.generate_final_videos(
                task_id="sonilo-zero-volume",
                params=params,
                downloaded_videos=["material.mp4"],
                audio_file="audio.mp3",
                subtitle_path="",
                audio_duration=5,
            )

        self.assertEqual(len(final_paths), 1)
        self.assertEqual(warnings, [])
        generate_bgm.assert_not_called()
        self.assertEqual(generate.call_args.kwargs["bgm_file_override"], "")

    def test_generate_final_videos_warns_when_sonilo_mix_fails(self):
        """Sonilo 生成成功但最终混音失败时，任务必须保留视频并返回警告。"""
        params = VideoParams(video_subject="test", bgm_type="sonilo")

        with (
            patch.object(tm.video, "combine_videos"),
            patch.object(
                tm.sonilo,
                "generate_bgm",
                side_effect=lambda **kwargs: kwargs["output_path"],
            ),
            patch.object(tm.video, "generate_video", return_value=False) as generate,
            patch.object(tm.sm.state, "update_task"),
        ):
            final_paths, _, warnings = tm.generate_final_videos(
                task_id="sonilo-mix-fallback",
                params=params,
                downloaded_videos=["material.mp4"],
                audio_file="audio.mp3",
                subtitle_path="",
                audio_duration=5,
            )

        self.assertEqual(len(final_paths), 1)
        self.assertEqual(
            warnings, [{"code": "sonilo_bgm_failed", "video_index": 1}]
        )
        self.assertTrue(
            generate.call_args.kwargs["bgm_file_override"].endswith(".m4a")
        )

    def test_start_rejects_missing_sonilo_key_before_costly_pipeline_steps(self):
        """完整任务缺少 Sonilo Key 时不能先调用 LLM、TTS 或素材服务。"""
        params = VideoParams(video_subject="test", bgm_type="sonilo")
        with (
            patch.object(tm.sonilo, "is_enabled", return_value=False),
            patch.object(tm, "generate_script") as generate_script,
            patch.object(tm, "generate_audio") as generate_audio,
            patch.object(tm, "get_video_materials") as get_materials,
            patch.object(tm.sm.state, "update_task") as update_task,
        ):
            result = tm.start("missing-sonilo-key", params)

        self.assertIsNone(result)
        generate_script.assert_not_called()
        generate_audio.assert_not_called()
        get_materials.assert_not_called()
        update_task.assert_any_call(
            "missing-sonilo-key", state=tm.const.TASK_STATE_FAILED
        )

    def test_start_does_not_require_sonilo_key_when_volume_is_zero(self):
        """0 音量不会使用 Sonilo，因此缺少 Key 时仍应进入正常任务流水线。"""
        params = VideoParams(
            video_subject="test",
            bgm_type="sonilo",
            bgm_volume=0.0,
        )
        with (
            patch.object(tm.sonilo, "is_enabled", return_value=False),
            patch.object(tm, "generate_script", return_value="") as generate_script,
            patch.object(tm.sm.state, "update_task"),
        ):
            result = tm.start("zero-volume-without-key", params)

        self.assertIsNone(result)
        generate_script.assert_called_once_with("zero-volume-without-key", params)

    def test_generate_terms_uses_script_order_mode_when_enabled(self):
        """
        默认模式不受影响；只有用户显式开启素材按文案顺序匹配时，任务层才
        要求 LLM 生成有序关键词，并适当增加关键词数量以覆盖更多脚本片段。
        """
        params = VideoParams(
            video_subject="城市通勤",
            video_script="",
            match_materials_to_script=True,
        )

        with patch.object(tm.llm, "generate_terms", return_value=["city", "train"]) as generate:
            result = tm.generate_terms("task-id", params, "先城市，再地铁")

        self.assertEqual(result, ["city", "train"])
        generate.assert_called_once_with(
            video_subject="城市通勤",
            video_script="先城市，再地铁",
            amount=8,
            match_script_order=True,
        )

    def test_start_stops_before_materials_when_term_provider_fails(self):
        """
        关键词 Provider 失败后，任务必须立即结束，不能继续生成音频或下载素材。

        这里从任务入口覆盖完整的错误传播路径，避免未来只修服务层返回类型，
        却又在任务编排层把空列表转换成其它真值后继续执行外部请求。
        """
        params = VideoParams(
            video_subject="startup story",
            video_script="A short startup story.",
        )

        with (
            patch.object(
                tm.llm,
                "_generate_response",
                return_value="Error: invalid API key",
            ),
            patch.object(tm, "generate_audio") as generate_audio,
            patch.object(tm, "get_video_materials") as get_video_materials,
            patch.object(tm.sm.state, "update_task") as update_task,
        ):
            result = tm.start("term-provider-error", params)

        self.assertIsNone(result)
        generate_audio.assert_not_called()
        get_video_materials.assert_not_called()
        update_task.assert_any_call(
            "term-provider-error",
            state=tm.const.TASK_STATE_FAILED,
        )
    
    def test_generate_audio_uses_custom_file_inside_task_directory(self):
        task_id = "test-custom-audio-safe"
        task_dir = utils.task_dir(task_id)
        custom_audio_file = os.path.join(task_dir, "custom-audio.mp3")
        with open(custom_audio_file, "wb") as audio:
            audio.write(b"fake audio")

        params = VideoParams(
            video_subject="custom audio",
            video_script="",
            custom_audio_file=custom_audio_file,
            voice_name="test-voice",
        )

        try:
            with (
                patch.object(tm.voice, "tts") as tts,
                patch.object(tm.voice, "get_audio_duration", return_value=7),
            ):
                audio_file, audio_duration, sub_maker = tm.generate_audio(
                    task_id, params, "script"
                )
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

        self.assertEqual(audio_file, os.path.realpath(custom_audio_file))
        self.assertEqual(audio_duration, 7)
        self.assertIsNone(sub_maker)
        tts.assert_not_called()

    def test_generate_audio_accepts_server_side_custom_file(self):
        task_id = "test-custom-audio-server-side"
        task_dir = utils.task_dir(task_id)

        with tempfile.NamedTemporaryFile(suffix=".mp3") as server_audio:
            server_audio.write(b"fake audio")
            server_audio.flush()
            params = VideoParams(
                video_subject="custom audio",
                video_script="",
                custom_audio_file=server_audio.name,
                voice_name="test-voice",
            )

            try:
                with (
                    patch.object(tm.voice, "tts") as tts,
                    patch.object(tm.voice, "get_audio_duration", return_value=6),
                ):
                    audio_file, audio_duration, result_sub_maker = tm.generate_audio(
                        task_id, params, "script"
                    )
            finally:
                shutil.rmtree(task_dir, ignore_errors=True)

        self.assertEqual(audio_file, os.path.realpath(server_audio.name))
        self.assertEqual(audio_duration, 6)
        self.assertIsNone(result_sub_maker)
        tts.assert_not_called()

    def test_generate_audio_rejects_missing_custom_file_without_tts(self):
        task_id = "test-custom-audio-missing"
        task_dir = utils.task_dir(task_id)
        missing_audio_file = os.path.join(task_dir, "missing.mp3")
        params = VideoParams(
            video_subject="custom audio",
            video_script="",
            custom_audio_file=missing_audio_file,
            voice_name="test-voice",
        )

        try:
            with (
                patch.object(tm.voice, "tts") as tts,
                patch.object(tm.sm.state, "update_task") as update_task,
            ):
                audio_file, audio_duration, result_sub_maker = tm.generate_audio(
                    task_id, params, "script"
                )
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

        self.assertIsNone(audio_file)
        self.assertIsNone(audio_duration)
        self.assertIsNone(result_sub_maker)
        tts.assert_not_called()
        update_task.assert_called_with(task_id, state=tm.const.TASK_STATE_FAILED)

    def test_generate_subtitle_uses_whisper_for_custom_audio_without_sub_maker(self):
        """
        自定义音频不会经过 TTS，所以没有 sub_maker。
        Whisper 可以直接从音频文件转写，此时不能被 sub_maker 为空的保护逻辑提前跳过。
        """
        task_id = "test-custom-audio-whisper-subtitle"
        task_dir = utils.task_dir(task_id)
        audio_file = os.path.join(task_dir, "custom-audio.mp3")
        Path(audio_file).write_bytes(b"fake audio")
        params = VideoParams(
            video_subject="custom audio",
            video_script="Hello world.",
            subtitle_enabled=True,
        )

        def fake_whisper_create(audio_file, subtitle_file):
            Path(subtitle_file).write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello world.\n\n",
                encoding="utf-8",
            )

        try:
            with (
                patch.object(
                    tm.config,
                    "app",
                    dict(tm.config.app, subtitle_provider="whisper"),
                ),
                patch.object(
                    tm.subtitle, "create", side_effect=fake_whisper_create
                ) as create,
                patch.object(tm.subtitle, "correct") as correct,
            ):
                subtitle_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Hello world.",
                    sub_maker=None,
                    audio_file=audio_file,
                )
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

        self.assertTrue(subtitle_path.endswith("subtitle.srt"))
        create.assert_called_once_with(audio_file=audio_file, subtitle_file=subtitle_path)
        correct.assert_called_once_with(
            subtitle_file=subtitle_path, video_script="Hello world."
        )

    def test_generate_subtitle_skips_edge_provider_without_sub_maker(self):
        """
        Edge 字幕依赖 TTS 返回的 sub_maker 时间轴。
        自定义音频缺少该对象时应继续跳过，避免产生不可信的字幕时间轴。
        """
        task_id = "test-custom-audio-edge-no-submaker"
        task_dir = utils.task_dir(task_id)
        audio_file = os.path.join(task_dir, "custom-audio.mp3")
        Path(audio_file).write_bytes(b"fake audio")
        params = VideoParams(
            video_subject="custom audio",
            video_script="Hello world.",
            subtitle_enabled=True,
        )

        try:
            with (
                patch.object(
                    tm.config,
                    "app",
                    dict(tm.config.app, subtitle_provider="edge"),
                ),
                patch.object(tm.voice, "create_subtitle") as create_subtitle,
                patch.object(tm.subtitle, "create") as whisper_create,
            ):
                subtitle_path = tm.generate_subtitle(
                    task_id=task_id,
                    params=params,
                    video_script="Hello world.",
                    sub_maker=None,
                    audio_file=audio_file,
                )
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)

        self.assertEqual(subtitle_path, "")
        create_subtitle.assert_not_called()
        whisper_create.assert_not_called()

    def test_start_returns_each_intermediate_result(self):
        """
        API 的 script、terms、audio、subtitle 和 materials 模式共用同一条任务
        流水线。每个提前停止点都要返回对应产物，同时不能误执行后续阶段。
        """
        expected_results = {
            "script": {"script": "generated script"},
            "terms": {
                "script": "generated script",
                "terms": ["coffee", "morning"],
            },
            "audio": {"audio_file": "audio.mp3", "audio_duration": 5},
            "subtitle": {"subtitle_path": "subtitle.srt"},
            "materials": {"materials": ["clip.mp4"]},
        }

        for stop_at, expected in expected_results.items():
            with self.subTest(stop_at=stop_at):
                params = VideoParams(video_subject="Coffee")
                with (
                    patch.object(tm, "generate_script", return_value="generated script"),
                    patch.object(
                        tm,
                        "generate_terms",
                        return_value=["coffee", "morning"],
                    ),
                    patch.object(tm, "save_script_data"),
                    patch.object(
                        tm,
                        "generate_audio",
                        return_value=("audio.mp3", 5, object()),
                    ),
                    patch.object(
                        tm,
                        "generate_subtitle",
                        return_value="subtitle.srt",
                    ),
                    patch.object(
                        tm,
                        "get_video_materials",
                        return_value=["clip.mp4"],
                    ),
                    patch.object(tm, "generate_final_videos") as generate_final,
                    patch.object(tm.sm.state, "update_task"),
                ):
                    result = tm.start(
                        f"intermediate-{stop_at}", params, stop_at=stop_at
                    )

                self.assertEqual(result, expected)
                generate_final.assert_not_called()

    def test_start_completes_video_without_cross_posting(self):
        """
        完整任务在自动发布未配置时仍应稳定完成，并把所有中间产物写入最终
        状态。这里还覆盖 API 可能传入字符串拼接模式的兼容转换。
        """
        params = VideoParams(video_subject="Coffee")
        params.video_concat_mode = "sequential"

        with (
            patch.object(tm, "generate_script", return_value="generated script"),
            patch.object(tm, "generate_terms", return_value=["coffee"]),
            patch.object(tm, "save_script_data"),
            patch.object(
                tm,
                "generate_audio",
                return_value=("audio.mp3", 5, object()),
            ),
            patch.object(tm, "generate_subtitle", return_value="subtitle.srt"),
            patch.object(
                tm,
                "get_video_materials",
                return_value=["clip.mp4"],
            ),
            patch.object(
                tm,
                "generate_final_videos",
                return_value=(["final.mp4"], ["combined.mp4"], []),
            ),
            patch.object(
                tm.upload_post.upload_post_service,
                "is_configured",
                return_value=False,
            ),
            patch.object(tm.upload_post, "cross_post_video") as cross_post,
            patch.object(tm.sm.state, "update_task") as update_task,
        ):
            result = tm.start("complete-video", params)

        self.assertEqual(result["videos"], ["final.mp4"])
        self.assertEqual(result["combined_videos"], ["combined.mp4"])
        self.assertEqual(result["cross_post_results"], None)
        self.assertEqual(params.video_concat_mode, tm.VideoConcatMode.sequential)
        cross_post.assert_not_called()
        update_task.assert_called_with(
            "complete-video",
            state=tm.const.TASK_STATE_COMPLETE,
            progress=100,
            **result,
        )

    def test_start_marks_pipeline_failures(self):
        """
        音频、素材和最终视频任一关键产物缺失时都必须进入失败状态，不能把
        不完整任务误报为完成。三个场景复用相同 mock，仅替换故障阶段。
        """
        failure_cases = {
            "audio": (
                (None, None, None),
                ["clip.mp4"],
                (["final.mp4"], ["combined.mp4"], []),
            ),
            "materials": (
                ("audio.mp3", 5, object()),
                None,
                (["final.mp4"], ["combined.mp4"], []),
            ),
            "video": (("audio.mp3", 5, object()), ["clip.mp4"], ([], [], [])),
        }

        for stage, failure_results in failure_cases.items():
            with self.subTest(stage=stage):
                audio_result, materials_result, videos_result = failure_results
                params = VideoParams(video_subject="Coffee")
                with (
                    patch.object(tm, "generate_script", return_value="generated script"),
                    patch.object(tm, "generate_terms", return_value=["coffee"]),
                    patch.object(tm, "save_script_data"),
                    patch.object(tm, "generate_audio", return_value=audio_result),
                    patch.object(tm, "generate_subtitle", return_value="subtitle.srt"),
                    patch.object(
                        tm,
                        "get_video_materials",
                        return_value=materials_result,
                    ),
                    patch.object(
                        tm,
                        "generate_final_videos",
                        return_value=videos_result,
                    ),
                    patch.object(tm.sm.state, "update_task") as update_task,
                ):
                    result = tm.start(f"failed-{stage}", params)

                self.assertIsNone(result)
                update_task.assert_any_call(
                    f"failed-{stage}", state=tm.const.TASK_STATE_FAILED
                )

    def test_start_generates_youtube_metadata_for_each_cross_post(self):
        """
        自动发布到 YouTube 时只生成一次元数据，但要把同一份字段传给每个
        成片，并在任务结果中保留每次上传成功或失败的独立结果。
        """
        params = VideoParams(
            video_subject="Coffee",
            video_language="en",
        )
        metadata = {
            "title": "Morning Coffee",
            "caption": "A better morning.",
            "hashtags": ["coffee", "shorts"],
        }
        service = tm.upload_post.upload_post_service

        with (
            patch.object(tm, "generate_script", return_value="generated script"),
            patch.object(tm, "generate_terms", return_value=["coffee"]),
            patch.object(tm, "save_script_data"),
            patch.object(
                tm,
                "generate_audio",
                return_value=("audio.mp3", 5, object()),
            ),
            patch.object(tm, "generate_subtitle", return_value="subtitle.srt"),
            patch.object(
                tm,
                "get_video_materials",
                return_value=["clip.mp4"],
            ),
            patch.object(
                tm,
                "generate_final_videos",
                return_value=(
                    ["final-1.mp4", "final-2.mp4"],
                    ["combined-1.mp4", "combined-2.mp4"],
                    [],
                ),
            ),
            patch.object(service, "is_configured", return_value=True),
            patch.object(service, "auto_upload", True),
            patch.object(service, "platforms", ["youtube"]),
            patch.object(service, "youtube_privacy_status", "unlisted"),
            patch.object(
                tm.llm,
                "generate_social_metadata",
                return_value=metadata,
            ) as generate_metadata,
            patch.object(
                tm.upload_post,
                "cross_post_video",
                side_effect=[
                    {"success": True},
                    {"success": False, "error": "upload failed"},
                ],
            ) as cross_post,
            patch.object(tm.sm.state, "update_task"),
        ):
            result = tm.start("youtube-cross-post", params)

        generate_metadata.assert_called_once_with(
            video_subject="Coffee",
            video_script="generated script",
            language="en",
            platform="youtube_shorts",
        )
        expected_extra = {
            "youtube_title": "Morning Coffee",
            "youtube_description": "A better morning.",
            "tags": ["coffee", "shorts"],
            "privacyStatus": "unlisted",
            "containsSyntheticMedia": True,
        }
        self.assertEqual(cross_post.call_count, 2)
        for call in cross_post.call_args_list:
            self.assertEqual(call.kwargs["youtube_extra"], expected_extra)
        self.assertEqual(
            result["cross_post_results"],
            [
                {"success": True},
                {"success": False, "error": "upload failed"},
            ],
        )

    @unittest.skipUnless(
        RUN_INTEGRATION_TESTS,
        "MPT_RUN_INTEGRATION_TESTS not set",
    )
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
    

if __name__ == "__main__":
    unittest.main()
