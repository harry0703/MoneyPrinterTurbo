"""设置页缓存容量在进位边界应显示为下一单位，而不是 1024 KB。"""
import ast
from pathlib import Path


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


def _load_format_file_size():
    """
    从 WebUI 入口中隔离加载容量格式化函数。

    直接导入 Main.py 会执行整套页面渲染。这里只编译目标函数，执行的仍是
    合并后的真实实现，因此断言覆盖的是生产行为而不是测试里的副本。
    """
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    selected_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_format_file_size"
    ]
    namespace = {}
    module = ast.fix_missing_locations(ast.Module(body=selected_nodes, type_ignores=[]))
    exec(compile(module, str(WEBUI_MAIN), "exec"), namespace)
    return namespace["_format_file_size"]


format_file_size = _load_format_file_size()


def test_format_file_size_steps_up_when_rounding_reaches_1024():
    assert format_file_size(0) == "0 B"
    assert format_file_size(1023) == "1023 B"
    assert format_file_size(1024) == "1 KB"
    assert format_file_size(1024 * 1024 - 1) == "1.00 MB"
    assert format_file_size(1024 * 1024) == "1.00 MB"
    assert format_file_size(1024**3 - 1) == "1.00 GB"
    assert format_file_size(1024**3) == "1.00 GB"


def test_format_file_size_keeps_ordinary_values_in_the_current_unit():
    assert format_file_size(512) == "512 B"
    assert format_file_size(1536) == "2 KB"
    assert format_file_size(2.5 * 1024 * 1024) == "2.50 MB"
