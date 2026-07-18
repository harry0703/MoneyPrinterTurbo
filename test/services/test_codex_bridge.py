from unittest.mock import Mock
import traceback

import pytest
import requests

from app.services import codex_bridge


def test_normalize_timeout_defaults_invalid_values_and_bounds_valid_numbers() -> None:
    assert codex_bridge.normalize_timeout("invalid") == 300
    assert codex_bridge.normalize_timeout(True) == 300
    assert codex_bridge.normalize_timeout(1) == 30
    assert codex_bridge.normalize_timeout(1_000) == 900
    assert codex_bridge.normalize_timeout(45) == 45


def test_generate_sends_authenticated_bounded_request(monkeypatch: pytest.MonkeyPatch) -> None:
    response = Mock(ok=True)
    response.json.return_value = {"output_text": "narration"}
    post = Mock(return_value=response)
    monkeypatch.setattr(codex_bridge.requests, "post", post)

    assert (
        codex_bridge.generate(
            "http://host.docker.internal:9876/", "secret", "rules", "episode", "", 300
        )
        == "narration"
    )
    assert post.call_args.args == ("http://host.docker.internal:9876/v1/generate",)
    assert post.call_args.kwargs == {
        "headers": {"Authorization": "Bearer secret"},
        "json": {
            "instructions": "rules",
            "input": "episode",
            "model": "",
            "timeout_seconds": 300,
        },
        "timeout": (10, 300),
    }


def test_generate_requires_a_bridge_token(monkeypatch: pytest.MonkeyPatch) -> None:
    post = Mock()
    monkeypatch.setattr(codex_bridge.requests, "post", post)

    with pytest.raises(codex_bridge.CodexBridgeError, match="bridge token is required"):
        codex_bridge.generate("http://bridge", "", "rules", "episode")

    post.assert_not_called()


def test_generate_sanitizes_remote_error(monkeypatch: pytest.MonkeyPatch) -> None:
    response = Mock(ok=False, status_code=401)
    response.json.return_value = {
        "error": {"code": "unauthorized", "message": "Invalid bridge token"}
    }
    monkeypatch.setattr(codex_bridge.requests, "post", Mock(return_value=response))

    with pytest.raises(codex_bridge.CodexBridgeError, match="Invalid bridge token") as error:
        codex_bridge.generate("http://bridge", "secret", "rules", "episode")

    assert "secret" not in str(error.value)


def test_generate_maps_remote_errors_without_disclosing_remote_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinels = {
        "instructions": "INSTRUCTIONS_SENTINEL",
        "input": "EPISODE_SENTINEL",
        "model": "MODEL_SENTINEL",
        "token": "TOKEN_SENTINEL",
        "userinfo": "USERNAME_SENTINEL",
    }
    response = Mock(ok=False, status_code=401)
    response.json.return_value = {
        "error": {
            "code": "unauthorized",
            "message": (
                f"{sentinels['instructions']} {sentinels['input']} {sentinels['model']} "
                f"{sentinels['token']} http://{sentinels['userinfo']}@bridge"
            ),
        }
    }
    monkeypatch.setattr(codex_bridge.requests, "post", Mock(return_value=response))

    with pytest.raises(codex_bridge.CodexBridgeError) as error:
        codex_bridge.generate(
            f"http://{sentinels['userinfo']}@bridge",
            sentinels["token"],
            sentinels["instructions"],
            sentinels["input"],
            sentinels["model"],
        )

    rendered_error = "".join(
        traceback.format_exception(error.type, error.value, error.tb)
    )
    assert str(error.value) == "Invalid bridge token."
    for sentinel in sentinels.values():
        assert sentinel not in str(error.value)
        assert sentinel not in rendered_error


def test_safe_message_redacts_username_only_url_userinfo() -> None:
    assert codex_bridge._safe_message("http://username@bridge/path") == "http://***@bridge/path"


@pytest.mark.parametrize("payload", [None, [], {}, {"output_text": None}, {"output_text": "   "}])
def test_generate_rejects_invalid_or_empty_success_payloads(
    monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    response = Mock(ok=True)
    response.json.return_value = payload
    monkeypatch.setattr(codex_bridge.requests, "post", Mock(return_value=response))

    with pytest.raises(codex_bridge.CodexBridgeError, match="invalid response"):
        codex_bridge.generate("http://bridge", "secret", "rules", "episode")


def test_generate_rejects_oversized_output(monkeypatch: pytest.MonkeyPatch) -> None:
    response = Mock(ok=True)
    response.json.return_value = {"output_text": "x" * 131_073}
    monkeypatch.setattr(codex_bridge.requests, "post", Mock(return_value=response))

    with pytest.raises(codex_bridge.CodexBridgeError, match="invalid response"):
        codex_bridge.generate("http://bridge", "secret", "rules", "episode")


def test_generate_uses_stable_message_for_request_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        codex_bridge.requests,
        "post",
        Mock(
            side_effect=requests.ConnectionError(
                "http://username:password@bridge/v1/generate request body: episode"
            )
        ),
    )

    with pytest.raises(codex_bridge.CodexBridgeError) as error:
        codex_bridge.generate("http://username:password@bridge", "secret", "rules", "episode")

    assert str(error.value) == "Codex bridge request failed."
    assert error.value.__cause__ is None


def test_generate_uses_stable_message_for_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(codex_bridge.requests, "post", Mock(side_effect=requests.Timeout()))

    with pytest.raises(codex_bridge.CodexBridgeError) as error:
        codex_bridge.generate("http://bridge", "secret", "rules", "episode")

    assert str(error.value) == "Codex bridge request timed out."


def test_health_returns_validated_health_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    response = Mock(ok=True)
    response.json.return_value = {"status": "ok", "codex_available": True}
    get = Mock(return_value=response)
    monkeypatch.setattr(codex_bridge.requests, "get", get)

    assert codex_bridge.health("http://bridge/") == {
        "status": "ok",
        "codex_available": True,
    }
    assert get.call_args.args == ("http://bridge/health",)
    assert get.call_args.kwargs == {"timeout": (10, 10)}


def test_health_rejects_invalid_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    response = Mock(ok=True)
    response.json.return_value = {"status": "ok", "codex_available": "yes"}
    monkeypatch.setattr(codex_bridge.requests, "get", Mock(return_value=response))

    with pytest.raises(codex_bridge.CodexBridgeError, match="invalid response"):
        codex_bridge.health("http://bridge")
