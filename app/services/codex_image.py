"""Single-image Codex adapter, sharing the LLM's application authorization."""

import base64
import binascii
from dataclasses import dataclass, field
import json
import math
import time

from app.config import config
from app.services import codex_oauth

MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_RESPONSE_BYTES = 96 * 1024 * 1024
ERROR_MESSAGES = {
    "codex.image.model_required": "Select a Codex Responses model for image generation.",
    "codex.image.invalid_timeout": "The Codex image timeout must be a positive number.",
    "codex.image.invalid_result": "Codex returned no complete valid image. Generation stopped without retrying.",
    "codex.image.uncertain": "The Codex image request did not finish reliably. Generation stopped without retrying.",
    "codex.image.save_failed": "The Codex image could not be saved. Generation stopped without retrying.",
}


class CodexImageError(codex_oauth.CodexError):
    """Sanitized, translatable error; never includes server bodies or image data."""

    def __init__(self, key, **params):
        if key not in ERROR_MESSAGES:
            super().__init__(key, **params)
            return
        self.key = key
        self.params = params
        ValueError.__init__(self, ERROR_MESSAGES[key].format(**params))


@dataclass(frozen=True)
class CodexImageContext:
    model: str
    timeout: float
    generation: int
    session: codex_oauth.CodexSessionBinding | None = field(default=None, repr=False)


def capture_context(app_config=None):
    settings = config.app if app_config is None else app_config
    model = str(settings.get("codex_image_model_name", "") or "").strip()
    if not model:
        raise CodexImageError("codex.image.model_required")
    try:
        timeout = float(settings.get("codex_image_timeout", 300))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        raise CodexImageError("codex.image.invalid_timeout") from None
    generation = codex_oauth.authorization_generation()
    try:
        session = codex_oauth.capture_session_binding()
    except codex_oauth.CodexError as error:
        raise CodexImageError(error.key, **error.params) from None
    context = CodexImageContext(model, timeout, generation, session)
    assert_current(context)
    return context


def assert_current(context):
    if context.generation != codex_oauth.authorization_generation():
        raise CodexImageError("codex.oauth.changed")
    try:
        codex_oauth.assert_session_binding(context.session)
    except codex_oauth.CodexError as error:
        raise CodexImageError(error.key, **error.params) from None


def _final_image(payload):
    if not isinstance(payload, dict) or payload.get("status") != "completed":
        raise CodexImageError("codex.image.invalid_result")
    output = payload.get("output")
    if not isinstance(output, list) or not all(isinstance(i, dict) for i in output):
        raise CodexImageError("codex.image.invalid_result")
    images = [item for item in output if item.get("type") == "image_generation_call"]
    if len(images) != 1 or images[0].get("status") != "completed":
        raise CodexImageError("codex.image.invalid_result")
    encoded = images[0].get("result")
    if (
        not isinstance(encoded, str)
        or not encoded
        or len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3)
    ):
        raise CodexImageError("codex.image.invalid_result")
    try:
        result = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise CodexImageError("codex.image.invalid_result") from None
    if not result or len(result) > MAX_IMAGE_BYTES:
        raise CodexImageError("codex.image.invalid_result")
    return result


def _remember_image(final_items, item, *, done=False):
    status = item.get("status")
    if status not in (None, "completed") or (
        status is None and not done and not final_items
    ):
        raise CodexImageError("codex.image.invalid_result")
    encoded = item.get("result")
    if (
        not isinstance(encoded, str)
        or not encoded
        or len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3)
    ):
        raise CodexImageError("codex.image.invalid_result")
    if final_items:
        previous = final_items[0]
        previous_id, item_id = previous.get("id"), item.get("id")
        # Repeated done events need an explicit identity. Two anonymous calls
        # may produce the same bytes, so equality of results alone is unsafe.
        # A single final output may repeat the already accredited done image.
        same_id = bool(previous_id and item_id and previous_id == item_id)
        conflicting_ids = bool(previous_id and item_id and previous_id != item_id)
        if (done and not same_id) or conflicting_ids or previous["result"] != encoded:
            raise CodexImageError("codex.image.invalid_result")
        return
    # output_item.done itself establishes completion when status is omitted.
    final_items.append(dict(item, status="completed"))


def _event(data, final_items=None):
    if final_items is None:
        final_items = []
    if data == b"[DONE]":
        return None
    try:
        event = json.loads(data)
        if not isinstance(event, dict):
            raise ValueError()
        kind = event.get("type")
        if kind in ("error", "response.failed", "response.incomplete"):
            raise CodexImageError("codex.image.invalid_result")
        if kind == "response.output_item.done":
            item = event.get("item")
            if not isinstance(item, dict):
                raise CodexImageError("codex.image.invalid_result")
            if item.get("type") == "image_generation_call":
                _remember_image(final_items, item, done=True)
                codex_oauth._record_image_diagnostic(
                    kind="image_tool",
                    event=kind,
                    tool_id=item.get("id"),
                    status="completed",
                )
        if kind == "response.completed":
            payload = event.get("response")
            if not isinstance(payload, dict) or payload.get("status") != "completed":
                raise CodexImageError("codex.image.invalid_result")
            output = payload.get("output")
            if not isinstance(output, list) or not all(
                isinstance(i, dict) for i in output
            ):
                raise CodexImageError("codex.image.invalid_result")
            images = [
                item for item in output if item.get("type") == "image_generation_call"
            ]
            if len(images) > 1:
                raise CodexImageError("codex.image.invalid_result")
            if images:
                # A final response may repeat the already completed tool item.
                # Its identity and result must agree, never choose one silently.
                _remember_image(final_items, images[0])
            result = _final_image(dict(payload, output=final_items))
            codex_oauth._record_image_diagnostic(
                kind="response",
                event=kind,
                response_id=payload.get("id"),
                response_model=payload.get("model"),
                status="completed",
            )
            codex_oauth._record_image_diagnostic(
                kind="image_tool",
                event=kind,
                tool_id=final_items[0].get("id"),
                status="completed",
                result_bytes=len(result),
            )
            return result
    except (ValueError, TypeError, UnicodeError):
        raise CodexImageError("codex.image.invalid_result") from None
    return None


def _read_stream(response, deadline):
    # Count raw bytes before buffering a line. iter_lines alone can allocate an
    # unbounded line before the application gets a chance to check its size.
    buffer = bytearray()
    data = []
    final_items = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if time.monotonic() >= deadline:
            raise CodexImageError("codex.image.uncertain")
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise CodexImageError("codex.image.invalid_result")
        buffer.extend(chunk)
        start = 0
        while True:
            end = buffer.find(b"\n", start)
            if end < 0:
                del buffer[:start]
                break
            line = bytes(buffer[start:end]).rstrip(b"\r")
            start = end + 1
            if line.startswith(b"data:"):
                data.append(line[5:].lstrip())
            elif not line and data:
                result = _event(b"\n".join(data), final_items)
                data = []
                if result is not None:
                    return result
    # The final event must be terminated; truncated output is never accepted.
    raise CodexImageError("codex.image.uncertain")


def generate_image(prompt, context):
    assert_current(context)
    payload = {
        "model": context.model,
        "store": False,
        "stream": True,
        "instructions": "Generate exactly one image for the user's prompt using the image generation tool.",
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": prompt}]}
        ],
        "tools": [
            {"type": "image_generation", "action": "generate", "output_format": "png"}
        ],
        "tool_choice": {"type": "image_generation"},
        "parallel_tool_calls": False,
    }
    try:
        result = codex_oauth.request_image(
            payload,
            generation=context.generation,
            session=context.session,
            timeout=context.timeout,
            read_result=_read_stream,
        )
    except codex_oauth.CodexError as error:
        if error.key in ("codex.oauth.network_error", "codex.oauth.timeout"):
            raise CodexImageError("codex.image.uncertain") from None
        raise CodexImageError(error.key, **error.params) from None
    assert_current(context)
    return result
