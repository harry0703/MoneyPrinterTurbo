"""Existing Codex provider, now using official ChatGPT plan authorization."""

from contextlib import contextmanager
import json
import time

import requests

from app.services import chatgpt_auth as auth

RESPONSES_URL = auth.RESOURCE + "/responses"
MODELS_URL = auth.RESOURCE + "/models"
ERROR_MESSAGES = auth.ERROR_MESSAGES
CodexError = auth.CodexError
USAGE_URL = auth.USAGE_URL
account_status = auth.account_status
account_details = auth.account_details
select_account = auth.select_account
begin_login = auth.begin_login
poll_login = auth.poll_login
cancel_login = auth.cancel_login
disconnect = auth.disconnect


def _provider_error(error):
    code = error.get("code", "") if isinstance(error, dict) else ""
    if code == "subscription_sharing_usage_limit_exceeded":
        return CodexError("rate_limit")
    if code in {
        "subscription_sharing_usage_unavailable",
        "subscription_sharing_user_unavailable",
    }:
        return CodexError("network_error")
    if code in {
        "chatpass_v2_scope_not_authorized",
        "chatpass_v2_invalid_authorization_context",
    }:
        return CodexError("plan_required")
    return CodexError("incomplete")


@contextmanager
def _authorized_request(method, url, timeout, **kwargs):
    deadline = time.monotonic() + timeout
    credentials, session = auth.credentials()
    for attempt in range(2):
        auth.assert_session(session)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CodexError("timeout")
        try:
            with requests.request(
                method,
                url,
                timeout=(min(15, remaining), remaining),
                allow_redirects=False,
                headers={
                    "Authorization": "Bearer " + credentials["access_token"],
                    "Accept": "text/event-stream"
                    if kwargs.get("stream")
                    else "application/json",
                },
                **kwargs,
            ) as response:
                if response.status_code == 401 and attempt == 0:
                    credentials, _ = auth.credentials(
                        force=True,
                        expected=credentials["access_token"],
                        session=session,
                    )
                    continue
                if response.status_code == 429:
                    raise CodexError("rate_limit")
                if response.status_code == 401:
                    raise CodexError("reconnect")
                if response.status_code >= 500:
                    raise CodexError("network_error")
                if response.status_code != 200:
                    raise CodexError("http_error", status=response.status_code)
                response.encoding = "utf-8"
                yield response, deadline
                auth.assert_session(session)
                return
        except requests.Timeout:
            raise CodexError("timeout") from None
        except requests.RequestException:
            raise CodexError("network_error") from None
    raise CodexError("reconnect")


def get_models():
    with _authorized_request("GET", MODELS_URL, 30) as (response, _):
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError()
            return payload
        except ValueError:
            raise CodexError("invalid_response") from None


def _final_text(payload):
    if payload.get("status") != "completed":
        raise CodexError("incomplete")
    pieces = []
    for item in payload.get("output", []):
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text" and isinstance(
                    part.get("text"), str
                ):
                    pieces.append(part["text"])
    result = "\n".join(pieces).strip()
    if not result:
        raise CodexError("empty")
    return result


def _stream_event(data, text_parts=None):
    if data == "[DONE]":
        return None
    try:
        event = json.loads(data)
        if not isinstance(event, dict):
            raise ValueError()
        kind = event.get("type")
        if text_parts is not None and kind in {
            "response.output_text.delta",
            "response.output_text.done",
        }:
            output_index = event.get("output_index", 0)
            content_index = event.get("content_index", 0)
            if not all(
                isinstance(index, int) and index >= 0
                for index in (output_index, content_index)
            ):
                raise ValueError()
            key = (output_index, content_index)
            text = event.get("delta" if kind.endswith(".delta") else "text")
            if not isinstance(text, str):
                raise ValueError()
            text_parts[key] = (
                text_parts.get(key, "") + text if kind.endswith(".delta") else text
            )
        if kind in ("error", "response.failed", "response.incomplete"):
            raise _provider_error(
                event.get("error") or event.get("response", {}).get("error")
            )
        if kind == "response.completed":
            response = event.get("response", {})
            # The public plan route may finish with output=[] after sending the
            # text in output_text events. Keep that text private until completion.
            try:
                return _final_text(response)
            except CodexError as error:
                if error.key != "codex.oauth.empty" or not text_parts:
                    raise
                result = "\n".join(
                    text_parts[key] for key in sorted(text_parts)
                ).strip()
                if not result:
                    raise
                return result
    except CodexError:
        raise
    except (ValueError, TypeError, AttributeError):
        raise CodexError("invalid_response") from None
    return None


def _read_stream(response, deadline):
    data, size = [], 0
    text_parts = {}
    for line in response.iter_lines(decode_unicode=True):
        if time.monotonic() >= deadline:
            raise CodexError("timeout")
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        size += len(line)
        if size > 8 * 1024 * 1024:
            raise CodexError("invalid_response")
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line and data:
            result = _stream_event("\n".join(data), text_parts)
            data = []
            if result is not None:
                return result
    if data:
        result = _stream_event("\n".join(data), text_parts)
        if result is not None:
            return result
    raise CodexError("incomplete")


def generate_text(prompt, model, timeout=300):
    with _authorized_request(
        "POST",
        RESPONSES_URL,
        timeout,
        stream=True,
        json={
            "model": model,
            "store": False,
            "stream": True,
            "instructions": "Follow the requested language and output format exactly. Return only the requested text.",
            "input": [
                {"role": "user", "content": [{"type": "input_text", "text": prompt}]}
            ],
        },
    ) as (response, deadline):
        return _read_stream(response, deadline)
