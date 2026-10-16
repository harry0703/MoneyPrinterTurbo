from unittest.mock import patch

from app.services import llm


def test_formatting_only_output_retries_instead_of_returning_empty_script():
    with patch.object(llm, "_generate_response", side_effect=[
        "[Scene opening]\n\n(Voiceover begins)", "An ocean wave rolls onto the shore."
    ]) as provider:
        script = llm.generate_script("Ocean")
    assert script == "An ocean wave rolls onto the shore."
    assert provider.call_count == 2


def test_meaningful_script_whitespace_and_paragraphs_survive_formatting():
    with patch.object(llm, "_generate_response", return_value="  First paragraph.\n\nSecond paragraph.  ") as provider:
        assert llm.generate_script("Ocean", paragraph_number=2) == "First paragraph.\n\nSecond paragraph."
    assert provider.call_count == 1
