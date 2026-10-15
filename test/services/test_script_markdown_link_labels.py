from unittest.mock import patch

from app.services import llm


def test_generated_script_retains_narration_in_markdown_link_labels():
    response = "Visit [the museum](https://example.org/museum) today."
    with patch.object(llm, "_generate_response", return_value=response):
        assert llm.generate_script("museum") == "Visit the museum today."
