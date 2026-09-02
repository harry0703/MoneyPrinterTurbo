import ast
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
SCHEDULE_HELPERS = {"_compose_schedule_occurrences", "_schedule_manager_label"}


def _load_schedule_helpers():
    """
    与 test_webui_task_history.py 相同的策略：只编译目标纯函数，不执行
    整套 Streamlit 页面渲染。
    """
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    selected_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in SCHEDULE_HELPERS
    ]
    # _schedule_manager_label chama tr(); um stub identidade é suficiente
    # pra testar a lógica de formatação sem carregar o sistema de locales.
    namespace: dict = {"tr": lambda key: key}
    module = ast.fix_missing_locations(ast.Module(body=selected_nodes, type_ignores=[]))
    exec(compile(module, str(WEBUI_MAIN), "exec"), namespace)
    return namespace


SCHEDULE_NAMESPACE = _load_schedule_helpers()
compose_schedule_occurrences = SCHEDULE_NAMESPACE["_compose_schedule_occurrences"]
schedule_manager_label = SCHEDULE_NAMESPACE["_schedule_manager_label"]


def test_compose_uses_fallback_subject_when_no_subject_list():
    base_dates = [datetime(2026, 3, 5, 9, 0), datetime(2026, 3, 6, 9, 0)]

    result = compose_schedule_occurrences(base_dates, None, [], [], "Café")

    assert result == [
        {"generate_at": base_dates[0], "video_subject": "Café"},
        {"generate_at": base_dates[1], "video_subject": "Café"},
    ]


def test_compose_assigns_subjects_by_index_when_list_given():
    base_dates = [datetime(2026, 3, 5, 9, 0), datetime(2026, 3, 6, 9, 0)]
    subjects = ["Assunto A", "Assunto B"]

    result = compose_schedule_occurrences(base_dates, subjects, [], [], "fallback")

    assert [item["video_subject"] for item in result] == ["Assunto A", "Assunto B"]


def test_compose_removes_excluded_dates():
    base_dates = [
        datetime(2026, 3, 5, 9, 0),
        datetime(2026, 3, 6, 9, 0),
        datetime(2026, 3, 7, 9, 0),
    ]

    result = compose_schedule_occurrences(
        base_dates, None, ["2026-03-06 09:00"], [], "Café"
    )

    assert [item["generate_at"] for item in result] == [
        base_dates[0],
        base_dates[2],
    ]


def test_compose_merges_and_sorts_extra_dates():
    base_dates = [datetime(2026, 3, 5, 9, 0), datetime(2026, 3, 10, 9, 0)]
    extra = [{"generate_at": datetime(2026, 3, 7, 8, 0), "video_subject": "Extra"}]

    result = compose_schedule_occurrences(base_dates, None, [], extra, "Café")

    assert [item["generate_at"] for item in result] == [
        datetime(2026, 3, 5, 9, 0),
        datetime(2026, 3, 7, 8, 0),
        datetime(2026, 3, 10, 9, 0),
    ]
    assert result[1]["video_subject"] == "Extra"


def test_compose_handles_all_dates_excluded():
    base_dates = [datetime(2026, 3, 5, 9, 0)]

    result = compose_schedule_occurrences(
        base_dates, None, ["2026-03-05 09:00"], [], "Café"
    )

    assert result == []


def test_schedule_manager_label_shows_pending_count_only_when_positive():
    assert schedule_manager_label(0) == "Schedule Manager"
    assert schedule_manager_label(3) == "Schedule Manager · 3"
