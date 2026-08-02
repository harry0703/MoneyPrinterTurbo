"""대본 스타일 프리셋."""

import ast
import io
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import cli
from streamlit.testing.v1 import AppTest

from app.services import llm


class TestScriptStyleSelection(unittest.TestCase):
    def test_a_style_name_picks_its_own_system_prompt(self):
        """스타일은 기본 system prompt 를 고르는 수단이다."""
        prompt = llm.build_script_prompt(video_subject="닭가슴살", script_style="story")
        self.assertIn(llm.STORY_SCRIPT_SYSTEM_PROMPT, prompt)
        self.assertNotIn(llm.DEFAULT_SCRIPT_SYSTEM_PROMPT, prompt)

    def test_omitting_the_style_is_the_same_as_asking_for_the_default_one(self):
        """
        스타일을 넘기지 않는 기존 호출이 계속 예전 프롬프트를 받아야 한다. 기본
        스타일을 이름으로 지정했을 때와 결과가 같은지로 확인한다.
        """
        without = llm.build_script_prompt(video_subject="닭가슴살")
        with_default = llm.build_script_prompt(
            video_subject="닭가슴살", script_style=llm.DEFAULT_SCRIPT_STYLE
        )
        self.assertEqual(without, with_default)
        self.assertIn(llm.DEFAULT_SCRIPT_SYSTEM_PROMPT, without)

    def test_a_written_prompt_wins_over_the_style(self):
        """
        직접 쓴 프롬프트가 스타일에 밀리면, 사용자가 고친 내용이 조용히 버려진다.
        """
        prompt = llm.build_script_prompt(
            video_subject="닭가슴살",
            custom_system_prompt="내가 쓴 규칙",
            script_style="story",
        )
        self.assertIn("내가 쓴 규칙", prompt)
        self.assertNotIn(llm.STORY_SCRIPT_SYSTEM_PROMPT, prompt)

    def test_an_unknown_style_is_not_written_into_the_log(self):
        """
        스타일 이름은 API 로 들어온다. 무엇이 담겨 있을지 모르는 문자열을 그대로
        로그에 남기면 안 된다.
        """
        with patch.object(llm.logger, "warning") as warning:
            llm.resolve_script_style("sk-secret-token-value")

        warning.assert_called_once()
        self.assertNotIn("sk-secret-token-value", warning.call_args.args[0])

    def test_the_style_field_is_length_bounded(self):
        """상한이 없으면 거대한 문자열이 그대로 요청에 실려 들어온다."""
        from pydantic import ValidationError

        from app.models.schema import VideoParams, VideoScriptRequest

        for model in (VideoParams, VideoScriptRequest):
            with self.subTest(model=model.__name__), self.assertRaises(ValidationError):
                model(video_subject="x", script_style="s" * 5_000)

    def test_an_unknown_style_falls_back_instead_of_failing(self):
        """
        스타일은 표현 선택일 뿐이다. 예전 설정이나 API 오타 하나로 영상 생성 전체가
        실패할 이유가 없다.
        """
        self.assertEqual(
            llm.script_style_prompt("nope"), llm.DEFAULT_SCRIPT_SYSTEM_PROMPT
        )

    def test_the_story_style_starts_at_the_crisis(self):
        """
        쇼츠에는 발단·전개를 담을 시간이 없다. 위기에서 시작해 절정과 결말만 쓴다.
        """
        prompt = llm.STORY_SCRIPT_SYSTEM_PROMPT
        self.assertIn("Crisis", prompt)
        self.assertIn("Climax", prompt)
        self.assertIn("Resolution", prompt)
        self.assertIn("no room for setup and rising action", prompt)

    def test_the_story_style_controls_how_the_narration_will_sound(self):
        """
        TTS 는 적힌 대로 읽는다. 숫자를 아라비아 숫자로 두거나 철자대로 읽으면
        어색해지는 단어를 그대로 두면, 대본이 좋아도 낭독이 어색해진다.
        """
        prompt = llm.STORY_SCRIPT_SYSTEM_PROMPT
        self.assertIn("numbers as words", prompt)
        self.assertIn("spell it", prompt)

    def test_the_story_style_forbids_inventing_facts(self):
        """
        각색을 허용하는 프롬프트다. 경험담은 지어내도 되지만 효능·수치까지 지어내면
        재미가 아니라 틀린 정보가 된다. 그 선을 프롬프트가 직접 그어야 한다.
        """
        self.assertIn("never invent factual claims", llm.STORY_SCRIPT_SYSTEM_PROMPT)


class TestCliStyleChoices(unittest.TestCase):
    def test_the_cli_choices_match_the_registered_styles(self):
        """
        cli.py 는 `-h` 를 가볍게 유지하려고 app 패키지를 늦게 불러온다. 그래서 선택지를
        직접 들고 있는데, 스타일이 추가되면 여기가 조용히 뒤처진다.
        """
        self.assertEqual(
            sorted(cli.SCRIPT_STYLE_CHOICES), sorted(llm.SCRIPT_STYLE_PROMPTS)
        )

    def test_the_flag_reaches_video_params(self):
        """플래그가 파싱만 되고 파라미터로 넘어가지 않으면 아무 일도 일어나지 않는다."""
        args = cli.parse_args(
            ["--video-subject", "닭가슴살", "--script-style", "story"]
        )
        params = cli.build_video_params(args)
        self.assertEqual(params.script_style, "story")

    def test_an_unregistered_style_is_rejected_by_the_choices_list(self):
        """
        오타는 그 자리에서 알려줘야 한다. 플래그가 아예 없어도 SystemExit 이 나므로,
        거절 이유가 `choices` 인지까지 확인한다.
        """
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()) as err:
            cli.parse_args(["--video-subject", "x", "--script-style", "nope"])
        message = err.getvalue()
        self.assertIn("invalid choice", message)
        self.assertIn("story", message)


class TestWebuiStyleLabels(unittest.TestCase):
    def test_every_style_has_a_label_in_every_locale(self):
        """라벨이 없으면 선택지에 영어 키가 그대로 노출된다."""
        import json

        for path in sorted(Path("webui/i18n").glob("*.json")):
            translation = json.loads(path.read_text(encoding="utf-8"))["Translation"]
            with self.subTest(locale=path.stem):
                self.assertIn("Script Style", translation)
                for name in llm.SCRIPT_STYLE_PROMPTS:
                    self.assertIn(f"Script Style {name}", translation)


class TestWebuiStyleWiring(unittest.TestCase):
    """화면에서 고른 스타일이 실제로 대본 생성까지 도달해야 한다."""

    def test_choosing_a_style_swaps_the_system_prompt_on_screen(self):
        """
        `stable_selectbox` 는 언어별 key 로 상태를 보관한다. 콜백이 원래 key 로 읽으면
        늘 비어 있어서, story 를 골라도 프롬프트가 기본값으로 되돌아간다. 그 프롬프트는
        다시 '사용자가 고친 것' 으로 취급돼 스타일 선택을 통째로 덮는다.
        """
        app = AppTest.from_file(
            str(Path("webui") / "Main.py"), default_timeout=60
        )
        app.session_state["ui_language"] = "ko"
        app.run()

        selector = next(
            box for box in app.selectbox if box.key == "script_style_select_ko"
        )
        selector.select("story").run()

        self.assertEqual(
            app.session_state["custom_system_prompt"], llm.STORY_SCRIPT_SYSTEM_PROMPT
        )

    def test_the_style_survives_a_ui_language_change(self):
        """
        위젯 key 에는 언어가 붙는다. 언어를 바꾸면 새 key 가 기본값으로 시작해 고른
        스타일이 사라지는데, 시스템 프롬프트는 story 인 채로 남는다. 화면은 '정보
        전달' 을 보여주면서 실제로는 story 프롬프트로 대본을 쓰게 된다.
        """
        app = AppTest.from_file(str(Path("webui") / "Main.py"), default_timeout=60)
        app.session_state["ui_language"] = "ko"
        app.run()

        next(
            box for box in app.selectbox if box.key == "script_style_select_ko"
        ).select("story").run()

        # 언어는 상단 위젯이 소유한다. session_state 를 직접 바꾸면 다음 실행에서
        # 위젯 값으로 되돌아간다.
        next(
            box for box in app.selectbox if box.key == "top_language_code_selector"
        ).select("en").run()

        selector = next(
            box for box in app.selectbox if box.key == "script_style_select_en"
        )
        self.assertEqual(selector.value, "story")

    def test_the_standalone_script_button_passes_the_style(self):
        """
        미리보기와 '대본 생성' 버튼이 스타일을 빠뜨리면, 화면에서는 story 를 골랐는데
        생성된 대본만 기본 스타일로 나온다.
        """
        source = Path("webui/Main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "attr", "") in {"generate_script", "build_script_prompt"}
        ]
        self.assertTrue(calls, "대본 생성 호출을 찾지 못했다")
        for call in calls:
            with self.subTest(line=call.lineno):
                self.assertIn(
                    "script_style", [kw.arg for kw in call.keywords]
                )


class TestEffectiveStyleIsRecorded(unittest.TestCase):
    """기록에는 요청값이 아니라 실제로 쓰인 스타일이 남아야 한다."""

    def test_an_unknown_api_value_is_replaced_before_the_manifest_is_written(self):
        """
        오타 하나로 작업을 실패시키지는 않는다. 대신 기본 스타일로 쓴다. 그런데
        요청값을 그대로 기록하면, 나중에 같은 작업을 되살렸을 때 기록된 스타일과
        실제로 나온 대본이 어긋난다.
        """
        from app.models.schema import VideoParams
        from app.services import task as tm

        params = VideoParams(video_subject="커피", video_script="", script_style="stor")

        with patch.object(tm.llm, "generate_script", return_value="생성된 대본"):
            tm.generate_script("task-id", params)

        self.assertEqual(params.script_style, llm.DEFAULT_SCRIPT_STYLE)

    def test_a_registered_style_is_left_alone(self):
        """멀쩡한 값까지 건드리면 고른 스타일이 조용히 사라진다."""
        from app.models.schema import VideoParams
        from app.services import task as tm

        params = VideoParams(video_subject="커피", video_script="", script_style="story")

        with patch.object(tm.llm, "generate_script", return_value="생성된 대본"):
            tm.generate_script("task-id", params)

        self.assertEqual(params.script_style, "story")


if __name__ == "__main__":
    unittest.main()
