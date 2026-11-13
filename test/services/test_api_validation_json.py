import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator

from app import asgi
from app.config import config


@pytest.mark.parametrize('number', ['NaN', 'Infinity', '-Infinity'])
@pytest.mark.parametrize('path,field', [('/api/v1/videos', 'n_threads'), ('/api/v1/terms', 'amount')])
def test_rejected_nonfinite_json_numbers_return_validation_response(number, path, field):
    with (
        patch.dict(config.app, {'api_key': ''}),
        patch('app.controllers.v1.video.task_manager.add_task') as schedule,
        patch('app.controllers.v1.llm.llm.generate_terms') as generate,
        TestClient(asgi.get_application(), raise_server_exceptions=False) as client,
    ):
        response = client.post(
            path,
            content='{"video_subject":"test","' + field + '":' + number + '}',
            headers={'content-type': 'application/json'},
        )
    assert response.status_code == 400
    body = response.json()
    assert body['status'] == 400
    assert body['data'][0]['loc'] == ['body', field]
    json.dumps(body, allow_nan=False)
    schedule.assert_not_called()
    generate.assert_not_called()


def test_validator_exception_context_is_serializable():
    class Parameters(BaseModel):
        value: str

        @field_validator('value')
        @classmethod
        def reject_value(cls, value):
            raise ValueError('invalid custom value')

    instance = FastAPI()
    instance.add_exception_handler(RequestValidationError, asgi.validation_exception_handler)

    @instance.post('/validate')
    def validate(params: Parameters):
        return params.model_dump()

    response = TestClient(instance, raise_server_exceptions=False).post('/validate', json={'value': 'x'})
    assert response.status_code == 400
    assert response.json()['data'][0]['ctx']['error'] == 'invalid custom value'


def test_normal_error_details_remain_available():
    instance = asgi.get_application()
    with patch.dict(config.app, {'api_key': ''}):
        response = TestClient(instance).post('/api/v1/terms', json={'amount': 0})
    assert response.status_code == 400
    error = response.json()['data'][0]
    assert error['type'] == 'greater_than_equal'
    assert error['input'] == 0
    assert error['ctx'] == {'ge': 1}


def test_unsafe_font_name_returns_403_not_400():
    """create_task pre-checks font_name via the file-serving wrapper.

    Path-escaping attempts must be rejected with the same 403 that the
    artifact endpoints already use, instead of the generic 400 returned
    for value errors such as invalid subtitle colors.
    """
    payload = {
        'video_subject': 'unsafe font test',
        'video_script': 'demo',
        'subtitle_enabled': True,
        'font_name': '../etc/passwd',
    }
    with (
        patch.dict(config.app, {'api_key': ''}),
        patch('app.controllers.v1.video.task_manager.add_task') as schedule,
        TestClient(asgi.get_application(), raise_server_exceptions=False) as client,
    ):
        response = client.post('/api/v1/videos', json=payload)
    assert response.status_code == 403, response.text
    schedule.assert_not_called()


def test_unknown_font_name_returns_404():
    """A font_name that is well-formed but missing on disk is a 404, not a 400."""
    payload = {
        'video_subject': 'unknown font test',
        'video_script': 'demo',
        'subtitle_enabled': True,
        'font_name': 'this-font-does-not-exist.ttf',
    }
    with (
        patch.dict(config.app, {'api_key': ''}),
        patch('app.controllers.v1.video.task_manager.add_task') as schedule,
        TestClient(asgi.get_application(), raise_server_exceptions=False) as client,
    ):
        response = client.post('/api/v1/videos', json=payload)
    assert response.status_code == 404, response.text
    schedule.assert_not_called()


def test_valid_font_name_still_reaches_scheduler():
    """A safe font_name must still pass through to the task scheduler.

    The fixture writes a real file into a temp font directory and points
    ``utils.font_dir`` at it, so the pre-check passes because the font
    actually exists on disk — not because the check was bypassed or the
    repo's bundled fonts happen to be present.
    """
    payload = {
        'video_subject': 'safe font test',
        'video_script': 'demo',
        'subtitle_enabled': True,
        'font_name': 'custom.ttf',
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        font_dir = Path(temp_dir, 'fonts')
        font_dir.mkdir()
        (font_dir / 'custom.ttf').write_bytes(b'font file')
        with (
            patch.dict(config.app, {'api_key': ''}),
            patch('app.controllers.v1.video.utils.font_dir', return_value=str(font_dir)),
            patch('app.controllers.v1.video.task_manager.add_task') as schedule,
            TestClient(asgi.get_application(), raise_server_exceptions=False) as client,
        ):
            response = client.post('/api/v1/videos', json=payload)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 200
    schedule.assert_called_once()
