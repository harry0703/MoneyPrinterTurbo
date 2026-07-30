import ast
import os
import re
from collections.abc import Mapping
from pathlib import Path


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
TASK_HISTORY_HELPERS = {
    "_find_final_task_video",
    "_list_final_task_videos",
    "_list_task_artifacts",
    "_build_restore_upload_requirements",
    "_get_unmet_restore_upload_requirements",
}
TASK_HISTORY_CONSTANTS = {
    "_FINAL_VIDEO_PATTERN",
    "_TASK_ARTIFACT_EXTENSIONS",
    "_TASK_ARTIFACT_EXCLUDED_PREFIXES",
    "_TASK_ARTIFACT_MAX_FILES",
    "VOICE_MODE_TTS",
    "VOICE_MODE_UPLOAD",
    "VOICE_MODE_NONE",
}


def _load_task_history_helpers():
    """
    从 WebUI 入口中隔离加载不依赖 Streamlit 的任务历史纯函数。

    直接导入 Main.py 会执行整套页面渲染。测试只编译目标常量和函数，既验证
    合并后的真实实现，也避免为了单元测试重新拆出一个只有少量函数的生产模块。
    """
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    selected_nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in TASK_HISTORY_CONSTANTS
            for target in node.targets
        ):
            selected_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in TASK_HISTORY_HELPERS:
            selected_nodes.append(node)

    namespace = {"os": os, "re": re, "Mapping": Mapping}
    module = ast.fix_missing_locations(ast.Module(body=selected_nodes, type_ignores=[]))
    exec(compile(module, str(WEBUI_MAIN), "exec"), namespace)
    return namespace


TASK_HISTORY_NAMESPACE = _load_task_history_helpers()
find_final_task_video = TASK_HISTORY_NAMESPACE["_find_final_task_video"]
list_final_task_videos = TASK_HISTORY_NAMESPACE["_list_final_task_videos"]
list_task_artifacts = TASK_HISTORY_NAMESPACE["_list_task_artifacts"]
build_restore_upload_requirements = TASK_HISTORY_NAMESPACE[
    "_build_restore_upload_requirements"
]
get_unmet_restore_upload_requirements = TASK_HISTORY_NAMESPACE[
    "_get_unmet_restore_upload_requirements"
]


def test_find_final_task_video_ignores_intermediate_files(tmp_path):
    """任务历史只能把 final 成片识别为完成，不能使用合成中间文件。"""
    for file_name in (
        "combined-1.mp4",
        "temp-clip-1.mp4",
        "final-1TEMP_MPY_wvf_snd.mp4",
    ):
        (tmp_path / file_name).touch()

    assert find_final_task_video(str(tmp_path)) == ""


def test_find_final_task_video_returns_first_numbered_output(tmp_path):
    """多成片任务与运行时结果保持一致，默认播放序号最小的最终视频。"""
    (tmp_path / "final-10.mp4").touch()
    (tmp_path / "final-2.mp4").touch()
    (tmp_path / "final-1.mp4").touch()

    assert find_final_task_video(str(tmp_path)) == str(tmp_path / "final-1.mp4")


def test_list_final_task_videos_uses_numeric_order_and_rejects_symlinks(tmp_path):
    outside_video = tmp_path.parent / "outside-final.mp4"
    outside_video.touch()
    (tmp_path / "final-10.mp4").touch()
    (tmp_path / "final-2.mp4").touch()
    (tmp_path / "final-1.mp4").symlink_to(outside_video)

    assert list_final_task_videos(str(tmp_path)) == [
        str((tmp_path / "final-2.mp4").resolve()),
        str((tmp_path / "final-10.mp4").resolve()),
    ]


def test_list_task_artifacts_only_returns_safe_delivery_files(tmp_path):
    (tmp_path / "final-1.mp4").write_bytes(b"video")
    (tmp_path / "audio.mp3").write_bytes(b"audio")
    (tmp_path / "subtitle.srt").write_text("subtitle", encoding="utf-8")
    (tmp_path / "script.json").write_text("{}", encoding="utf-8")
    (tmp_path / "combined-1.mp4").touch()
    (tmp_path / "temp-clip-1.mp4").touch()
    (tmp_path / ".secret.json").touch()
    (tmp_path / "debug.log").touch()
    (tmp_path / "nested").mkdir()
    (tmp_path / "linked.mp4").symlink_to(tmp_path / "final-1.mp4")

    artifacts = list_task_artifacts(str(tmp_path))

    assert [artifact["name"] for artifact in artifacts] == [
        "final-1.mp4",
        "audio.mp3",
        "script.json",
        "subtitle.srt",
    ]
    assert artifacts[0]["size"] == 5


def test_restore_requirements_block_missing_uploaded_files():
    params = {
        "video_source": "local",
        "custom_audio_file": "/old-task/custom-audio.wav",
        "voice_name": "zh-CN-XiaoxiaoNeural-Female",
    }
    requirements = build_restore_upload_requirements(params)

    assert get_unmet_restore_upload_requirements(
        requirements,
        video_source="local",
        voice_name=params["voice_name"],
        has_local_materials=False,
        has_custom_audio=False,
    ) == {"local_materials", "custom_audio"}


def test_restore_requirements_allow_explicit_replacements():
    requirements = build_restore_upload_requirements(
        {
            "video_source": "local",
            "custom_audio_file": "/old-task/custom-audio.wav",
            "voice_name": "zh-CN-XiaoxiaoNeural-Female",
        }
    )

    assert not get_unmet_restore_upload_requirements(
        requirements,
        video_source="pexels",
        voice_name="en-US-JennyNeural-Female",
        has_local_materials=False,
        has_custom_audio=False,
    )


def test_restore_requirements_require_file_in_upload_voice_mode():
    """恢复上传配音任务时，继续使用上传模式必须重新选择音频文件。"""
    requirements = build_restore_upload_requirements(
        {
            "video_source": "pexels",
            "custom_audio_file": "/old-task/custom-audio.wav",
            "voice_name": "zh-CN-XiaoxiaoNeural-Female",
        }
    )

    assert get_unmet_restore_upload_requirements(
        requirements,
        video_source="pexels",
        voice_name="zh-CN-XiaoxiaoNeural-Female",
        has_local_materials=False,
        has_custom_audio=False,
        voice_mode="upload",
    ) == {"custom_audio"}


def test_restore_requirements_allow_replacing_upload_with_other_voice_modes():
    """用户主动切换到自动配音或无配音时，不再强制恢复历史上传文件。"""
    requirements = build_restore_upload_requirements(
        {
            "video_source": "pexels",
            "custom_audio_file": "/old-task/custom-audio.wav",
            "voice_name": "zh-CN-XiaoxiaoNeural-Female",
        }
    )

    for voice_mode in ("tts", "none"):
        assert not get_unmet_restore_upload_requirements(
            requirements,
            video_source="pexels",
            voice_name="zh-CN-XiaoxiaoNeural-Female",
            has_local_materials=False,
            has_custom_audio=False,
            voice_mode=voice_mode,
        )
