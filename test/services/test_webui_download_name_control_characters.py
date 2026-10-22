"""任务历史下载文件名必须移除控制符与双向文本控制符。"""
import ast
import os
import re
from collections.abc import Mapping
from pathlib import Path


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
DOWNLOAD_NAME_HELPERS = {"_build_video_download_name"}
DOWNLOAD_NAME_CONSTANTS = {
    "_DOWNLOAD_FILENAME_INVALID_PATTERN",
    "_WINDOWS_RESERVED_FILENAMES",
}


def _load_download_name_helpers():
    """
    从 WebUI 入口中隔离加载下载文件名相关的纯函数。

    直接导入 Main.py 会执行整套页面渲染。这里只编译目标常量和函数，执行的仍是
    合并后的真实实现，因此断言覆盖的是生产行为而不是测试里的副本。
    """
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    selected_nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in DOWNLOAD_NAME_CONSTANTS
            for target in node.targets
        ):
            selected_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in DOWNLOAD_NAME_HELPERS:
            selected_nodes.append(node)

    namespace = {"os": os, "re": re, "Mapping": Mapping}
    module = ast.fix_missing_locations(ast.Module(body=selected_nodes, type_ignores=[]))
    exec(compile(module, str(WEBUI_MAIN), "exec"), namespace)
    return namespace


build_video_download_name = _load_download_name_helpers()[
    "_build_video_download_name"
]

# 显式列出必须移除的字符，不复制生产代码的 range 推导：实现写错范围时断言会
# 直接失败，而不是跟着实现一起漏测。C0 控制符与 U+0085、U+2028、U+2029 已被
# 空白合并处理，这里仍然逐个确认，避免后续改动把它们重新放进文件名。
C0_CONTROL_CHARACTERS = ("\x00", "\x08", "\x1b", "\x1f")
C1_CONTROL_CHARACTERS = ("\x7f", "\x80", "\x85", "\x9f")
BIDIRECTIONAL_CONTROL_CHARACTERS = (
    "‎",
    "‏",
    "‪",
    "‫",
    "‬",
    "‭",
    "‮",
    "⁦",
    "⁧",
    "⁨",
    "⁩",
)
LINE_SEPARATOR_CHARACTERS = (" ", " ")


def test_download_name_drops_bidirectional_override_from_subject():
    """U+202E 会把后续字符反向渲染，伪造出另一个看起来可信的扩展名。"""
    download_name = build_video_download_name("holiday‮4pm", 1, 1)

    assert "‮" not in download_name
    assert download_name == "holiday 4pm.mp4"


def test_download_name_drops_every_unsafe_character_from_subject():
    """上传入口拒绝的整组字符都不能进入下载文件名。"""
    unsafe_characters = (
        C0_CONTROL_CHARACTERS
        + C1_CONTROL_CHARACTERS
        + BIDIRECTIONAL_CONTROL_CHARACTERS
        + LINE_SEPARATOR_CHARACTERS
    )
    for character in unsafe_characters:
        download_name = build_video_download_name(f"trip{character}note", 1, 1)

        assert character not in download_name, f"U+{ord(character):04X} survived"
        assert download_name == "trip note.mp4"


def test_download_name_keeps_ordinary_multilingual_subjects():
    """移除控制符不能顺带改写正常主题，包括中文、重音字母和标点。"""
    assert build_video_download_name("上海一日游", 1, 1) == "上海一日游.mp4"
    assert build_video_download_name("Café déjà vu", 2, 3) == "Café déjà vu-2.mp4"
    assert (
        build_video_download_name("A day: in / Shanghai?", 2, 3)
        == "A day in Shanghai-2.mp4"
    )
