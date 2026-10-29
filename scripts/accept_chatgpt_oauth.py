"""Manual native OAuth acceptance. Real requests use the selected ChatGPT plan.

Run from a source checkout: python scripts/accept_chatgpt_oauth.py --help
No API key or Codex credentials are used. The report contains allowlisted
diagnostics and synthetic-task output, never tokens or authorization URLs.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loguru import logger  # noqa: E402

from app import paths  # noqa: E402
from app.services import chatgpt_auth as auth, chatgpt_models, chatgpt_oauth, llm  # noqa: E402
from app.utils.logging_utils import set_logging_options  # noqa: E402


class AcceptanceFailure(Exception):
    pass


def _revision():
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            ).stdout
        )
        return {"commit": commit, "dirty": dirty}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def sign_in():
    flow = auth.begin_login()
    try:
        if not webbrowser.open(flow["authorize_url"]):
            raise AcceptanceFailure(
                "Could not open the browser. Sign in using the native provider in WebUI, then rerun without --login."
            )
        print(
            "Complete ChatGPT authorization in the browser. No credentials need to be copied."
        )
        while time.time() < flow["expires_at"]:
            if auth.poll_login(flow):
                return
            time.sleep(0.5)
        raise AcceptanceFailure("Browser authorization did not complete before expiry.")
    finally:
        auth.cancel_login(flow)


def _completed(trace):
    return any(
        item.get("event") == "response.completed" and item.get("status") == "completed"
        for item in trace
    )


def run_acceptance(*, model=None, disconnect=False, login=False, import_preview=False):
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "os": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
            **_revision(),
        },
        "provider": "openai_chatgpt",
        "stages": {},
        "status": "failed",
    }
    stages = report["stages"]
    try:
        if import_preview:
            auth.import_preview_credentials()
        if login:
            sign_in()
        details = auth.account_details()
        stages["authorization"] = {
            "connected": details["connected"],
            "plan_authorized": details["authorized"],
            "browser_flow_performed_this_run": login,
        }
        if not details["authorized"]:
            raise AcceptanceFailure(
                "Authorize an eligible account in the native provider or run with --login. Existing Codex login is separate."
            )
        with chatgpt_oauth.capture_diagnostics() as trace:
            stages["models"] = {"trace": trace}
            catalog = chatgpt_models.get_catalog(force_refresh=True)
        ids = [entry.id for entry in catalog.models]
        stages["models"]["model_ids"] = ids
        selected = model or (ids[0] if ids else None)
        if selected not in ids:
            raise AcceptanceFailure(
                "The requested model is not listed for this account."
            )
        report["selected_model"] = selected
        settings = {
            "llm_provider": "openai_chatgpt",
            "openai_chatgpt_model_name": selected,
            "openai_chatgpt_timeout": "120",
        }
        subject = "A short educational video about taking a walk outdoors"
        script = ""
        for name in ("script", "keywords"):
            with chatgpt_oauth.capture_diagnostics() as trace:
                stages[name] = {"trace": trace, "response_completed": False}
                if name == "script":
                    result = llm.generate_script(
                        subject,
                        language="English",
                        paragraph_number=1,
                        video_script_prompt="Write at most 45 words.",
                        app_config=settings,
                    )
                else:
                    result = llm.generate_terms(
                        subject, script, amount=3, app_config=settings
                    )
            stages[name] = {
                "response_completed": _completed(trace),
                "trace": trace,
                "output": result[:4000] if isinstance(result, str) else result[:10],
            }
            if not result or not _completed(trace):
                raise AcceptanceFailure(
                    f"{name} did not produce a completed response through the native provider."
                )
            if name == "script":
                script = result

        before, session = auth.credentials()
        renewed, renewed_session = auth.credentials(force=True, session=session)
        stages["refresh"] = {
            "succeeded": True,
            "registration_preserved": before["client_id"] == renewed["client_id"],
            "session_preserved": session == renewed_session,
            "refresh_token_rotated": before["refresh_token"]
            != renewed["refresh_token"],
        }
        with chatgpt_oauth.capture_diagnostics() as trace:
            stages["after_refresh"] = {"trace": trace, "response_completed": False}
            refreshed_text = chatgpt_oauth.generate_text(
                "Reply exactly: OAuth refresh OK", selected, 120
            )
        stages["after_refresh"] = {
            "response_completed": _completed(trace),
            "trace": trace,
            "output": refreshed_text[:4000],
        }
        if not _completed(trace):
            raise AcceptanceFailure("The post-refresh request did not complete.")
        if disconnect:
            confirmed = auth.disconnect()
            with chatgpt_oauth.capture_diagnostics() as trace:
                try:
                    chatgpt_oauth.generate_text(
                        "This request must be blocked after sign-out.", selected, 10
                    )
                except auth.ChatGPTError as error:
                    blocked = error.key == "chatgpt.oauth.not_connected"
                else:
                    blocked = False
            # Only booleans are copied out of the protected store.
            with auth._store_lock():
                stored = auth._load()
                active = stored["profiles"].get(stored["active"], {})
                cleared = all(
                    not active.get(key)
                    for key in ("access_token", "refresh_token", "id_token")
                )
            stages["disconnect"] = {
                "remote_revocation_confirmed": confirmed,
                "local_tokens_cleared": cleared,
                "signed_out_request_blocked": blocked,
                "inference_requests_after_signout": len(trace),
            }
            if not (confirmed and cleared and blocked and not trace):
                raise AcceptanceFailure(
                    "Disconnect acceptance is incomplete; inspect the reported booleans."
                )
        else:
            stages["disconnect"] = {
                "skipped": True,
                "reason": "Run with --disconnect to verify sign-out.",
            }
        report["status"] = "passed" if login and disconnect else "partial"
    except auth.ChatGPTError as error:
        report["error"] = {"code": error.key}
    except AcceptanceFailure as error:
        report["error"] = {"message": str(error)}
    except Exception as error:
        # Never include raw network errors, request objects or token responses.
        report["error"] = {"type": type(error).__name__}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--login",
        action="store_true",
        help="Open local browser authorization before testing",
    )
    parser.add_argument(
        "--import-preview",
        action="store_true",
        help="Copy this PR's v2 preview store into the separate native store; retain source",
    )
    parser.add_argument(
        "--disconnect",
        action="store_true",
        help="Revoke and clear the native session after successful inference tests",
    )
    parser.add_argument(
        "--model", help="Account-listed model ID; defaults to the first returned model"
    )
    parser.add_argument(
        "--output", type=Path, help="Destination for the sanitized JSON report"
    )
    args = parser.parse_args()
    set_logging_options("ERROR", False)
    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    report = run_acceptance(
        model=args.model,
        disconnect=args.disconnect,
        login=args.login,
        import_preview=args.import_preview,
    )
    output = args.output or paths.runtime_root() / "storage" / "acceptance" / (
        "chatgpt-native-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Acceptance: {report['status']}; report: {output.resolve()}")
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
