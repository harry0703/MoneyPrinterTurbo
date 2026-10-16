from unittest.mock import patch

import pytest

from app.services import llm


@pytest.mark.parametrize('narration', ['Learn C# and F# today.', 'Play the F# note before G.'])
def test_script_cleanup_preserves_inline_hashes(narration):
    with patch.object(llm, '_generate_response', return_value=narration):
        assert llm.generate_script('lesson') == narration


@pytest.mark.parametrize('response,expected', [
    ('## Lesson\nRead this aloud.', 'Lesson\nRead this aloud.'),
    ('## Lesson ##\nRead this aloud.', 'Lesson\nRead this aloud.'),
    ('## Learn C#', 'Learn C#'),
])
def test_script_cleanup_still_removes_markdown_heading_markers(response, expected):
    with patch.object(llm, '_generate_response', return_value=response):
        assert llm.generate_script('lesson') == expected
