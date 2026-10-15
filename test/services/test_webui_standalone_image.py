# -*- coding: utf-8 -*-
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.config import config


ROOT_DIR = Path(__file__).parent.parent.parent
WEBUI_MAIN = ROOT_DIR / "webui" / "Main.py"


def _widget_by_key(elements, key):
    return next(
        (
            item
            for item in elements
            if str(getattr(item, "key", "")) == key
            or str(getattr(item, "key", "")).startswith(f"{key}_")
        ),
        None,
    )


def test_batch_generation_after_rerun_passes_configuration_and_blueprint():
    """
    Regression test for rerun bug:
    Generate an image first so blueprint is saved in session state,
    then click 'Generate Batch Now' on the next rerun where gen_btn is False.
    Verify that active_model and active_base_url are resolved and passed correctly.
    """
    test_config = dict(
        config.app,
        openai_image_base_url="https://ai.example.com/v1",
        openai_image_model="dall-e-3",
        openai_image_api_keys=["sk-test-key-xyz"],
    )

    with (
        patch.object(config, "app", test_config),
        patch.object(config, "try_save_config", return_value=True),
        patch("app.services.image.generate_images") as mock_gen,
    ):
        mock_gen.side_effect = [
            [
                {
                    "path": "test_output_1.png",
                    "filename": "test_output_1.png",
                    "width": 1024,
                    "height": 1024,
                    "size_bytes": 1024,
                    "prompt": "Test Prompt",
                    "blueprint": "saved_design_blueprint_abc",
                }
            ],
            [
                {
                    "path": "test_output_batch_1.png",
                    "filename": "test_output_batch_1.png",
                    "width": 1024,
                    "height": 1024,
                    "size_bytes": 1024,
                    "prompt": "",
                    "blueprint": "saved_design_blueprint_abc",
                }
            ],
        ]

        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.run()
        assert not app.exception

        prompt_input = _widget_by_key(app.text_area, "standalone_image_prompt_input")
        assert prompt_input is not None
        prompt_input.set_value("Cyberpunk city street").run()

        # Click first button: Generate Images
        gen_btn = _widget_by_key(app.button, "standalone_generate_image_action_btn")
        assert gen_btn is not None
        gen_btn.click().run()

        assert not app.exception
        assert mock_gen.call_count == 1
        first_call = mock_gen.call_args_list[0].kwargs
        assert first_call["prompt"] == "Cyberpunk city street"
        assert first_call["model"] == "dall-e-3"
        assert first_call["base_url"] == "https://ai.example.com/v1"

        # On the rerun, batch button is visible because blueprint exists
        batch_btn = _widget_by_key(app.button, "standalone_generate_batch_action_btn")
        assert batch_btn is not None

        # Click second button: Generate Batch Now
        batch_btn.click().run()

        # Must not raise UnboundLocalError: cannot access local variable 'active_model'
        assert not app.exception
        assert mock_gen.call_count == 2
        batch_call = mock_gen.call_args_list[1].kwargs
        assert batch_call["model"] == "dall-e-3"
        assert batch_call["base_url"] == "https://ai.example.com/v1"
        assert batch_call["cached_blueprint"] == "saved_design_blueprint_abc"


def test_batch_generation_handles_missing_configuration_gracefully():
    """Verify that batch generation validates empty base_url/model instead of crashing."""
    test_config = dict(
        config.app,
        openai_image_base_url="",
        openai_image_model="",
    )

    with (
        patch.object(config, "app", test_config),
        patch.object(config, "try_save_config", return_value=True),
        patch("app.services.image.generate_images") as mock_gen,
    ):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.session_state["cached_active_blueprint"] = "blueprint_123"
        app.session_state["standalone_last_generated_images"] = [
            {
                "path": "img.png",
                "filename": "img.png",
                "width": 512,
                "height": 512,
                "size_bytes": 100,
            }
        ]
        app.run()
        assert not app.exception

        batch_btn = _widget_by_key(app.button, "standalone_generate_batch_action_btn")
        assert batch_btn is not None
        batch_btn.click().run()

        assert not app.exception
        assert mock_gen.call_count == 0
        assert any("is required" in str(err.value) for err in app.error)
