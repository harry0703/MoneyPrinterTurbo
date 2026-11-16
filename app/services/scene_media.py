"""Search, rank, visually validate, and persist media candidates per scene."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect
from app.models.scene_media import (
    CandidateScores,
    SceneMediaAssignment,
    SceneMediaCandidate,
    SceneMediaManifest,
    SceneMediaAttempt,
    SceneVisualAssessment,
)
from app.models.scene_quality import MediaQualityReport
from app.models.video_plan import Scene, VideoPlan
from app.services import material, scene_quality, task_artifacts, twelvelabs
from app.utils import utils


_STOCK_PROVIDERS = {
    "pexels": "pexels_api_keys",
    "pixabay": "pixabay_api_keys",
    "coverr": "coverr_api_keys",
}
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "by", "de", "del", "el", "en",
    "for", "from", "in", "is", "la", "las", "los", "of", "on", "or", "the",
    "to", "un", "una", "uno", "y", "que", "se", "su", "por", "with",
}
_KNOWN_ALIASES = {
    "sun": ("sun", "the sun", "sol"),
    "sol": ("sun", "the sun", "sol"),
    "jupiter": ("jupiter", "júpiter"),
    "júpiter": ("jupiter", "júpiter"),
    "saturn": ("saturn", "saturno"),
    "saturno": ("saturn", "saturno"),
    "mars": ("mars", "marte"),
    "marte": ("mars", "marte"),
    "voyager": ("voyager", "voyager 1", "voyager 2"),
    "oort cloud": ("oort cloud", "oort-cloud", "nube de oort"),
    "nube de oort": ("oort cloud", "oort-cloud", "nube de oort"),
}


def evaluate_image_asset(scene: Scene, image_path: str | Path) -> tuple[dict | None, MediaQualityReport]:
    """Evaluate a local image with Pegasus 1.6 and local technical checks.

    Text/image embeddings are recorded as auxiliary semantic evidence only; they
    cannot accept an image without an explicit Pegasus visual assessment.
    """
    path = Path(image_path).expanduser().resolve()
    report = scene_quality.inspect_media_file(path)
    cache_key = _visual_assessment_key(scene) + ":" + report.asset_sha256
    cached = _IMAGE_ASSESSMENT_CACHE.get(cache_key)
    if cached is not None:
        return cached, report
    try:
        from PIL import Image, ImageOps

        with Image.open(path) as source:
            with ImageOps.exif_transpose(source) as oriented:
                image = oriented.convert("RGB")
                image.thumbnail((2048, 2048))
                import io

                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=90, optimize=True)
                image_bytes = buffer.getvalue()
        prompt = (
            "Inspect this image as visual evidence for one video scene. Return only JSON with "
            "subject_visible, action_matches, context_matches, confidence, description, "
            "mismatch_reasons. Require the specific named subject, depicted action, and "
            "visual context; thematic similarity is insufficient. Scene: "
            + _visual_prompt(scene)
        )
        response = twelvelabs.analyze_images([image_bytes], prompt=prompt)
        if not response:
            return None, report
        assessment = _parse_visual_assessment(str(response))
        subject_match = assessment.subject_visible and _subject_match(
            assessment.description, scene
        )
        action_match = assessment.action_matches
        context_match = assessment.context_matches is True
        visual_score = (
            0.40 * float(subject_match)
            + 0.35 * float(action_match)
            + 0.25 * float(context_match)
        )
        semantic_relevance = None
        if config.app.get("scene_media_semantic_scoring", False):
            expected = " ".join((scene.visual.subject[0], scene.visual.action, scene.visual.context))
            semantic_relevance = twelvelabs.image_text_similarity(str(path), expected[:450])
        matches = (
            subject_match and action_match and context_match
            and visual_score >= 0.85 and assessment.confidence >= 0.70
        )
        result = "accepted" if matches and report.result == "accepted" else (
            "rejected" if (
                not subject_match or not action_match or not context_match
                or report.result == "rejected"
            ) else "review"
        )
        evaluation = {
            "asset_sha256": report.asset_sha256,
            "result": result,
            "semantic_relevance": semantic_relevance,
            "visual_correspondence": visual_score,
            "technical_quality": report.technical_quality,
            "confidence": assessment.confidence,
            "description": assessment.description,
            "reason": (
                "image matches the specific subject, action, and context"
                if result == "accepted" else "; ".join(
                    assessment.mismatch_reasons or report.issues
                    or ["visual evidence was ambiguous or did not meet thresholds"]
                )
            ),
        }
        _IMAGE_ASSESSMENT_CACHE[cache_key] = evaluation
        if len(_IMAGE_ASSESSMENT_CACHE) > 256:
            _IMAGE_ASSESSMENT_CACHE.pop(next(iter(_IMAGE_ASSESSMENT_CACHE)))
        return evaluation, report
    except Exception as exc:
        logger.warning("image visual assessment failed: path={}, error={}", path, _safe_error(exc))
        return None, report


_IMAGE_ASSESSMENT_CACHE: dict[str, dict] = {}


def _safe_error(exc: Exception) -> str:
    detail = re.sub(r"https?://[^\s)]+", "[redacted-url]", str(exc))
    return f"{type(exc).__name__}: {detail[:500]}"


def _setting_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(config.app.get(name, default))
    except (TypeError, ValueError, OverflowError):
        return default
    return min(maximum, max(minimum, value))


def _same_plan(existing: SceneMediaManifest, plan: VideoPlan) -> bool:
    return (
        existing.plan_id == plan.plan_id
        and existing.script_sha256 == plan.script_sha256
    )


def _configured_providers() -> list[str]:
    providers = []
    for provider, key_name in _STOCK_PROVIDERS.items():
        keys = config.app.get(key_name)
        if (isinstance(keys, str) and keys.strip()) or (
            isinstance(keys, (list, tuple)) and any(str(key).strip() for key in keys)
        ):
            providers.append(provider)
    return providers


def _tokens(text: str) -> set[str]:
    return {
        token.casefold()
        for token in _WORD.findall(text or "")
        if token.casefold() not in _STOP_WORDS and len(token) > 1
    }


def _queries_for_scene(scene: Scene, limit: int) -> list[str]:
    visual = scene.visual
    raw_queries = list(visual.search_queries)
    primary_subject = visual.subject[0]
    generated = [
        f"{primary_subject} {visual.action}",
        f"{primary_subject} {visual.context}" if visual.context else "",
        primary_subject,
    ]
    queries = []
    seen = set()
    for raw in raw_queries + generated:
        query = " ".join((raw or "").split()).strip(" ,.;")[:500]
        key = query.casefold()
        if query and key not in seen:
            queries.append(query)
            seen.add(key)
        if len(queries) >= limit:
            break
    return queries


def _retrieval_score(scene: Scene, query: str) -> float:
    """Estimate query-to-brief relevance; this is explicitly not visual QA."""
    query_tokens = _tokens(query)
    subject_tokens = _tokens(" ".join(scene.visual.subject))
    action_context_tokens = _tokens(f"{scene.visual.action} {scene.visual.context}")
    subject_ratio = len(query_tokens & subject_tokens) / max(1, len(subject_tokens))
    action_ratio = len(query_tokens & action_context_tokens) / max(1, len(action_context_tokens))
    return min(1.0, max(0.0, 0.7 * subject_ratio + 0.3 * action_ratio))


def _quality_scores(scene: Scene, candidate, aspect: VideoAspect) -> tuple[float, float, float]:
    source = candidate.source_info if isinstance(candidate.source_info, dict) else {}
    rendition = source.get("rendition") if isinstance(source.get("rendition"), dict) else {}
    try:
        width, height = int(rendition.get("width")), int(rendition.get("height"))
    except (TypeError, ValueError, OverflowError):
        width = height = 0
    if width > 0 and height > 0:
        target_width, target_height = aspect.to_resolution()
        resolution = min(1.0, width / target_width, height / target_height)
        ratio = width / height
        target_ratio = target_width / target_height
        aspect_score = max(0.0, 1.0 - abs(math.log(ratio / target_ratio)))
    else:
        width = height = 0
        resolution = 0.25
        aspect_score = 0.25

    target_duration = max(1.0, scene.timing.estimated_duration_ms / 1000)
    duration_score = min(1.0, float(candidate.duration or 0) / target_duration)
    return resolution, duration_score, aspect_score


def _candidate_id(candidate) -> str:
    source = candidate.source_info if isinstance(candidate.source_info, dict) else {}
    asset_id = source.get("asset_id")
    if asset_id:
        return f"{candidate.provider}:{asset_id}"
    digest = hashlib.sha256(candidate.url.encode("utf-8")).hexdigest()[:16]
    return f"{candidate.provider}:{digest}"


def _resource_fingerprint(candidate) -> str:
    source = candidate.source_info if isinstance(candidate.source_info, dict) else {}
    stable_page = str(source.get("source_page") or "").strip()
    identity = stable_page or f"{candidate.provider}:{source.get('asset_id') or candidate.url}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _aliases_for_scene(scene: Scene) -> tuple[str, ...]:
    primary = scene.visual.subject[0].strip()
    normalized = primary.casefold()
    known = _KNOWN_ALIASES.get(normalized)
    if known is None and "voyager" in normalized:
        known = _KNOWN_ALIASES["voyager"]
    if known is None and "oort" in normalized:
        known = _KNOWN_ALIASES["oort cloud"]
    if known is None:
        for name, aliases in _KNOWN_ALIASES.items():
            if normalized.startswith(name + " "):
                known = aliases
                break
    return known or (primary,)


def _visual_prompt(scene: Scene) -> str:
    return (
        "Inspect visual content throughout the complete clip, not a single frame. "
        "Check the beginning, middle, and end separately. Do not infer from search "
        "terms, narration, or soundtrack. Return one JSON object only with fields "
        "subject_visible (boolean), action_matches (boolean), context_matches "
        "(boolean or null), confidence (0 to 1), temporal_consistency (0 to 1), "
        "technical_quality (0 to 1), description (visible content only), "
        "observations (exactly three objects with position=beginning|middle|end, "
        "subject_visible, action_matches, context_matches, description), and "
        "mismatch_reasons (array of strings). If uncertain, use false and low confidence.\n"
        f"Primary subject (must be visually identifiable): {scene.visual.subject[0]}\n"
        f"Action: {scene.visual.action}\n"
        f"Context: {scene.visual.context}\n"
        f"Expected visual: {scene.visual.description}\n"
        "Do not set subject_visible or action_matches to true merely because the video "
        "is thematically related. The named subject and requested action must both "
        "be visibly supported in the observations. Return concise factual JSON."
    )


def _visual_assessment_key(scene: Scene) -> str:
    model = str(config.app.get("twelvelabs_pegasus_model", twelvelabs.DEFAULT_PEGASUS_MODEL))
    prompt = f"scene-visual-v2\0{model}\0{_visual_prompt(scene)}"
    if config.app.get("scene_media_semantic_scoring", False):
        prompt += "\0" + str(config.app.get("twelvelabs_marengo_model", twelvelabs.DEFAULT_MARENGO_MODEL))
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _parse_visual_assessment(response: str) -> SceneVisualAssessment:
    text = (response or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return SceneVisualAssessment.model_validate(payload)
    raise ValueError("visual assessor did not return a valid JSON assessment")


def _subject_match(description: str, scene: Scene) -> bool:
    folded = (description or "").casefold()
    return any(
        re.search(rf"(?<!\w){re.escape(alias.casefold())}(?!\w)", folded)
        for alias in _aliases_for_scene(scene)
    )


def _provider_search(
    provider: str, query: str, aspect: VideoAspect, visual_validation: bool
):
    # Current Pegasus analyze supports video inputs starting at one second.
    # Retaining the old four-second stock filter would unnecessarily discard
    # short, otherwise valid clips.
    minimum_duration = 1
    return material.search_stock_videos(provider, query, minimum_duration, aspect)


def _search_candidates(
    scene: Scene,
    queries: list[str],
    providers: list[str],
    aspect: VideoAspect,
    visual_validation: bool,
):
    requests = [(provider, query) for provider in providers for query in queries]
    if not requests:
        return [], ["no stock providers are configured"], 0
    workers = min(_setting_int("scene_media_search_concurrency", 4, 1, 16), len(requests))
    errors = []
    found = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="scene-media-search") as pool:
        futures = {
            pool.submit(
                _provider_search, provider, query, aspect, visual_validation
            ): (provider, query)
            for provider, query in requests
        }
        for future, (provider, query) in futures.items():
            try:
                items = future.result()
            except Exception as exc:
                safe_error = _safe_error(exc)
                logger.warning(
                    "scene media provider search failed: scene_id={}, provider={}, error={}",
                    scene.scene_id, provider, safe_error,
                )
                errors.append(f"{provider} search failed for {query!r}: {safe_error}")
                continue
            if not isinstance(items, (list, tuple)):
                errors.append(f"{provider} returned an invalid result list for {query!r}")
                continue
            for item in items:
                if not isinstance(item, MaterialInfo) or not item.url:
                    continue
                found.append((provider, query, item))
    return found, errors, len(requests)


def _build_candidates(scene: Scene, results, aspect: VideoAspect, max_candidates: int):
    by_id = {}
    candidates = []
    for provider, query, item in results:
        asset_id = _candidate_id(item)
        fingerprint = _resource_fingerprint(item)
        existing = by_id.get(fingerprint)
        if existing is not None:
            if query != existing.search_query and query not in existing.matched_queries:
                existing.matched_queries.append(query)
            continue
        source = item.source_info if isinstance(item.source_info, dict) else {}
        rendition = source.get("rendition") if isinstance(source.get("rendition"), dict) else {}
        try:
            width = int(rendition.get("width"))
            height = int(rendition.get("height"))
        except (TypeError, ValueError, OverflowError):
            width = height = None
        resolution, duration, aspect_score = _quality_scores(scene, item, aspect)
        record = SceneMediaCandidate(
            provider=provider,
            original_asset_id=(
                str(source.get("asset_id"))[:256] if source.get("asset_id") else None
            ),
            resource_fingerprint=fingerprint,
            source_page=source.get("source_page"),
            material_type="stock_video",
            search_query=query,
            matched_queries=[query],
            duration_seconds=float(item.duration or 0),
            width=width,
            height=height,
            scores=CandidateScores(
                retrieval=_retrieval_score(scene, query),
                resolution=resolution,
                duration=duration,
                aspect=aspect_score,
            ),
        )
        by_id[fingerprint] = record
        candidates.append((asset_id, item, record))
    candidates.sort(
        key=lambda row: (
            row[2].scores.retrieval,
            row[2].scores.resolution,
            row[2].scores.duration,
            row[2].scores.aspect,
        ),
        reverse=True,
    )
    return candidates[:max_candidates]


def _assign_scene(
    task_id: str,
    scene: Scene,
    aspect: VideoAspect,
    used_resources: dict[str, str],
    visual_validation: bool,
    cached_assessments: dict[tuple[str, str], SceneMediaCandidate] | None = None,
    used_file_hashes: dict[str, str] | None = None,
) -> SceneMediaAssignment:
    started = time.monotonic()
    query_limit = _setting_int("scene_media_max_queries_per_scene", 2, 1, 8)
    candidate_limit = _setting_int("scene_media_max_candidates_per_scene", 8, 1, 30)
    queries = _queries_for_scene(scene, query_limit)
    providers = _configured_providers()
    validation_enabled = visual_validation
    validation_available = validation_enabled and twelvelabs.is_enabled()
    results, provider_errors, provider_search_requests = _search_candidates(
        scene, queries, providers, aspect, validation_available
    )
    candidates = _build_candidates(scene, results, aspect, candidate_limit)
    warnings = []
    if not validation_enabled:
        warnings.append(
            "visual validation is disabled; retrieval scores are not visual match scores"
        )
    elif not validation_available:
        warnings.append("visual validation requested but TwelveLabs is not configured")

    selected_candidate = None
    visual_validation_requests = 0
    visual_cache_hits = 0
    quality_cache_hits = 0
    download_attempts = 0
    if validation_available and candidates:
        check_limit = _setting_int("scene_media_visual_checks_per_scene", 3, 1, 8)
        checked = 0
        visually_matching = []
        assessment_key = _visual_assessment_key(scene)
        for asset_id, item, record in candidates:
            if record.duplicate_of:
                continue
            if checked >= check_limit:
                record.discard_reasons.append("visual validation candidate limit reached")
                continue
            checked += 1
            record.visual_assessment_key = assessment_key
            cached = (cached_assessments or {}).get(
                (record.resource_fingerprint, assessment_key)
            )
            if cached and cached.visual_validation in {"passed", "mismatched"}:
                visual_cache_hits += 1
                record.visual_validation = cached.visual_validation
                record.visual_description = cached.visual_description
                record.evaluation_result = cached.evaluation_result
                record.scores = cached.scores.model_copy(deep=True)
                record.discard_reasons = list(cached.discard_reasons)
                if record.visual_validation == "passed":
                    visually_matching.append((record.scores.validated_ranking or 0, asset_id, item, record))
                continue
            visual_validation_requests += 1
            try:
                if float(item.duration or 0) < 1:
                    raise ValueError("Pegasus requires a video clip of at least one second")
                if not item.url.startswith(("https://", "http://")):
                    raise ValueError("Pegasus requires a public HTTP(S) video URL")
                response = twelvelabs.analyze_clip(
                    item.url,
                    prompt=_visual_prompt(scene),
                )
            except Exception as exc:
                response = None
                record.visual_validation = "failed"
                provider_errors.append(f"TwelveLabs validation failed: {_safe_error(exc)}")
            if not response:
                if record.visual_validation != "failed":
                    record.visual_validation = "unavailable"
                record.discard_reasons.append("visual content could not be evaluated")
                continue
            try:
                assessment = _parse_visual_assessment(str(response))
            except Exception as exc:
                record.visual_validation = "unavailable"
                record.discard_reasons.append(
                    f"visual assessment response was invalid: {_safe_error(exc)}"
                )
                continue
            record.visual_description = assessment.description
            observations = assessment.observations
            observed_positions = {entry.position for entry in observations}
            if len(observations) < 3 or observed_positions != {"beginning", "middle", "end"}:
                record.visual_validation = "unavailable"
                record.evaluation_result = "review"
                record.discard_reasons.append(
                    "visual analysis did not provide evidence from beginning, middle, and end"
                )
                continue

            subject_score = sum(
                entry.subject_visible and _subject_match(entry.description, scene)
                for entry in observations
            ) / len(observations)
            action_score = sum(entry.action_matches for entry in observations) / len(observations)
            context_score = (
                sum(entry.context_matches is True for entry in observations) / len(observations)
                if scene.visual.context.strip()
                else 1.0
            )
            subject_match = assessment.subject_visible and subject_score >= 0.8
            action_match = assessment.action_matches and action_score >= 0.8
            context_match = assessment.context_matches is not False and context_score >= 0.8
            visual_correspondence = (
                0.40 * subject_score + 0.35 * action_score + 0.25 * context_score
            )
            technical_quality = assessment.technical_quality
            if technical_quality is None:
                technical_quality = sum((record.scores.resolution, record.scores.duration, record.scores.aspect)) / 3
            semantic_relevance = None
            if config.app.get("scene_media_semantic_scoring", False):
                expected_text = " ".join((
                    " ".join(scene.visual.subject), scene.visual.action,
                    scene.visual.context, scene.visual.description,
                ))[:450]
                semantic_relevance = twelvelabs.text_similarity(
                    expected_text, assessment.description[:450]
                )
            record.scores.visual_subject_match = subject_score
            record.scores.action_match = action_score
            record.scores.context_match = context_score
            record.scores.visual_correspondence = visual_correspondence
            record.scores.technical_quality = technical_quality
            record.scores.semantic_relevance = semantic_relevance
            record.scores.assessment_confidence = assessment.confidence
            final_confidence = assessment.confidence * (
                assessment.temporal_consistency
                if assessment.temporal_consistency is not None
                else visual_correspondence
            )
            confidence_threshold = 0.70
            is_match = (
                subject_match
                and action_match
                and context_match
                and visual_correspondence >= 0.85
                and final_confidence >= confidence_threshold
                and assessment.confidence >= confidence_threshold
            )
            record.visual_validation = "passed" if is_match else "mismatched"
            record.evaluation_result = "accepted" if is_match else "rejected"
            if not subject_match:
                record.discard_reasons.append(
                    "visual analysis did not identify the required subject: "
                    f"{scene.visual.subject[0]}"
                )
            if not action_match:
                record.discard_reasons.append(
                    "visual analysis did not confirm the requested action"
                )
            if not context_match:
                record.discard_reasons.append(
                    "visual analysis did not confirm the expected context"
                )
            if assessment.confidence < confidence_threshold:
                record.discard_reasons.append(
                    f"visual assessment confidence was below {confidence_threshold:.2f}"
                )
            if not is_match:
                record.discard_reasons.extend(assessment.mismatch_reasons)
                continue
            if record.resource_fingerprint in used_resources:
                record.duplicate_of = used_resources[record.resource_fingerprint]
                record.discard_reasons.append("resource already assigned to another scene")
                continue
            record.scores.validated_ranking = (
                0.40 * visual_correspondence
                + 0.25 * final_confidence
                + 0.20 * technical_quality
                + 0.15 * (semantic_relevance if semantic_relevance is not None else record.scores.retrieval)
            )
            if record.provider == "coverr":
                record.discard_reasons.append(
                    "Coverr embeds a signed download URL and counts retrieval as a "
                    "license download event; automatic visual QA download is disabled"
                )
                continue
            visually_matching.append((record.scores.validated_ranking, asset_id, item, record))

        visibly_ranked = sorted(visually_matching, key=lambda row: row[0], reverse=True)
        for _score, asset_id, item, record in visibly_ranked:
            # Match the legacy downloader's output directory so its save_video
            # cache can reuse this download without changing rendering behavior.
            material_directory = str(config.app.get("material_directory", "") or "").strip()
            if material_directory == "task":
                local_dir = Path(utils.task_dir(task_id))
            elif material_directory and Path(material_directory).is_dir():
                local_dir = Path(material_directory)
            else:
                local_dir = Path(utils.storage_dir("cache_videos", create=True))
            download_attempts += 1
            try:
                local_path = material.save_video(item.url, str(local_dir))
            except Exception as exc:
                local_path = ""
                provider_errors.append(f"download failed for {asset_id}: {_safe_error(exc)}")
            if not local_path:
                record.discard_reasons.append(
                    "visually matched resource could not be downloaded and validated"
                )
                continue
            try:
                target_width, target_height = aspect.to_resolution()
                quality_report = scene_quality.inspect_media_file(
                    local_path,
                    target_width=target_width,
                    target_height=target_height,
                )
                record.quality_report = quality_report
                record.scores.technical_quality = quality_report.technical_quality
                quality_cache_hits += int(quality_report.cache_hit)
                if quality_report.result != "accepted":
                    record.evaluation_result = "rejected"
                    record.discard_reasons.extend(quality_report.issues)
                    record.discard_reasons.append(
                        "local technical quality did not pass conservative acceptance"
                    )
                    continue
                duplicate_scene = (used_file_hashes or {}).get(quality_report.asset_sha256)
                if duplicate_scene:
                    record.duplicate_of = duplicate_scene
                    record.evaluation_result = "rejected"
                    record.discard_reasons.append(
                        "downloaded media has identical file content to another scene"
                    )
                    continue
            except Exception as exc:
                record.evaluation_result = "review"
                record.discard_reasons.append(
                    f"local technical assessment failed: {_safe_error(exc)}"
                )
                continue
            try:
                record.local_path = Path(local_path).resolve().relative_to(
                    Path(utils.task_dir(task_id)).resolve()
                ).as_posix()
            except (OSError, ValueError):
                record.local_path = str(local_path)
            record.selected = True
            selected_candidate = record
            used_resources[record.resource_fingerprint] = scene.scene_id
            if used_file_hashes is not None:
                used_file_hashes[quality_report.asset_sha256] = scene.scene_id
            break

    if selected_candidate is not None:
        status = "selected"
    elif candidates:
        status = "pending_review"
        if validation_available:
            warnings.append(
                "no candidate passed the strict visual subject check and download validation"
            )
    else:
        status = "no_candidates"
        if not provider_errors:
            warnings.append(
                "no stock results were returned; provider adapters may represent "
                "both empty results and handled request failures as an empty list"
            )

    return SceneMediaAssignment(
        scene_id=scene.scene_id,
        status=status,
        search_queries=queries,
        selected_candidate=selected_candidate,
        material_type=selected_candidate.material_type if selected_candidate else None,
        provider=selected_candidate.provider if selected_candidate else None,
        original_asset_id=(
            selected_candidate.original_asset_id if selected_candidate else None
        ),
        local_path=selected_candidate.local_path if selected_candidate else None,
        selected_search_query=(
            selected_candidate.search_query if selected_candidate else None
        ),
        selected_scores=(
            selected_candidate.scores.model_copy(deep=True)
            if selected_candidate
            else None
        ),
        candidates=[record for _, _, record in candidates],
        provider_errors=provider_errors,
        warnings=warnings,
        elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
        provider_search_requests=provider_search_requests,
        visual_validation_requests=visual_validation_requests,
        visual_cache_hits=visual_cache_hits,
        quality_cache_hits=quality_cache_hits,
        download_attempts=download_attempts,
    )


def select_plan_materials(
    task_id: str,
    plan: VideoPlan,
    *,
    video_aspect: VideoAspect | str = VideoAspect.portrait,
    scene_ids: list[str] | None = None,
    visual_validation: bool = False,
) -> SceneMediaManifest:
    """Search and assess plan scenes independently, optionally retrying a subset.

    Only the configured stock providers (Pexels, Pixabay, Coverr) are queried.
    Billable generation services retain their existing task flows and are not
    invoked as hidden fallbacks from this search-only sprint.
    """
    aspect = VideoAspect(video_aspect)
    existing = None
    try:
        raw_existing = task_artifacts.read_scene_media_manifest(task_id)
        if raw_existing:
            existing = SceneMediaManifest.model_validate(raw_existing)
    except Exception as exc:
        logger.warning(
            "ignoring invalid scene media artifact for retry: task_id={}, error={}: {}",
            task_id, type(exc).__name__, exc,
        )

    if existing and _same_plan(existing, plan):
        assignments = {entry.scene_id: entry for entry in existing.assignments}
        created_at = existing.created_at
        cached_assessments = {}
        for assignment in existing.assignments:
            previous_attempts = [
                candidate
                for attempt in assignment.search_history
                for candidate in attempt.candidates
            ]
            for candidate in [*assignment.candidates, *previous_attempts]:
                if candidate.visual_assessment_key and candidate.visual_validation in {
                    "passed", "mismatched"
                }:
                    cached_assessments[(
                        candidate.resource_fingerprint,
                        candidate.visual_assessment_key,
                    )] = candidate
    else:
        if existing:
            logger.warning(
                "scene media artifact belongs to another scene plan; resetting assignments: "
                "task_id={}, old_plan_id={}, new_plan_id={}",
                task_id,
                existing.plan_id,
                plan.plan_id,
            )
        assignments = {}
        created_at = datetime.now(timezone.utc)
        cached_assessments = {}
    selected_ids = set(scene_ids or [scene.scene_id for scene in plan.scenes])
    valid_ids = {scene.scene_id for scene in plan.scenes}
    unknown_ids = selected_ids - valid_ids
    if unknown_ids:
        raise ValueError(f"unknown scene IDs requested for retry: {sorted(unknown_ids)}")

    if scene_ids is None:
        scene_limit = _setting_int("scene_media_max_scenes_per_task", 30, 1, 100)
        process_ids = {scene.scene_id for scene in plan.scenes[:scene_limit]}
    else:
        process_limit = _setting_int("scene_media_max_scenes_per_task", 30, 1, 100)
        if len(selected_ids) > process_limit:
            raise ValueError(
                f"scene retry exceeds configured limit of {process_limit} scenes"
            )
        process_ids = selected_ids

    previous_total_searches = sum(
        assignment.provider_search_requests
        + sum(attempt.provider_search_requests for attempt in assignment.search_history)
        for assignment in assignments.values()
    )
    previous_total_visual_checks = sum(
        assignment.visual_validation_requests
        + sum(attempt.visual_validation_requests for attempt in assignment.search_history)
        for assignment in assignments.values()
    )
    previous_total_downloads = sum(
        assignment.download_attempts
        + sum(attempt.download_attempts for attempt in assignment.search_history)
        for assignment in assignments.values()
    )
    previous_total_elapsed = sum(
        assignment.elapsed_ms
        + sum(attempt.elapsed_ms for attempt in assignment.search_history)
        for assignment in assignments.values()
    )

    for scene in plan.scenes:
        if scene.scene_id in selected_ids and scene.scene_id not in process_ids:
            assignments[scene.scene_id] = SceneMediaAssignment(
                scene_id=scene.scene_id,
                status="pending_review",
                warnings=["scene search limit reached; retry this scene explicitly later"],
                attempts=(
                    assignments[scene.scene_id].attempts
                    if scene.scene_id in assignments
                    else 1
                ),
            )

    used_resources = {
        entry.selected_candidate.resource_fingerprint: entry.scene_id
        for entry in assignments.values()
        if entry.scene_id not in process_ids and entry.selected_candidate is not None
    }
    used_file_hashes = {}
    for entry in assignments.values():
        if entry.scene_id in process_ids or entry.selected_candidate is None:
            continue
        report = entry.selected_candidate.quality_report
        if report is not None:
            used_file_hashes[report.asset_sha256] = entry.scene_id
    for scene in plan.scenes:
        if scene.scene_id not in process_ids:
            continue
        previous_attempts = assignments.get(scene.scene_id)
        try:
            assignment = _assign_scene(
                task_id,
                scene,
                aspect,
                used_resources,
                visual_validation,
                cached_assessments,
                used_file_hashes,
            )
            if previous_attempts is not None:
                assignment.attempts = previous_attempts.attempts + 1
                previous_attempt = SceneMediaAttempt(
                    status=previous_attempts.status,
                    search_queries=previous_attempts.search_queries,
                    candidates=previous_attempts.candidates,
                    selected_candidate=previous_attempts.selected_candidate,
                    provider_errors=previous_attempts.provider_errors,
                    warnings=previous_attempts.warnings,
                    elapsed_ms=previous_attempts.elapsed_ms,
                    provider_search_requests=previous_attempts.provider_search_requests,
                    visual_validation_requests=previous_attempts.visual_validation_requests,
                    visual_cache_hits=previous_attempts.visual_cache_hits,
                    quality_cache_hits=previous_attempts.quality_cache_hits,
                    download_attempts=previous_attempts.download_attempts,
                )
                assignment.search_history = (
                    previous_attempts.search_history + [previous_attempt]
                )[-20:]
            assignments[scene.scene_id] = assignment
            if assignment.selected_candidate is not None:
                used_resources[assignment.selected_candidate.resource_fingerprint] = scene.scene_id
        except Exception as exc:
            logger.error(
                "scene media selection failed: task_id={}, scene_id={}, error={}",
                task_id, scene.scene_id, _safe_error(exc),
            )
            failed_assignment = SceneMediaAssignment(
                scene_id=scene.scene_id,
                status="failed",
                provider_errors=[_safe_error(exc)],
                warnings=["scene remains available for a later retry"],
                attempts=(previous_attempts.attempts + 1) if previous_attempts else 1,
            )
            if previous_attempts is not None:
                failed_assignment.search_history = previous_attempts.search_history
            assignments[scene.scene_id] = failed_assignment

    manifest = SceneMediaManifest(
        plan_id=plan.plan_id,
        script_sha256=plan.script_sha256,
        created_at=created_at,
        updated_at=datetime.now(timezone.utc),
        assignments=[
            assignments[scene.scene_id]
            for scene in plan.scenes
            if scene.scene_id in assignments
        ],
        max_parallel_searches=_setting_int("scene_media_search_concurrency", 4, 1, 16),
        total_provider_search_requests=previous_total_searches + sum(
            entry.provider_search_requests for entry in assignments.values()
        ),
        total_visual_validation_requests=previous_total_visual_checks + sum(
            entry.visual_validation_requests for entry in assignments.values()
        ),
        total_visual_cache_hits=sum(
            entry.visual_cache_hits
            + sum(attempt.visual_cache_hits for attempt in entry.search_history)
            for entry in assignments.values()
        ),
        total_quality_cache_hits=sum(
            entry.quality_cache_hits
            + sum(attempt.quality_cache_hits for attempt in entry.search_history)
            for entry in assignments.values()
        ),
        total_download_attempts=previous_total_downloads + sum(
            entry.download_attempts for entry in assignments.values()
        ),
        total_elapsed_ms=previous_total_elapsed
        + sum(entry.elapsed_ms for entry in assignments.values()),
    )
    task_artifacts.write_scene_media_manifest(task_id, manifest.model_dump(mode="json"))
    return manifest
