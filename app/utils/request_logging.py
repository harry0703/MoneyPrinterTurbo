"""可选的请求参数追踪；不读取响应正文，不改变重试或网络传输行为。"""

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
_SECRET_KEY = re.compile(
    r"authorization|cookie|password|passwd|secret|credential|signature|"
    r"apikey|accesskey|privatekey|clientkey|devicecode|usercode|authorizationcode|"
    r"(?:access|refresh|id|auth|api|bearer)token"
)
_TOKEN = re.compile(
    r"\b(?:sk|rk|sess|ghp|github_pat)[-_][A-Za-z0-9_-]{8,}|"
    r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
)
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
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
    """查询参数全部遮盖，避免漏掉供应商自定义的签名字段。"""
    try:
        parts = urlsplit(value)
        netloc = parts.netloc.rsplit("@", 1)[-1]
        query = urlencode([(k, _REDACTED) for k, _ in parse_qsl(parts.query)])
        return _TOKEN.sub(
            _REDACTED, urlunsplit((parts.scheme, netloc, parts.path, query, ""))
        )[:_MAX_STRING]
    except ValueError:
        return "[invalid URL]"


def _safe_string(value: str) -> str:
    if value.lstrip().lower().startswith("data:"):
        return "[media omitted]"
    if len(value) >= 256 and re.fullmatch(r"[A-Za-z0-9+/=\r\n]+", value):
        return "[base64 omitted]"
    value = _TOKEN.sub(_REDACTED, value)
    value = _URL.sub(lambda match: _safe_url(match.group()), value)
    return value[:_MAX_STRING] + ("… [truncated]" if len(value) > _MAX_STRING else "")


def _safe_query_params(value):
    """与 URL 内的 query 保持一致，遮盖所有值，兼容 requests 的参数格式。"""
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
    """限制深度、节点数和文本长度；未知对象只记录类型，不调用其 repr。"""
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
    # 诊断失败不能阻断付费提交、污染业务异常或触发额外重试。
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
    # 不访问 .content/.text/.json()，避免提前消耗 SSE、音频和大文件下载。
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
    """包装项目显式发出的 requests 请求，原参数和返回对象保持不变。"""
    payload = {
        key: kwargs[key] for key in ("params", "json", "data", "files") if key in kwargs
    }
    # 原始表单/二进制正文不能可靠按字段脱敏，只允许查看结构化参数。
    if "data" in payload and not isinstance(payload["data"], Mapping):
        payload["data"] = "[raw body omitted]"
    if method.upper() == "REQUEST":
        # Session.request 的第一个位置参数是 method，第二个才是 URL。
        method, url, args = url, args[0], args[1:]
        return _trace_call(
            "http", method, url, payload, send, method, url, *args, **kwargs
        )
    return _trace_call("http", method, url, payload, send, url, *args, **kwargs)


def trace_sdk_call(provider, endpoint, send, **kwargs):
    """记录 SDK 调用参数；不声称覆盖 SDK 内部重试或其最终 wire JSON。"""
    return _trace_call("sdk", provider, endpoint, kwargs, send, **kwargs)
