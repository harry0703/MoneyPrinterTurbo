"""Optional request parameter tracing; never reads response bodies or changes retry or network transport behavior."""

import json
import re
from collections.abc import Mapping
from itertools import islice
from time import perf_counter
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel

from app.utils.logging_utils import get_logging_options


_REDACTED = "[REDACTED]"
_MAX_STRING = 1000
_MAX_PAYLOAD = 12000
# Credential field names are always masked. Session identifiers in device login flows are credentials too: Kimi uses
# ``device_code`` and Codex uses ``device_auth_id``, and both must stay out of the logs.
_SECRET_KEY = re.compile(
    r"authorization|cookie|password|passwd|secret|credential|signature|"
    r"apikey|accesskey|privatekey|clientkey|devicecode|deviceauthid|usercode|"
    r"authorizationcode|(?:access|refresh|id|auth|api|bearer)token"
)
_TOKEN = re.compile(
    r"\b(?:sk|rk|sess|ghp|github_pat)[-_][A-Za-z0-9_-]{8,}|"
    r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
)
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
# Some providers put the account email inside ids (useapi.net job and media
# ids, for example), in URL paths and in request bodies; traces must not reveal it.
_EMAIL = re.compile(
    r"[A-Za-z0-9._%+*-]+(?:@|%40)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}",
    re.IGNORECASE,
)
_MEDIA_KEYS = frozenset(
    {
        "audio",
        "audiodata",
        "audiobase64",
        "base64",
        "b64json",
        "bytes",
        "file",
        "files",
        "filedata",
        "image",
        "imagedata",
        "imagebase64",
        "video",
    }
)


def _safe_url(value: str) -> str:
    """Mask all query parameters, so provider-specific signature fields aren't missed."""
    try:
        parts = urlsplit(value)
        netloc = parts.netloc.rsplit("@", 1)[-1]
        query = urlencode([(k, _REDACTED) for k, _ in parse_qsl(parts.query)])
        path = _EMAIL.sub(_REDACTED, parts.path)
        return _TOKEN.sub(
            _REDACTED, urlunsplit((parts.scheme, netloc, path, query, ""))
        )[:_MAX_STRING]
    except ValueError:
        return "[invalid URL]"


def _safe_string(value: str) -> str:
    if value.lstrip().lower().startswith("data:"):
        return "[media omitted]"
    if len(value) >= 256 and re.fullmatch(r"[A-Za-z0-9+/=\r\n]+", value):
        return "[base64 omitted]"
    value = _TOKEN.sub(_REDACTED, value)
    value = _EMAIL.sub(_REDACTED, value)
    value = _URL.sub(lambda match: _safe_url(match.group()), value)
    return value[:_MAX_STRING] + ("… [truncated]" if len(value) > _MAX_STRING else "")


def _safe_query_params(value):
    """Mask all values, consistent with queries in URLs and compatible with requests' parameter formats."""
    if isinstance(value, Mapping):
        return {_safe_string(str(key)): _REDACTED for key in islice(value, 30)}
    if isinstance(value, (list, tuple)):
        return [
            [_safe_string(str(pair[0])), _REDACTED]
            for pair in value[:30]
            if isinstance(pair, (list, tuple)) and len(pair) == 2
        ]
    return "[query values omitted]"


def sanitize_payload(value):
    """Limit depth, node count and text length; unknown objects only have their type logged, without calling their repr."""
    remaining = 100

    def visit(item, depth=0):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 6:
            return "[truncated]"
        if isinstance(item, Mapping):
            result = {}
            for index, (key, child) in enumerate(item.items()):
                if index >= 30 or remaining <= 0:
                    result["…"] = "[truncated]"
                    break
                key = str(key)
                normalized = re.sub(r"[^a-z0-9]", "", key.lower())
                if normalized in {
                    "key",
                    "token",
                    "headers",
                    "cookies",
                    "code",
                    "codeverifier",
                    "nonce",
                } or _SECRET_KEY.search(normalized):
                    result[_safe_string(key)] = _REDACTED
                elif normalized in {"params", "extraquery", "queryparams"}:
                    result[_safe_string(key)] = _safe_query_params(child)
                elif normalized in _MEDIA_KEYS:
                    result[_safe_string(key)] = "[media omitted]"
                else:
                    result[_safe_string(key)] = visit(child, depth + 1)
            return result
        if isinstance(item, (list, tuple)):
            return [visit(child, depth + 1) for child in item[:10]] + (
                ["[truncated]"] if len(item) > 10 else []
            )
        if isinstance(item, str):
            return _safe_string(item)
        if isinstance(item, BaseModel):
            return visit(item.model_dump(mode="json", exclude_none=True), depth + 1)
        if item is None or isinstance(item, (bool, int, float)):
            return item
        return f"[{type(item).__name__} omitted]"

    return visit(value)


def _emit(event: dict) -> None:
    # A diagnostics failure must not block paid submissions, pollute business exceptions or trigger extra retries.
    try:
        logger.bind(request_trace=True).info(
            "request_trace {}", json.dumps(event, ensure_ascii=False)
        )
    except Exception:
        pass


def _trace_call(kind, method, endpoint, payload, send, *args, **kwargs):
    if not get_logging_options()[1]:
        return send(*args, **kwargs)
    trace_id = uuid4().hex[:12]
    try:
        parameters = sanitize_payload(payload)
        summary = json.dumps(parameters, ensure_ascii=False)
        _emit(
            {
                "event": "request",
                "id": trace_id,
                "kind": kind,
                "method": method,
                "endpoint": _safe_url(str(endpoint)),
                "parameters": parameters
                if len(summary) <= _MAX_PAYLOAD
                else summary[:_MAX_PAYLOAD],
                "truncated": len(summary) > _MAX_PAYLOAD,
            }
        )
    except Exception:
        pass
    started = perf_counter()
    try:
        response = send(*args, **kwargs)
    except Exception as exc:
        _emit(
            {
                "event": "error",
                "id": trace_id,
                "error_type": type(exc).__name__,
                "elapsed_ms": round((perf_counter() - started) * 1000, 1),
            }
        )
        raise
    # .content/.text/.json() aren't accessed, so SSE, audio and large file downloads aren't consumed early.
    try:
        status = getattr(response, "status_code", None)
    except Exception:
        status = None
    _emit(
        {
            "event": "response",
            "id": trace_id,
            "status": status if isinstance(status, int) else None,
            "elapsed_ms": round((perf_counter() - started) * 1000, 1),
        }
    )
    return response


def trace_http_call(method, send, url, *args, **kwargs):
    """Wrap requests explicitly made by the project, leaving the original arguments and return object unchanged."""
    payload = {
        key: kwargs[key] for key in ("params", "json", "data", "files") if key in kwargs
    }
    # Raw form/binary bodies can't be reliably redacted per field, so only structured parameters may be inspected.
    if "data" in payload and not isinstance(payload["data"], Mapping):
        payload["data"] = "[raw body omitted]"
    if method.upper() == "REQUEST":
        # The first positional argument of Session.request is method; the second is the URL.
        method, url, args = url, args[0], args[1:]
        return _trace_call(
            "http", method, url, payload, send, method, url, *args, **kwargs
        )
    return _trace_call("http", method, url, payload, send, url, *args, **kwargs)


def trace_sdk_call(provider, endpoint, send, **kwargs):
    """Log SDK call parameters; doesn't claim to cover the SDK's internal retries or its final wire JSON."""
    return _trace_call("sdk", provider, endpoint, kwargs, send, **kwargs)
