import ast
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models.schema import VideoParams


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
TASK_HISTORY_HELPERS = {
    "_find_final_task_video",
    "_build_video_download_name",
    "_build_restore_upload_requirements",
    "_get_unmet_restore_upload_requirements",
    "_load_task_restore_payload",
    "_copy_task_diagnostics",
    "_safe_material_provider_value",
    "_material_provider_result_values",
    "_format_material_provider_results",
}
TASK_HISTORY_CONSTANTS = {
    "_FINAL_VIDEO_PATTERN",
    "_DOWNLOAD_FILENAME_INVALID_PATTERN",
    "VOICE_MODE_TTS",
    "VOICE_MODE_UPLOAD",
    "VOICE_MODE_NONE",
    "_MATERIAL_PROVIDER_NAMES",
    "_MATERIAL_PROVIDER_STATUSES",
    "_MATERIAL_PROVIDER_CATEGORIES",
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

    namespace = {
        "os": os,
        "re": re,
        "Mapping": Mapping,
        "VideoParams": VideoParams,
        "logger": MagicMock(),
        "utils": SimpleNamespace(task_dir=lambda: ""),
        "_safe_load_task_script": lambda _task_path: {},
        "tr": lambda key: key,
    }
    module = ast.fix_missing_locations(ast.Module(body=selected_nodes, type_ignores=[]))
    exec(compile(module, str(WEBUI_MAIN), "exec"), namespace)
    return namespace


TASK_HISTORY_NAMESPACE = _load_task_history_helpers()
find_final_task_video = TASK_HISTORY_NAMESPACE["_find_final_task_video"]
build_video_download_name = TASK_HISTORY_NAMESPACE["_build_video_download_name"]
build_restore_upload_requirements = TASK_HISTORY_NAMESPACE[
    "_build_restore_upload_requirements"
]
get_unmet_restore_upload_requirements = TASK_HISTORY_NAMESPACE[
    "_get_unmet_restore_upload_requirements"
]
load_task_restore_payload = TASK_HISTORY_NAMESPACE["_load_task_restore_payload"]


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


def test_build_video_download_name_uses_subject_and_output_index():
    assert (
        build_video_download_name("A day: in / Shanghai?", 2, 3)
        == "A day in Shanghai-2.mp4"
    )


def test_build_video_download_name_handles_empty_and_long_subjects():
    assert build_video_download_name("  ...  ", 1, 1) == "video.mp4"
    assert len(build_video_download_name("a" * 100, 1, 1)) == 84


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
def test_provider_result_format_is_ordered_and_secret_free():
    format_results = TASK_HISTORY_NAMESPACE["_format_material_provider_results"]
    function_globals = format_results.__globals__
    original_tr = function_globals["tr"]
    function_globals["tr"] = lambda key: {
        "Material Provider Result": "{provider}: {status} · {category} · {count} results · {duration} sec",
        "Material Provider Other": "Other",
        "Material Provider Unknown": "Unknown",
    }.get(key, key)
    try:
        lines = format_results(
            [
                {
                    "provider": "pixabay",
                    "status": "authentication",
                    "error_types": ["authentication"],
                    "result_count": 0,
                    "downloaded_duration": 1.25,
                    "error": "https://secret.example/?key=private",
                    "api_key": "private",
                },
                {
                    "provider": "pexels",
                    "status": "success",
                    "result_count": 3,
                    "downloaded_count": 1,
                    "downloaded_duration": 4,
                },
            ]
        )
    finally:
        function_globals["tr"] = original_tr

    assert lines == [
        "Pixabay: authentication · authentication · 0 results · 1.2 sec",
        "Pexels: success · downloaded · 3 results · 4.0 sec",
    ]
    rendered = " ".join(lines)
    assert "secret.example" not in rendered
    assert "private" not in rendered


@pytest.mark.parametrize(
    ("mode", "providers"),
    [
        ("fallback", ["pixabay", "pexels", "coverr"]),
        ("fan_out", ["coverr", "pexels", "pixabay"]),
    ],
)
def test_restore_payload_keeps_modern_provider_strategy_order(tmp_path, mode, providers):
    task_id = "modern-provider-task"
    task_path = tmp_path / task_id
    task_path.mkdir()
    (task_path / "script.json").write_text(
        json.dumps(
            {
                "script": "A reusable script",
                "params": {
                    "video_subject": "Provider restore",
                    "video_source": "pexels",
                    "material_provider_mode": mode,
                    "material_providers": providers,
                },
            }
        ),
        encoding="utf-8",
    )
    function_globals = load_task_restore_payload.__globals__
    original_utils = function_globals["utils"]
    original_loader = function_globals["_safe_load_task_script"]
    function_globals["utils"] = SimpleNamespace(task_dir=lambda: str(tmp_path))
    function_globals["_safe_load_task_script"] = lambda path: json.loads(
        (Path(path) / "script.json").read_text(encoding="utf-8")
    )
    try:
        payload = load_task_restore_payload(task_id)
    finally:
        function_globals["utils"] = original_utils
        function_globals["_safe_load_task_script"] = original_loader

    assert payload["params"]["material_provider_mode"] == mode
    assert payload["params"]["material_providers"] == providers
