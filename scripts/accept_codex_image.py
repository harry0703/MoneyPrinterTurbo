"""Opt-in live acceptance of the normal Codex image material path.

Requires an existing application Codex sign-in. One image is requested using the
explicit model; the same PNG is rendered twice. No model fallback is attempted.
"""

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import math
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loguru import logger  # noqa: E402
from moviepy import VideoFileClip  # noqa: E402
from PIL import Image  # noqa: E402

from app.services import codex_image, codex_oauth, material  # noqa: E402
from app.utils import utils  # noqa: E402
from app.utils.logging_utils import set_logging_options  # noqa: E402

PROMPT = "An ancient Egyptian limestone pyramid in a desert at sunrise, documentary illustration, no text"
PLANS = ("unknown", "free", "plus", "pro", "business", "enterprise", "edu")
TRACE_FIELDS = {
    "http": {"kind", "status", "request_id", "requested_model", "attempt"},
    "response": {"kind", "event", "status", "response_id", "response_model"},
    "image_tool": {"kind", "event", "tool_id", "status", "result_bytes"},
    "provider_error": {"kind", "error_type", "error_code", "error_param", "reason"},
}


class AcceptanceFailure(Exception):
    """A fixed diagnostic code, never a remote body or arbitrary error text."""


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


def _package_version(name):
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _ffmpeg_version():
    try:
        output = subprocess.run(
            [utils.get_ffmpeg_binary(), "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=True,
        ).stdout
        match = re.match(r"ffmpeg version ([A-Za-z0-9._+-]{1,100})(?:\s|$)", output)
        return match[1] if match else None
    except (OSError, subprocess.SubprocessError):
        return None


def _trace(records):
    # The service already sanitizes values. Copy only its documented diagnostic
    # schema so future debug fields cannot silently enter an acceptance report.
    return [
        {key: value for key, value in record.items() if key in TRACE_FIELDS[kind]}
        for record in records
        if isinstance(record, dict) and (kind := record.get("kind")) in TRACE_FIELDS
    ]


def _file_evidence(path):
    path = Path(path)
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _probe_video(path):
    with VideoFileClip(str(path), audio=False) as clip:
        frame = clip.get_frame(0)
        duration = float(clip.duration)
        if (
            not math.isfinite(duration)
            or not 1.5 <= duration <= 2.5
            or frame.ndim != 3
            or min(frame.shape[:2]) < 1
        ):
            raise AcceptanceFailure("invalid_rendered_video")
        return {
            **_file_evidence(path),
            "duration_seconds": round(duration, 4),
            "width": int(frame.shape[1]),
            "height": int(frame.shape[0]),
            "first_frame_decoded": True,
        }


def _render_probe_worker():
    """Internal subprocess entry: no credentials and no generation request."""
    set_logging_options("ERROR", False)
    logger.remove()
    path = material._render_openai_image_video(sys.argv[1], 2, image_motion=sys.argv[2])
    if not path:
        raise SystemExit(1)
    print(json.dumps(_probe_video(path)))


def _render_and_probe(image_path, motion):
    # MoviePy rendering and its decoding probe run in a bounded child. Timeout
    # stops this acceptance run; it never triggers another remote image order.
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "from scripts.accept_codex_image import _render_probe_worker; _render_probe_worker()",
                str(image_path),
                motion,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=True,
        )
    except subprocess.TimeoutExpired:
        raise AcceptanceFailure("render_timeout") from None
    except (OSError, subprocess.SubprocessError):
        raise AcceptanceFailure("render_failed") from None
    try:
        result = json.loads(completed.stdout)
        if not isinstance(result, dict) or not result.get("first_frame_decoded"):
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise AcceptanceFailure("invalid_rendered_video") from None


def run_acceptance(
    *, model, output_dir, confirm_image_generation=False, plan="unknown", timeout=300
):
    """Return a sanitized report; never fall back, log in, or regenerate."""
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "os": platform.system(),
            "release": platform.release(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "ffmpeg": _ffmpeg_version(),
            "packages": {
                name: _package_version(name)
                for name in ("requests", "Pillow", "moviepy", "imageio-ffmpeg")
            },
            **_revision(),
        },
        "provider": "codex_image",
        "endpoint": codex_oauth.RESPONSES_URL,
        "requested_model": None,
        "self_reported_plan": plan if plan in PLANS else "unknown",
        "account_access_verified": False,
        "normal_material_path": "capture_context -> generate_images_codex -> request_image",
        "trace": [],
        "status": "failed",
    }
    records = []
    try:
        if not confirm_image_generation:
            raise AcceptanceFailure("explicit_generation_confirmation_required")
        if (
            not isinstance(model, str)
            or not re.fullmatch(r"[A-Za-z0-9._-]{1,160}", model)
            or model.lower().startswith("sk-")
            or model.startswith("eyJ")
        ):
            raise AcceptanceFailure("explicit_responses_model_required")
        report["requested_model"] = model
        context = codex_image.capture_context(
            {"codex_image_model_name": model, "codex_image_timeout": timeout}
        )
        report["timeout_seconds"] = context.timeout
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        with codex_oauth.capture_image_diagnostics() as records:
            items = material.generate_images_codex(
                PROMPT, 2, "16:9", str(output_dir), context=context
            )
        report["trace"] = _trace(records)
        if len(items) != 1:
            raise AcceptanceFailure("expected_one_material")
        completed = any(
            record.get("kind") == "response"
            and record.get("event") == "response.completed"
            and record.get("status") == "completed"
            for record in report["trace"]
        )
        tool_completed = any(
            record.get("kind") == "image_tool"
            and record.get("status") == "completed"
            and isinstance(record.get("result_bytes"), int)
            and record["result_bytes"] > 0
            for record in report["trace"]
        )
        if not completed or not tool_completed:
            raise AcceptanceFailure("completed_image_evidence_missing")
        png = Path(items[0].url)
        with Image.open(png) as image:
            image.load()
            if image.format != "PNG":
                raise AcceptanceFailure("expected_png_material")
            report["image"] = {
                **_file_evidence(png),
                "format": image.format,
                "width": image.width,
                "height": image.height,
                "decoded": True,
            }
        report["account_access_verified"] = True
        report["renders"] = {}
        for motion in ("static", "zoom"):
            codex_image.assert_current(context)
            report["renders"][motion] = _render_and_probe(png, motion)
            codex_image.assert_current(context)
        report["status"] = "passed"
    except codex_oauth.CodexError as error:
        report["error"] = {"code": error.key}
        if isinstance(error.params.get("status"), int):
            report["error"]["http_status"] = error.params["status"]
    except material.CodexImageMaterialError as error:
        report["error"] = {"code": error.key}
        if isinstance(error.params.get("status"), int):
            report["error"]["http_status"] = error.params["status"]
    except AcceptanceFailure as error:
        report["error"] = {"code": str(error)}
    except Exception as error:
        report["error"] = {"code": "unexpected_error", "type": type(error).__name__}
    finally:
        report["trace"] = _trace(records)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", required=True, help="Exact Responses model ID; no fallback"
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="Sanitized JSON report"
    )
    parser.add_argument(
        "--plan",
        choices=PLANS,
        default="unknown",
        help="Self-reported plan, not verified entitlement",
    )
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument(
        "--confirm-image-generation",
        action="store_true",
        help="Explicitly request one image using the account allowance",
    )
    args = parser.parse_args(argv)
    if not args.confirm_image_generation:
        parser.error(
            "--confirm-image-generation is required; this run requests a real image"
        )
    set_logging_options("ERROR", False)
    logger.remove()
    report = run_acceptance(
        model=args.model,
        output_dir=args.output.parent / (args.output.stem + "-assets"),
        confirm_image_generation=True,
        plan=args.plan,
        timeout=args.timeout,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Acceptance: {report['status']}; report: {args.output.resolve()}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
