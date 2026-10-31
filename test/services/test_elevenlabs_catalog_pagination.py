import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import requests
from app.services import voice


def test_complete_catalog_uses_real_http_page_token():
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            seen.append((query, self.headers.get('xi-api-key')))
            page = query.get('next_page_token', [''])[0]
            payload = {'voices': [{'voice_id': 'v2' if page else 'v1', 'name': 'Second' if page else 'First'}], 'has_more': not bool(page), 'next_page_token': None if page else 'cursor/with+symbols'}
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    session = requests.Session()
    def local_get(url, **kwargs):
        assert url == 'https://api.elevenlabs.io/v2/voices'
        return session.get(f'http://127.0.0.1:{server.server_port}/voices', **kwargs)
    try:
        with patch.object(voice.requests, 'get', side_effect=local_get):
            assert voice.get_elevenlabs_voices('owned-fixture-key') == ['elevenlabs:v1:First', 'elevenlabs:v2:Second']
        assert seen[1][0]['next_page_token'] == ['cursor/with+symbols']
        assert all(key == 'owned-fixture-key' for _, key in seen)
    finally:
        session.close()
        server.shutdown()
        thread.join(2)
        server.server_close()


def test_repeated_cursor_does_not_loop_or_duplicate_catalog():
    class Response:
        status_code = 200
        def json(self):
            return {'voices': [{'voice_id': 'v1', 'name': 'First'}], 'has_more': True, 'next_page_token': 'same'}
        def close(self):
            pass
    with patch.object(voice.requests, 'get', return_value=Response()) as get:
        assert voice.get_elevenlabs_voices('key') == ['elevenlabs:v1:First']
        assert get.call_count == 2


def test_budget_exhaustion_returns_collected_pages_without_another_request():
    class Response:
        status_code = 200
        def json(self):
            return {'voices': [{'voice_id': 'v1', 'name': 'First'}], 'has_more': True, 'next_page_token': 'next'}
        def close(self):
            pass
    with patch.object(voice.requests, 'get', return_value=Response()) as get, patch.object(voice.time, 'monotonic', side_effect=[100, 101, 131]), patch.object(voice.logger, 'warning') as warning:
        assert voice.get_elevenlabs_voices('key') == ['elevenlabs:v1:First']
        assert get.call_count == 1
        assert get.call_args.kwargs['timeout'] == (10, 10)
        assert 'time budget' in warning.call_args.args[0]


def test_second_page_failure_closes_response_and_discards_partial_catalog():
    from unittest.mock import MagicMock
    first = MagicMock(status_code=200)
    first.json.return_value = {'voices': [{'voice_id': 'v1', 'name': 'First'}], 'has_more': True, 'next_page_token': 'next'}
    for status, malformed in [(503, False), (200, True)]:
        second = MagicMock(status_code=status)
        if malformed:
            second.json.side_effect = ValueError('invalid JSON')
        with patch.object(voice.requests, 'get', side_effect=[first, second]):
            assert voice.get_elevenlabs_voices('key') == []
        second.close.assert_called_once()


def test_page_cap_is_explicit_and_preserves_collected_voices():
    from unittest.mock import MagicMock
    responses = []
    for index in range(100):
        response = MagicMock(status_code=200)
        response.json.return_value = {'voices': [{'voice_id': str(index), 'name': 'Voice'}], 'has_more': True, 'next_page_token': str(index)}
        responses.append(response)
    with patch.object(voice.requests, 'get', side_effect=responses) as get, patch.object(voice.time, 'monotonic', return_value=100), patch.object(voice.logger, 'warning') as warning:
        assert len(voice.get_elevenlabs_voices('key')) == 100
        assert get.call_count == 100
        assert 'page limit' in warning.call_args.args[0]
