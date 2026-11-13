import json
from unittest.mock import patch

from app.services import llm


def test_terms_recovery_stops_after_first_array():
    response = 'Suggested visuals: ["ocean waves", "sailing boat"]\nRelated alternatives: ["beach"]'
    with patch.object(llm, "_generate_response", return_value=response) as provider:
        assert llm.generate_terms("Ocean", "A boat sails.", amount=2) == [
            "ocean waves", "sailing boat"
        ]
    assert provider.call_count == 1


def test_social_recovery_stops_after_first_object():
    metadata = {"title": "Ocean", "caption": "Go sailing", "hashtags": ["#ocean"]}
    response = f'Publishing copy: {json.dumps(metadata)}\nExample settings: {{"temperature": 0.2}}'
    assert llm._parse_social_metadata(response, "tiktok") == metadata
