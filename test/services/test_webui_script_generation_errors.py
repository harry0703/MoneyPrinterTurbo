from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.config import config
from app.services import llm, version_checker


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"
# _generate_response() returns a rejected request as text, for example after a
# wrong API key, an account without balance or a wrong Base URL.
PROVIDER_ERROR = (
    "Error: Error code: 401 - {'error': {'message': "
    "'Incorrect API key provided: sk-wrong.', 'code': 'invalid_api_key'}}"
)
SCRIPT_FAILED = (
    "AI could not generate the video script. Try again, or in Settings, open "
    "LLM Settings and click Test Model Connection to check the model service."
)
KEYWORDS_FAILED = (
    "AI could not generate the video keywords. Try again, or in Settings, open "
    "LLM Settings and click Test Model Connection to check the model service."
)
USER_TEXT = {
    "video_subject": "Coffee",
    "video_script": "My own script about coffee.",
    "video_terms": "coffee, cafe",
}


def _widget_by_key(elements, key):
    return next(item for item in elements if str(getattr(item, "key", "")) == key)


def _is_terms_prompt(prompt):
    return "# Role: Video Search Terms Generator" in prompt


def _click_ai_button(button_key, model, text=USER_TEXT):
    """Fill in the script fields, click an AI button and return the page."""
    test_config = dict(
        config.app,
        llm_provider="openai",
        script_generation_backend="local",
    )

    with (
        patch.object(config, "app", test_config),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(
            version_checker,
            "poll_available_update",
            return_value=version_checker.UpdateCheckSnapshot(complete=True),
        ),
        # The real generate_script() and generate_terms() run; only the
        # request to the model service is replaced.
        patch.object(llm, "_generate_response", side_effect=model),
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.run()
        for key, value in text.items():
            _widget_by_key(app.text_area, key).set_value(value).run()
        _widget_by_key(app.button, button_key).click().run()

    assert [str(item.value) for item in app.exception] == []
    return app


def _user_text(app):
    return {key: _widget_by_key(app.text_area, key).value for key in USER_TEXT}


def test_failed_script_generation_shows_an_error_and_keeps_the_user_text():
    """A failed model no longer empties the script and keywords without a word."""
    prompts = []

    def failing_model(prompt, **kwargs):
        prompts.append(prompt)
        return PROVIDER_ERROR

    app = _click_ai_button("auto_generate_script", failing_model)

    assert [str(item.value) for item in app.error] == [SCRIPT_FAILED]
    assert _user_text(app) == USER_TEXT
    # generate_script() retries the script; no keywords are requested for a
    # script that was not generated.
    assert len(prompts) == llm._max_retries
    assert not any(_is_terms_prompt(prompt) for prompt in prompts)


def test_failed_keyword_generation_shows_an_error_and_keeps_the_keywords():
    app = _click_ai_button(
        "auto_generate_terms", lambda prompt, **kwargs: PROVIDER_ERROR
    )

    assert [str(item.value) for item in app.error] == [KEYWORDS_FAILED]
    assert _user_text(app) == USER_TEXT


def test_generated_script_is_applied_when_only_the_keywords_fail():
    script = "Coffee beans are the roasted seeds of the coffee plant."

    def model(prompt, **kwargs):
        if _is_terms_prompt(prompt):
            return PROVIDER_ERROR
        return script

    app = _click_ai_button("auto_generate_script", model)

    assert [str(item.value) for item in app.error] == [KEYWORDS_FAILED]
    assert _widget_by_key(app.text_area, "video_script").value == script
    # Blank keywords are generated from the script when the video is made.
    assert _widget_by_key(app.text_area, "video_terms").value == ""


def test_generated_script_that_quotes_an_error_message_is_applied():
    """A tutorial script may quote an error such as "NameError: ..."."""
    script = (
        "Python stops with NameError: name 'total' is not defined "
        "when a variable is used before it is assigned."
    )

    def model(prompt, **kwargs):
        if _is_terms_prompt(prompt):
            return '["python code", "programmer laptop"]'
        return script

    app = _click_ai_button(
        "auto_generate_script", model, {"video_subject": "Python variables"}
    )

    assert [str(item.value) for item in app.error] == []
    assert _widget_by_key(app.text_area, "video_script").value == script
    assert (
        _widget_by_key(app.text_area, "video_terms").value
        == "python code, programmer laptop"
    )
