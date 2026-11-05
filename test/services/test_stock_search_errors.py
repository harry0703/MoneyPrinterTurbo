"""
A failed Pexels or Coverr search must say why in the log: a rejected API key,
a rate limit or an error page. Like the Pixabay search, the log gets the status
and content type, never the response body or the configured key.
"""

import io
from unittest.mock import patch

import pytest
import requests
from loguru import logger

from app.config import config
from app.services import material

SEARCHES = {
    "pexels": material.search_videos_pexels,
    "coverr": material.search_videos_coverr,
}
# What the providers answer to a search with a wrong key.
REJECTED_KEY_BODIES = {
    "pexels": '{"status":401,"code":"Unauthorized","message":"Invalid API key"}',
    "coverr": '{"message":"Invalid API_KEY"}',
}


@pytest.fixture(autouse=True)
def configured_keys(monkeypatch):
    for provider in SEARCHES:
        monkeypatch.setitem(
            config.app, f"{provider}_api_keys", [f"{provider}-secret-key"]
        )


def _response(status, content_type, body, headers=None):
    response = requests.Response()
    response.status_code = status
    response.headers.update({"Content-Type": content_type, **(headers or {})})
    response.raw = io.BytesIO(body.encode("utf-8"))
    return response


def _search(provider, response):
    """Search once against ``response``; return the result and the error log."""
    errors = []
    handler_id = logger.add(
        lambda message: errors.append(message.record["message"]), level="ERROR"
    )
    try:
        with patch.object(material.requests, "get", return_value=response):
            result = SEARCHES[provider]("ocean", 5)
    finally:
        logger.remove(handler_id)
    return result, "\n".join(errors)


@pytest.mark.parametrize("provider", SEARCHES)
def test_rejected_api_key_names_the_key_setting(provider):
    result, log = _search(
        provider,
        _response(
            401, "application/json; charset=utf-8", REJECTED_KEY_BODIES[provider]
        ),
    )
    assert result == []
    assert (
        f"{provider} rejected the API key: status=401. "
        f"Check {provider}_api_keys in config.toml." in log
    )
    assert f"{provider}-secret-key" not in log
    assert "Invalid API" not in log


@pytest.mark.parametrize("provider", SEARCHES)
def test_rate_limit_is_reported_with_retry_after(provider):
    result, log = _search(
        provider,
        _response(
            429, "text/plain; charset=utf-8", "Too Many Requests", {"Retry-After": "60"}
        ),
    )
    assert result == []
    assert f"{provider} API rate limit exceeded: status=429, retry_after=60" in log


@pytest.mark.parametrize("provider", SEARCHES)
def test_error_page_is_reported_without_its_body(provider):
    result, log = _search(
        provider,
        _response(
            403, "text/html; charset=UTF-8", "<html><title>403 Forbidden</title></html>"
        ),
    )
    assert result == []
    assert (
        f"{provider} search request failed: "
        "status=403, content_type=text/html; charset=UTF-8" in log
    )
    assert "<html" not in log
    assert "Expecting value" not in log


@pytest.mark.parametrize("provider", SEARCHES)
def test_non_json_success_response_is_reported(provider):
    result, log = _search(
        provider, _response(200, "text/html; charset=utf-8", "<html>Sign in</html>")
    )
    assert result == []
    assert (
        f"{provider} returned an unexpected non-JSON response: "
        "status=200, content_type=text/html; charset=utf-8" in log
    )
    assert "Expecting value" not in log
