"""주소로 지난 작업 설정 불러오기."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

WEBUI_MAIN = str(Path("webui") / "Main.py")

TASK_ID = "url-restore-task"
SCRIPT_DATA = {
    "script": "200번째 닭가슴살을 씹다가 휴지통 앞에서 울컥했다.",
    "search_terms": ["chicken breast"],
    "params": {
        "video_subject": "닭가슴살 200개 먹고 나서야 알게 된 것",
        "video_language": "ko-KR",
        "script_style": "story",
        "layout": "card",
        "headline": "200개째 깨달았다\n문제는 닭이 아니었다",
        # 저장된 설정이나 기본값과 우연히 같으면, 불러오지 않아도 테스트가 통과한다.
        "layout_video_height_ratio": 0.42,
        "layout_corner_radius": 12,
        "headline_font_size": 64,
    },
}


def _app_with_task(tmp_path, query):
    task_dir = Path(tmp_path) / TASK_ID
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "script.json").write_text(
        json.dumps(SCRIPT_DATA, ensure_ascii=False), encoding="utf-8"
    )
    app = AppTest.from_file(WEBUI_MAIN, default_timeout=60)
    app.session_state["ui_language"] = "ko"
    app.query_params.update(query)
    with patch("app.utils.utils.task_dir", return_value=str(tmp_path)):
        app.run()
    return app


class TestRestoreFromUrl(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = self._tmp.name
        # 작업 폴더 밖을 가리키는 대상도 정리 대상 안에 둔다. 시스템 임시
        # 디렉터리에 남기면 반복 실행이나 병렬 실행에서 서로 부딪힌다.
        self._outside_tmp = tempfile.TemporaryDirectory()
        self.outside_path = self._outside_tmp.name

    def tearDown(self):
        self._tmp.cleanup()
        self._outside_tmp.cleanup()

    def test_opening_with_a_task_id_fills_the_form(self):
        """
        '다시 생성 → 설정 불러오기' 를 누르는 것과 같은 일을 주소로 한다. 만들어 둔
        영상을 손보려고 화면을 열 때, 대본을 다시 붙여넣게 하지 않기 위해서다.
        """
        app = _app_with_task(self.tmp_path, {"task": TASK_ID})

        self.assertEqual(
            app.session_state["video_subject"], SCRIPT_DATA["params"]["video_subject"]
        )
        self.assertEqual(app.session_state["video_script"], SCRIPT_DATA["script"])
        self.assertEqual(app.session_state["headline_input"], "200개째 깨달았다\n문제는 닭이 아니었다")

    def test_the_template_comes_along_with_it(self):
        """대본만 돌아오고 화면 구성이 기본값이면 같은 영상이 나오지 않는다."""
        app = _app_with_task(self.tmp_path, {"task": TASK_ID})

        self.assertEqual(app.session_state["layout_select_ko"], "card")
        self.assertAlmostEqual(
            app.session_state["layout_video_height_ratio_slider"], 0.42
        )
        self.assertEqual(app.session_state["layout_corner_radius_slider"], 12)
        self.assertEqual(app.session_state["headline_font_size_slider"], 64)

    def test_an_unknown_task_does_not_break_the_page(self):
        """
        오래된 링크나 지워진 작업 하나로 화면 전체가 뜨면 안 된다. 주소를 읽고
        시도는 했는지까지 확인한다 — 안 읽었어도 화면은 멀쩡하기 때문이다.
        """
        app = _app_with_task(self.tmp_path, {"task": "does-not-exist"})

        # 주소를 읽고 시도했다는 표시. 안 읽었어도 화면은 멀쩡하므로 이걸 봐야 한다.
        self.assertEqual(
            app.session_state["url_task_restore_applied"], "does-not-exist"
        )
        self.assertEqual(app.session_state["video_subject"], "")
        self.assertFalse(app.exception)

    def test_paths_that_escape_the_task_directory_are_refused(self):
        """
        작업 이름이 주소에서 온다. 상대 경로, 절대 경로, NUL 이 섞인 값 어느 것도
        작업 디렉터리 밖을 가리켜서는 안 된다.
        """
        hostile_ids = (
            "../../etc",
            "/etc",
            "sub/../../../etc",
            "task\x00.json",
            # 결과가 작업 폴더 안에 떨어져도, 경로처럼 생긴 값은 받지 않는다.
            f"unused/../{TASK_ID}",
            str(Path(self.tmp_path) / TASK_ID),
        )
        for hostile in hostile_ids:
            with self.subTest(task=hostile):
                app = _app_with_task(self.tmp_path, {"task": hostile})
                # 주소를 읽고 거절했다는 표시. 아예 안 읽어도 아래는 통과한다.
                self.assertEqual(app.session_state["url_task_restore_applied"], hostile)
                self.assertEqual(app.session_state["video_subject"], "")
                self.assertFalse(app.exception)
                self.assertNotIn("task_restore_payload", app.session_state)

    def test_a_symlink_out_of_the_task_directory_is_refused(self):
        """작업 디렉터리 안의 심볼릭 링크로 밖을 가리키는 것도 막아야 한다."""
        import os

        outside = Path(self.outside_path) / "outside-task"
        outside.mkdir(exist_ok=True)
        (outside / "script.json").write_text(
            json.dumps(SCRIPT_DATA, ensure_ascii=False), encoding="utf-8"
        )
        link = Path(self.tmp_path) / "escape"
        if not link.exists():
            os.symlink(outside, link)

        app = _app_with_task(self.tmp_path, {"task": "escape"})

        self.assertEqual(app.session_state["url_task_restore_applied"], "escape")
        self.assertEqual(app.session_state["video_subject"], "")
        self.assertNotIn("task_restore_payload", app.session_state)

    def test_a_traversal_path_is_refused(self):
        """
        작업 이름은 주소에서 온다. 작업 디렉터리 밖을 가리키는 값이 그대로 로더에
        전달되더라도, 로더의 경로 검증에서 막혀 아무것도 채워지지 않아야 한다.
        """
        app = _app_with_task(self.tmp_path, {"task": "../../etc"})

        self.assertEqual(app.session_state["url_task_restore_applied"], "../../etc")
        self.assertEqual(app.session_state["video_subject"], "")
        self.assertFalse(app.exception)
        self.assertNotIn("task_restore_payload", app.session_state)

    def test_edits_are_not_overwritten_on_the_next_rerun(self):
        """
        rerun 마다 다시 채우면, 불러온 대본을 고치는 순간 원래 내용으로 되돌아간다.
        """
        app = _app_with_task(self.tmp_path, {"task": TASK_ID})
        self.assertEqual(
            app.session_state["video_subject"], SCRIPT_DATA["params"]["video_subject"]
        )

        app.session_state["video_subject"] = "내가 고친 주제"
        with patch("app.utils.utils.task_dir", return_value=str(self.tmp_path)):
            app.run()

        self.assertEqual(app.session_state["video_subject"], "내가 고친 주제")


if __name__ == "__main__":
    unittest.main()
