#!/usr/bin/env python3
"""Initialize and validate a source-faithful BPA video localization job."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
LOCALES = ("en", "jp", "kr", "tw")
RATIOS = {
    "portrait": (1080, 1920),
    "square": (1080, 1080),
    "landscape": (1920, 1080),
}
MANUAL_CHECKS = (
    "source_structure",
    "locked_copy_and_claims",
    "locale_consistency",
    "voice_pronunciation_and_roles",
    "voice_caption_match",
    "active_word_highlight",
    "caption_subject_clearance",
    "gameplay_semantic_match",
    "bgm_and_game_sfx",
    "logo_cta_and_compliance",
    "ratio_framing",
    "full_playback",
)
APPROVALS = (
    "source_revision",
    "pilot",
    "batch_authorization",
    "native_language",
    "current_compliance",
    "rights",
)


class ManifestError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_rate(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        if float(denominator) == 0:
            return None
        return float(numerator) / float(denominator)
    return float(value)


def probe(path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise ManifestError("ffprobe is required but was not found") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or "ffprobe could not read the media"
        raise ManifestError(f"Could not probe {path}: {detail}") from error

    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not video:
        raise ManifestError(f"No video stream found in {path}")

    duration_value = payload.get("format", {}).get("duration") or video.get("duration")
    if duration_value is None:
        raise ManifestError(
            "The localization manifest supports timed video creatives only; "
            f"no duration was found in {path}"
        )
    duration = float(duration_value)
    if duration <= 0:
        raise ManifestError(f"Invalid duration for {path}: {duration}")

    return {
        "width": int(video.get("width", 0)),
        "height": int(video.get("height", 0)),
        "duration": round(duration, 6),
        "fps": parse_rate(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        "video_codec": video.get("codec_name"),
        "pixel_format": video.get("pix_fmt"),
        "audio_present": audio is not None,
        "audio_codec": audio.get("codec_name") if audio else None,
        "sample_rate": int(audio.get("sample_rate", 0)) if audio else None,
        "channels": int(audio.get("channels", 0)) if audio else None,
    }


def state(value: str = "pending", evidence: str = "") -> dict[str, str]:
    return {"state": value, "evidence": evidence}


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def init_manifest(args: argparse.Namespace) -> None:
    source = Path(args.source).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    if not source.is_file():
        raise ManifestError(f"Source file does not exist: {source}")
    if manifest_path.exists():
        raise ManifestError(
            f"Manifest already exists: {manifest_path}. Use a new job path or "
            "edit the existing manifest explicitly."
        )

    target_locales = unique(args.target_locale)
    ratios = unique(args.ratio)
    source_probe = probe(source)
    source_duration = float(source_probe["duration"])
    forbidden_base = [f"unlocalized source-locale copy ({args.source_locale})"]

    locale_plans: dict[str, Any] = {}
    for locale in target_locales:
        forbidden = list(forbidden_base)
        required_labels: list[str] = []
        if locale == "kr":
            required_labels.append("확률형 아이템 포함")
        else:
            forbidden.append("확률형 아이템 포함")
        locale_plans[locale] = {
            "terminology": [],
            "script": [],
            "localized_text_elements": [],
            "assets": {
                "logo": "",
                "font": "",
                "rating_or_legal": [],
            },
            "gameplay": {
                "replacement_required": None,
                "source": "",
                "locale": locale,
                "semantic_match_notes": "",
            },
            "voice": {
                "provider": "",
                "voice_ids": {},
                "sample_state": "pending",
                "sample_evidence": "",
                "word_timing_path": "",
                "max_speed_factor": 1.15,
            },
            "captions": {
                "timing_source": "locale_plan.script",
                "active_word_highlight": True,
                "safe_zone_notes": "",
            },
            "compliance": {
                "required_labels": required_labels,
                "forbidden_carryovers": forbidden,
                **state(),
            },
            "native_review": state(),
        }

    ratio_plans = {
        ratio: {
            "resolution": list(RATIOS[ratio]),
            "framing_notes": "",
            "protected_subjects": [],
            "safe_zones": [],
        }
        for ratio in ratios
    }
    expected_outputs = [
        {
            "locale": locale,
            "ratio": ratio,
            "resolution": list(RATIOS[ratio]),
            "path": "",
            "status": "pending",
        }
        for locale in target_locales
        for ratio in ratios
    ]

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "job": {
            "concept": args.concept,
            "keyname": args.keyname,
            "stage": args.stage,
            "material_id": args.material_id or "",
            "source_locale": args.source_locale,
            "target_locales": target_locales,
            "ratios": ratios,
            "source_path": str(source),
            "output_root": str(output_root),
        },
        "source_probe": {
            **source_probe,
            "sha256": sha256(source),
        },
        "source_contract": {
            "segments": [
                {
                    "id": "hook",
                    "start": 0.0,
                    "end": None,
                    "purpose": "",
                    "locked_visuals": [],
                    "localize": [],
                },
                {
                    "id": "body",
                    "start": None,
                    "end": None,
                    "purpose": "",
                    "locked_visuals": [],
                    "localize": [],
                },
                {
                    "id": "endcard",
                    "start": None,
                    "end": source_duration,
                    "purpose": "",
                    "locked_visuals": [],
                    "localize": [],
                },
            ],
            "locked_elements": [],
            "localizable_elements": [],
            "text_bearing_areas": [],
            "voice": {
                "present": None,
                "localized_voice_required": None,
                "roles": [],
                "source_transcript": [],
            },
            "audio": {
                "bgm_present": None,
                "game_sfx_present": None,
                "energy_notes": "",
            },
        },
        "locale_plans": locale_plans,
        "ratio_plans": ratio_plans,
        "delivery_spec": {
            "fps": 30.0,
            "video_codec": "h264",
            "pixel_format": "yuv420p",
            "audio_codec": "aac",
            "sample_rate": 48000,
            "channels": 2,
            "duration_tolerance_seconds": 0.08,
            "integrated_lufs_target": -14.0,
            "true_peak_max_dbtp": -1.0,
        },
        "pilot": {
            "locale": target_locales[0],
            "ratio": ratios[0],
            "path": "",
            "source_comparison_evidence": "",
            "full_playback_evidence": "",
            **state(),
        },
        "pilot_qa": {name: state() for name in MANUAL_CHECKS},
        "expected_outputs": expected_outputs,
        "approvals": {name: state() for name in APPROVALS},
        "review": {
            "deterministic_preflight": state(),
            "bpa_creative_review": state(),
        },
        "manual_qa": {name: state() for name in MANUAL_CHECKS},
        "exceptions": [],
    }

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Created manifest: {manifest_path}")
    print(f"Source SHA-256: {manifest['source_probe']['sha256']}")
    print(
        "Next: inspect the full source, complete the source/locale/ratio plans, "
        "then run validate --phase plan."
    )


def nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def resolve_reference(value: str, output_root: Path) -> Path | None:
    if value.startswith(("http://", "https://", "drive://", "slack://")):
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else output_root / path


def validate_state(
    record: Any,
    label: str,
    issues: list[str],
    confirmations: list[str],
    *,
    allowed: set[str],
) -> None:
    if not isinstance(record, dict):
        issues.append(f"{label} must be an object with state and evidence")
        return
    value = record.get("state")
    evidence = record.get("evidence")
    if value not in allowed:
        issues.append(f"{label}.state must be one of {sorted(allowed)}; got {value!r}")
        return
    if value in {"pass", "needs_confirmation"} and not nonempty_string(evidence):
        issues.append(f"{label}.evidence is required when state is {value}")
    if value == "needs_confirmation":
        confirmations.append(label)


def validate_script(
    locale: str,
    plan: dict[str, Any],
    roles: set[str],
    duration: float,
    issues: list[str],
) -> list[tuple[str, str]]:
    script = plan.get("script")
    if not isinstance(script, list) or not script:
        issues.append(f"locale_plans.{locale}.script must contain timed lines")
        return []
    ids: set[str] = set()
    sequence: list[tuple[str, str]] = []
    for index, line in enumerate(script):
        label = f"locale_plans.{locale}.script[{index}]"
        if not isinstance(line, dict):
            issues.append(f"{label} must be an object")
            continue
        line_id = str(line.get("id", "")).strip()
        role = str(line.get("role", "")).strip()
        start = line.get("start")
        end = line.get("end")
        text = line.get("text")
        if not line_id:
            issues.append(f"{label}.id is required")
        elif line_id in ids:
            issues.append(f"Duplicate line id for {locale}: {line_id}")
        ids.add(line_id)
        if role not in roles:
            issues.append(f"{label}.role {role!r} is not in source voice roles {sorted(roles)}")
        if not number(start) or not number(end) or not (0 <= float(start) < float(end) <= duration + 0.001):
            issues.append(f"{label} must have 0 <= start < end <= source duration")
        if not nonempty_string(text):
            issues.append(f"{label}.text is required")
        sequence.append((line_id, role))
    return sequence


def expected_matrix(locales: list[str], ratios: list[str]) -> set[tuple[str, str]]:
    return {(locale, ratio) for locale in locales for ratio in ratios}


def validate_plan(manifest: dict[str, Any]) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    confirmations: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        issues.append(
            f"schema_version must be {SCHEMA_VERSION}; got {manifest.get('schema_version')!r}"
        )

    job = manifest.get("job")
    if not isinstance(job, dict):
        return ["job must be an object"], confirmations
    for field in ("concept", "keyname", "source_locale", "source_path", "output_root"):
        if not nonempty_string(job.get(field)):
            issues.append(f"job.{field} is required")

    source_locale = job.get("source_locale")
    if source_locale not in LOCALES:
        issues.append(f"job.source_locale must be one of {LOCALES}")
    target_locales = job.get("target_locales")
    ratios = job.get("ratios")
    if not isinstance(target_locales, list) or not target_locales:
        issues.append("job.target_locales must be a non-empty list")
        target_locales = []
    elif len(target_locales) != len(set(target_locales)) or any(item not in LOCALES for item in target_locales):
        issues.append(f"job.target_locales must be unique values from {LOCALES}")
    if not isinstance(ratios, list) or not ratios:
        issues.append("job.ratios must be a non-empty list")
        ratios = []
    elif len(ratios) != len(set(ratios)) or any(item not in RATIOS for item in ratios):
        issues.append(f"job.ratios must be unique values from {tuple(RATIOS)}")

    stage = job.get("stage")
    if stage not in {"asset-only", "pretest", "post-test"}:
        issues.append("job.stage must be asset-only, pretest, or post-test")
    material_id = str(job.get("material_id", ""))
    if stage == "post-test" and not re.fullmatch(r"[vi]\d{4}", material_id):
        issues.append("post-test jobs require a registry-confirmed material_id like v0080")

    source_path = Path(str(job.get("source_path", ""))).expanduser()
    source_probe = manifest.get("source_probe")
    if not source_path.is_file():
        issues.append(f"Source file is missing: {source_path}")
    if not isinstance(source_probe, dict):
        issues.append("source_probe must be an object")
        source_probe = {}
    elif source_path.is_file():
        recorded_hash = source_probe.get("sha256")
        current_hash = sha256(source_path)
        if recorded_hash != current_hash:
            issues.append("Source SHA-256 differs from the initialized manifest")

    duration = source_probe.get("duration")
    if not number(duration) or float(duration) <= 0:
        issues.append("source_probe.duration must be a positive number")
        duration_value = 0.0
    else:
        duration_value = float(duration)

    contract = manifest.get("source_contract")
    if not isinstance(contract, dict):
        return issues + ["source_contract must be an object"], confirmations
    for field in ("locked_elements", "localizable_elements"):
        value = contract.get(field)
        if not isinstance(value, list) or not value:
            issues.append(f"source_contract.{field} must be a non-empty list")
    if not isinstance(contract.get("text_bearing_areas"), list):
        issues.append("source_contract.text_bearing_areas must be a list")

    segments = contract.get("segments")
    if not isinstance(segments, list) or len(segments) < 3:
        issues.append("source_contract.segments must include hook, body, and endcard")
    else:
        segment_ids = [item.get("id") for item in segments if isinstance(item, dict)]
        for required in ("hook", "body", "endcard"):
            if required not in segment_ids:
                issues.append(f"source_contract.segments is missing {required}")
        previous_end: float | None = None
        for index, segment in enumerate(segments):
            label = f"source_contract.segments[{index}]"
            if not isinstance(segment, dict):
                issues.append(f"{label} must be an object")
                continue
            start = segment.get("start")
            end = segment.get("end")
            if not number(start) or not number(end) or not (0 <= float(start) < float(end) <= duration_value + 0.001):
                issues.append(f"{label} must have 0 <= start < end <= source duration")
                continue
            if previous_end is not None and abs(float(start) - previous_end) > 0.1:
                issues.append(f"{label} leaves a gap or overlap larger than 0.1s")
            previous_end = float(end)
            if not nonempty_string(segment.get("purpose")):
                issues.append(f"{label}.purpose is required")
            for field in ("locked_visuals", "localize"):
                if not isinstance(segment.get(field), list):
                    issues.append(f"{label}.{field} must be a list")
        if segments and isinstance(segments[0], dict) and number(segments[0].get("start")):
            if abs(float(segments[0]["start"])) > 0.05:
                issues.append("The first source segment must start at 0")
        if previous_end is not None and abs(previous_end - duration_value) > 0.1:
            issues.append("Source segments must cover the complete source duration")

    voice = contract.get("voice")
    if not isinstance(voice, dict):
        issues.append("source_contract.voice must be an object")
        voice = {}
    voice_present = voice.get("present")
    localized_voice_required = voice.get("localized_voice_required")
    if not isinstance(voice_present, bool):
        issues.append("source_contract.voice.present must be true or false")
    if not isinstance(localized_voice_required, bool):
        issues.append("source_contract.voice.localized_voice_required must be true or false")
    if voice_present is True and localized_voice_required is not True:
        issues.append("Source voice is present, so localized_voice_required must be true")
    roles_value = voice.get("roles")
    if voice_present is True and (not isinstance(roles_value, list) or not roles_value):
        issues.append("source_contract.voice.roles is required when source voice is present")
    roles = {str(item) for item in roles_value} if isinstance(roles_value, list) else set()
    source_transcript = voice.get("source_transcript")
    if not isinstance(source_transcript, list):
        issues.append("source_contract.voice.source_transcript must be a list")
        source_sequence: list[tuple[str, str]] = []
    elif voice_present is True:
        source_sequence = validate_script(
            "source",
            {"script": source_transcript},
            roles,
            duration_value,
            issues,
        )
    else:
        source_sequence = []

    audio = contract.get("audio")
    if not isinstance(audio, dict):
        issues.append("source_contract.audio must be an object")
    else:
        for field in ("bgm_present", "game_sfx_present"):
            if not isinstance(audio.get(field), bool):
                issues.append(f"source_contract.audio.{field} must be true or false")
        if not nonempty_string(audio.get("energy_notes")):
            issues.append("source_contract.audio.energy_notes is required")

    output_root = Path(str(job.get("output_root", ""))).expanduser()
    locale_plans = manifest.get("locale_plans")
    if not isinstance(locale_plans, dict):
        issues.append("locale_plans must be an object")
        locale_plans = {}
    if set(locale_plans) != set(target_locales):
        issues.append("locale_plans keys must exactly match job.target_locales")
    for locale in target_locales:
        plan = locale_plans.get(locale)
        if not isinstance(plan, dict):
            issues.append(f"locale_plans.{locale} must be an object")
            continue
        if not isinstance(plan.get("terminology"), list) or not plan.get("terminology"):
            issues.append(f"locale_plans.{locale}.terminology must be a non-empty list")
        if not isinstance(plan.get("localized_text_elements"), list):
            issues.append(f"locale_plans.{locale}.localized_text_elements must be a list")
        elif contract.get("text_bearing_areas") and not plan.get("localized_text_elements"):
            issues.append(
                f"locale_plans.{locale}.localized_text_elements is required because the source has text-bearing areas"
            )
        assets = plan.get("assets")
        if not isinstance(assets, dict):
            issues.append(f"locale_plans.{locale}.assets must be an object")
        else:
            for field in ("logo", "font"):
                value = assets.get(field)
                if not nonempty_string(value):
                    issues.append(f"locale_plans.{locale}.assets.{field} is required")
                else:
                    resolved = resolve_reference(str(value), output_root)
                    if resolved is not None and not resolved.exists():
                        issues.append(f"locale_plans.{locale}.assets.{field} is missing: {resolved}")
            if not isinstance(assets.get("rating_or_legal"), list):
                issues.append(f"locale_plans.{locale}.assets.rating_or_legal must be a list")

        gameplay = plan.get("gameplay")
        if not isinstance(gameplay, dict):
            issues.append(f"locale_plans.{locale}.gameplay must be an object")
        else:
            if not isinstance(gameplay.get("replacement_required"), bool):
                issues.append(f"locale_plans.{locale}.gameplay.replacement_required must be true or false")
            if not nonempty_string(gameplay.get("source")):
                issues.append(f"locale_plans.{locale}.gameplay.source is required; use preserve-source when applicable")
            else:
                gameplay_source = str(gameplay["source"])
                if gameplay.get("replacement_required") is True and gameplay_source == "preserve-source":
                    issues.append(
                        f"locale_plans.{locale}.gameplay.source cannot be preserve-source when replacement is required"
                    )
                if gameplay_source != "preserve-source":
                    resolved = resolve_reference(gameplay_source, output_root)
                    if resolved is not None and not resolved.exists():
                        issues.append(
                            f"locale_plans.{locale}.gameplay.source is missing: {resolved}"
                        )
            if gameplay.get("locale") != locale:
                issues.append(f"locale_plans.{locale}.gameplay.locale must equal {locale}")
            if not nonempty_string(gameplay.get("semantic_match_notes")):
                issues.append(f"locale_plans.{locale}.gameplay.semantic_match_notes is required")

        voice_plan = plan.get("voice")
        if not isinstance(voice_plan, dict):
            issues.append(f"locale_plans.{locale}.voice must be an object")
        elif voice_present is True:
            if not nonempty_string(voice_plan.get("provider")):
                issues.append(f"locale_plans.{locale}.voice.provider is required")
            if not isinstance(voice_plan.get("voice_ids"), dict) or set(voice_plan.get("voice_ids", {})) != roles:
                issues.append(f"locale_plans.{locale}.voice.voice_ids must map every source role exactly")
            factor = voice_plan.get("max_speed_factor")
            if not number(factor) or not (1.0 <= float(factor) <= 1.15):
                issues.append(f"locale_plans.{locale}.voice.max_speed_factor must be between 1.0 and 1.15")
            target_sequence = validate_script(locale, plan, roles, duration_value, issues)
            if source_sequence and target_sequence != source_sequence:
                issues.append(
                    f"locale_plans.{locale}.script must preserve source line IDs and role order; "
                    f"expected {source_sequence}, got {target_sequence}"
                )

        captions = plan.get("captions")
        if not isinstance(captions, dict):
            issues.append(f"locale_plans.{locale}.captions must be an object")
        else:
            if captions.get("timing_source") != "locale_plan.script":
                issues.append(f"locale_plans.{locale}.captions.timing_source must be locale_plan.script")
            if voice_present is True and captions.get("active_word_highlight") is not True:
                issues.append(f"locale_plans.{locale}.captions.active_word_highlight must be true")
            if not nonempty_string(captions.get("safe_zone_notes")):
                issues.append(f"locale_plans.{locale}.captions.safe_zone_notes is required")

        compliance = plan.get("compliance")
        if not isinstance(compliance, dict):
            issues.append(f"locale_plans.{locale}.compliance must be an object")
        else:
            required_labels = compliance.get("required_labels")
            forbidden = compliance.get("forbidden_carryovers")
            if not isinstance(required_labels, list) or not isinstance(forbidden, list):
                issues.append(f"locale_plans.{locale}.compliance label fields must be lists")
            else:
                kr_notice = "확률형 아이템 포함"
                if locale == "kr" and kr_notice not in required_labels:
                    issues.append(f"locale_plans.kr.compliance must require {kr_notice}")
                if locale != "kr" and kr_notice not in forbidden:
                    issues.append(f"locale_plans.{locale}.compliance must forbid the KR-only notice")
                if locale != "kr" and kr_notice in required_labels:
                    issues.append(f"locale_plans.{locale}.compliance must not require the KR-only notice")
            validate_state(
                compliance,
                f"locale_plans.{locale}.compliance",
                issues,
                confirmations,
                allowed={"pass", "needs_confirmation"},
            )
        validate_state(
            plan.get("native_review"),
            f"locale_plans.{locale}.native_review",
            issues,
            confirmations,
            allowed={"pending", "pass", "needs_confirmation"},
        )

    ratio_plans = manifest.get("ratio_plans")
    if not isinstance(ratio_plans, dict):
        issues.append("ratio_plans must be an object")
        ratio_plans = {}
    if set(ratio_plans) != set(ratios):
        issues.append("ratio_plans keys must exactly match job.ratios")
    for ratio in ratios:
        plan = ratio_plans.get(ratio)
        if not isinstance(plan, dict):
            issues.append(f"ratio_plans.{ratio} must be an object")
            continue
        if plan.get("resolution") != list(RATIOS[ratio]):
            issues.append(f"ratio_plans.{ratio}.resolution must be {list(RATIOS[ratio])}")
        if not nonempty_string(plan.get("framing_notes")):
            issues.append(f"ratio_plans.{ratio}.framing_notes is required")
        if not isinstance(plan.get("protected_subjects"), list) or not plan.get("protected_subjects"):
            issues.append(f"ratio_plans.{ratio}.protected_subjects must be a non-empty list")
        if not isinstance(plan.get("safe_zones"), list) or not plan.get("safe_zones"):
            issues.append(f"ratio_plans.{ratio}.safe_zones must be a non-empty list")

    outputs = manifest.get("expected_outputs")
    if not isinstance(outputs, list):
        issues.append("expected_outputs must be a list")
    else:
        observed: set[tuple[str, str]] = set()
        for index, item in enumerate(outputs):
            if not isinstance(item, dict):
                issues.append(f"expected_outputs[{index}] must be an object")
                continue
            key = (str(item.get("locale")), str(item.get("ratio")))
            if key in observed:
                issues.append(f"Duplicate expected output: {key}")
            observed.add(key)
            if key[1] in RATIOS and item.get("resolution") != list(RATIOS[key[1]]):
                issues.append(f"expected_outputs[{index}].resolution is incorrect")
        expected = expected_matrix(list(target_locales), list(ratios))
        if observed != expected:
            issues.append(f"expected_outputs matrix mismatch; expected {sorted(expected)}, got {sorted(observed)}")

    pilot = manifest.get("pilot")
    if not isinstance(pilot, dict):
        issues.append("pilot must be an object")
    else:
        if pilot.get("locale") not in target_locales:
            issues.append("pilot.locale must be one of job.target_locales")
        if pilot.get("ratio") not in ratios:
            issues.append("pilot.ratio must be one of job.ratios")
    pilot_qa = manifest.get("pilot_qa")
    if not isinstance(pilot_qa, dict) or set(pilot_qa) != set(MANUAL_CHECKS):
        issues.append(f"pilot_qa keys must exactly match {MANUAL_CHECKS}")

    approvals = manifest.get("approvals")
    if not isinstance(approvals, dict):
        issues.append("approvals must be an object")
    else:
        if set(approvals) != set(APPROVALS):
            issues.append(f"approvals keys must exactly match {APPROVALS}")
        validate_state(
            approvals.get("source_revision"),
            "approvals.source_revision",
            issues,
            confirmations,
            allowed={"pass"},
        )
        validate_state(
            approvals.get("current_compliance"),
            "approvals.current_compliance",
            issues,
            confirmations,
            allowed={"pass", "needs_confirmation"},
        )
        validate_state(
            approvals.get("rights"),
            "approvals.rights",
            issues,
            confirmations,
            allowed={"pass", "needs_confirmation"},
        )
        for name in ("pilot", "batch_authorization", "native_language"):
            validate_state(
                approvals.get(name),
                f"approvals.{name}",
                issues,
                confirmations,
                allowed={"pending", "pass", "needs_confirmation"},
            )

    exceptions = manifest.get("exceptions")
    if not isinstance(exceptions, list):
        issues.append("exceptions must be a list")
    else:
        for index, item in enumerate(exceptions):
            label = f"exceptions[{index}]"
            if not isinstance(item, dict):
                issues.append(f"{label} must be an object")
                continue
            for field in ("timestamp", "source_issue", "planned_change", "fidelity_rationale", "approval_state", "evidence"):
                if not nonempty_string(item.get(field)):
                    issues.append(f"{label}.{field} is required")

    return issues, unique(confirmations)


def validate_rendered_media(
    *,
    label: str,
    path_value: Any,
    ratio: str,
    output_root: Path,
    source_duration: float,
    spec: dict[str, Any],
    issues: list[str],
) -> None:
    if not nonempty_string(path_value):
        issues.append(f"{label}.path is required")
        return
    path = Path(str(path_value)).expanduser()
    if not path.is_absolute():
        path = output_root / path
    if not path.is_file():
        issues.append(f"{label} file is missing: {path}")
        return
    try:
        metadata = probe(path)
    except ManifestError as error:
        issues.append(f"{label}: {error}")
        return
    expected_width, expected_height = RATIOS[ratio]
    tolerance = float(spec.get("duration_tolerance_seconds", 0.08))
    checks = {
        "resolution": (metadata["width"], metadata["height"])
        == (expected_width, expected_height),
        "duration": abs(float(metadata["duration"]) - source_duration) <= tolerance,
        "fps": metadata["fps"] is not None
        and abs(float(metadata["fps"]) - float(spec.get("fps", 30.0))) <= 0.05,
        "video_codec": metadata["video_codec"] == spec.get("video_codec", "h264"),
        "pixel_format": metadata["pixel_format"] == spec.get("pixel_format", "yuv420p"),
        "audio_present": metadata["audio_present"] is True,
        "audio_codec": metadata["audio_codec"] == spec.get("audio_codec", "aac"),
        "sample_rate": metadata["sample_rate"] == int(spec.get("sample_rate", 48000)),
        "channels": metadata["channels"] == int(spec.get("channels", 2)),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        issues.append(f"{label} {path.name} failed: {', '.join(failed)}")


def validate_pilot(manifest: dict[str, Any]) -> tuple[list[str], list[str]]:
    issues, confirmations = validate_plan(manifest)
    if issues:
        return issues, confirmations

    job = manifest["job"]
    source_duration = float(manifest["source_probe"]["duration"])
    output_root = Path(job["output_root"]).expanduser()
    spec = manifest.get("delivery_spec", {})
    pilot = manifest["pilot"]

    validate_rendered_media(
        label="pilot",
        path_value=pilot.get("path"),
        ratio=str(pilot["ratio"]),
        output_root=output_root,
        source_duration=source_duration,
        spec=spec,
        issues=issues,
    )
    for field in ("source_comparison_evidence", "full_playback_evidence"):
        if not nonempty_string(pilot.get(field)):
            issues.append(f"pilot.{field} is required")
    validate_state(
        pilot,
        "pilot",
        issues,
        confirmations,
        allowed={"pass"},
    )

    pilot_locale = str(pilot["locale"])
    if manifest["source_contract"]["voice"]["present"] is True:
        voice_plan = manifest["locale_plans"][pilot_locale]["voice"]
        if voice_plan.get("sample_state") != "pass":
            issues.append(
                f"locale_plans.{pilot_locale}.voice.sample_state must be pass before pilot approval"
            )
        if not nonempty_string(voice_plan.get("sample_evidence")):
            issues.append(
                f"locale_plans.{pilot_locale}.voice.sample_evidence is required before pilot approval"
            )
        timing_value = voice_plan.get("word_timing_path")
        if not nonempty_string(timing_value):
            issues.append(
                f"locale_plans.{pilot_locale}.voice.word_timing_path is required before pilot approval"
            )
        else:
            timing_path = resolve_reference(str(timing_value), output_root)
            if timing_path is not None and not timing_path.is_file():
                issues.append(
                    f"locale_plans.{pilot_locale}.voice.word_timing_path is missing: {timing_path}"
                )

    pilot_qa = manifest["pilot_qa"]
    for name in MANUAL_CHECKS:
        validate_state(
            pilot_qa[name],
            f"pilot_qa.{name}",
            issues,
            confirmations,
            allowed={"pass", "needs_confirmation"},
        )

    approvals = manifest["approvals"]
    pilot_state = approvals["pilot"]["state"]
    batch_state = approvals["batch_authorization"]["state"]
    if pilot_state != "pass" and batch_state != "pass":
        issues.append("Pilot gate requires user pilot approval or explicit batch authorization")

    return issues, unique(confirmations)


def validate_delivery(manifest: dict[str, Any]) -> tuple[list[str], list[str]]:
    issues, confirmations = validate_pilot(manifest)
    if issues:
        return issues, confirmations

    job = manifest["job"]
    source_duration = float(manifest["source_probe"]["duration"])
    output_root = Path(job["output_root"]).expanduser()
    spec = manifest.get("delivery_spec", {})
    approvals = manifest["approvals"]
    for name in ("native_language", "current_compliance", "rights"):
        validate_state(
            approvals[name],
            f"approvals.{name}",
            issues,
            confirmations,
            allowed={"pass", "needs_confirmation"},
        )

    if manifest["source_contract"]["voice"]["present"] is True:
        for locale, plan in manifest["locale_plans"].items():
            voice_plan = plan["voice"]
            if voice_plan.get("sample_state") != "pass":
                issues.append(
                    f"locale_plans.{locale}.voice.sample_state must be pass before delivery"
                )
            if not nonempty_string(voice_plan.get("sample_evidence")):
                issues.append(
                    f"locale_plans.{locale}.voice.sample_evidence is required before delivery"
                )
            timing_value = voice_plan.get("word_timing_path")
            if not nonempty_string(timing_value):
                issues.append(
                    f"locale_plans.{locale}.voice.word_timing_path is required before delivery"
                )
            else:
                timing_path = resolve_reference(str(timing_value), output_root)
                if timing_path is not None and not timing_path.is_file():
                    issues.append(
                        f"locale_plans.{locale}.voice.word_timing_path is missing: {timing_path}"
                    )

    for index, item in enumerate(manifest["expected_outputs"]):
        label = f"expected_outputs[{index}]"
        validate_rendered_media(
            label=label,
            path_value=item.get("path"),
            ratio=str(item["ratio"]),
            output_root=output_root,
            source_duration=source_duration,
            spec=spec,
            issues=issues,
        )
        if item.get("status") not in {"pass", "needs_confirmation"}:
            issues.append(f"{label}.status must be pass or needs_confirmation")
        if item.get("status") == "needs_confirmation":
            confirmations.append(label)

    manual_qa = manifest.get("manual_qa")
    if not isinstance(manual_qa, dict) or set(manual_qa) != set(MANUAL_CHECKS):
        issues.append(f"manual_qa keys must exactly match {MANUAL_CHECKS}")
    else:
        for name in MANUAL_CHECKS:
            validate_state(
                manual_qa[name],
                f"manual_qa.{name}",
                issues,
                confirmations,
                allowed={"pass", "needs_confirmation"},
            )

    review = manifest.get("review")
    if not isinstance(review, dict):
        issues.append("review must be an object")
    else:
        for name in ("deterministic_preflight", "bpa_creative_review"):
            validate_state(
                review.get(name),
                f"review.{name}",
                issues,
                confirmations,
                allowed={"pass", "needs_confirmation"},
            )

    return issues, unique(confirmations)


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ManifestError(f"Manifest does not exist: {path}") from error
    except json.JSONDecodeError as error:
        raise ManifestError(f"Invalid JSON in {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ManifestError("Manifest root must be a JSON object")
    return payload


def validate_manifest(args: argparse.Namespace) -> int:
    path = Path(args.manifest).expanduser().resolve()
    manifest = load_manifest(path)
    if args.phase == "plan":
        issues, confirmations = validate_plan(manifest)
        success_status = "PLAN_READY_WITH_CONFIRMATIONS" if confirmations else "PLAN_READY"
    elif args.phase == "pilot":
        issues, confirmations = validate_pilot(manifest)
        success_status = "PILOT_READY_WITH_CONFIRMATIONS" if confirmations else "PILOT_READY"
    else:
        issues, confirmations = validate_delivery(manifest)
        success_status = "READY_WITH_CONFIRMATIONS" if confirmations else "READY"

    if issues:
        print(f"NOT_READY: {len(issues)} issue(s)")
        for issue in issues:
            print(f"- {issue}")
        if confirmations:
            print("Confirmations already recorded:")
            for item in confirmations:
                print(f"- {item}")
        return 1

    print(success_status)
    if confirmations:
        print("Unresolved confirmations:")
        for item in confirmations:
            print(f"- {item}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a new job manifest")
    init_parser.add_argument("--source", required=True)
    init_parser.add_argument("--source-locale", choices=LOCALES, required=True)
    init_parser.add_argument("--target-locale", action="append", choices=LOCALES, required=True)
    init_parser.add_argument("--ratio", action="append", choices=tuple(RATIOS), required=True)
    init_parser.add_argument("--concept", required=True)
    init_parser.add_argument("--keyname", required=True)
    init_parser.add_argument("--stage", choices=("asset-only", "pretest", "post-test"), default="asset-only")
    init_parser.add_argument("--material-id")
    init_parser.add_argument("--output-root", required=True)
    init_parser.add_argument("--manifest", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate a plan or delivery")
    validate_parser.add_argument("--manifest", required=True)
    validate_parser.add_argument("--phase", choices=("plan", "pilot", "delivery"), required=True)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "init":
            init_manifest(args)
            return 0
        return validate_manifest(args)
    except ManifestError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
