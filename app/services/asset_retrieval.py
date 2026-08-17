"""
Asset selection for the photo library — script lines in, library assets out.

A visual brief (the LLM's description of the frame a line needs) is what gets
vectorized, not the line itself: the line is speech, the asset vector holds a
picture description. The same brief travels on as the search query for anything
the library could not cover.

Knows nothing about rendering: it returns assets plus the numbers behind every
choice, and the pipeline decides what to do with them.

Config (config.toml, [app] section):
    photo_library_weight_semantic = 0.7
    photo_library_weight_tags = 0.3
    photo_library_weight_recency = 0.2
    photo_library_score_accept = 0.62
    photo_library_score_reject = 0.45
    photo_library_recency_window = 20
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional, Sequence

from loguru import logger

from app.config import config
from app.services import asset_embed, asset_library, llm
from app.services.asset_library import Asset

DEFAULT_WEIGHT_SEMANTIC = 0.7
DEFAULT_WEIGHT_TAGS = 0.3
DEFAULT_WEIGHT_RECENCY = 0.2
DEFAULT_SCORE_ACCEPT = 0.62
DEFAULT_SCORE_REJECT = 0.45
DEFAULT_RECENCY_WINDOW = 20

VERDICT_ACCEPT = "accept"
VERDICT_GRAY = "gray"
VERDICT_REJECT = "reject"
VERDICT_REQUIRED = "required"

REASON_NO_CANDIDATES = "no_candidates"
REASON_BELOW_REJECT = "below_reject"
REASON_REQUIRED_MISSING = "required_missing"

REQUIRE_PATH_PREFIX = "path:"
REQUIRE_TAG_PREFIX = "tag:"

_POOL_LIMIT = 20
_REQUIRE_LIMIT = 200
_PATH_PAGE = 500


@dataclass
class ScoredCandidate:
    asset: Asset
    cosine: float
    tag_score: float
    recency_penalty: float
    score: float


@dataclass
class Assignment:
    index: int
    brief: str
    asset: Asset
    verdict: str
    candidate: Optional[ScoredCandidate] = None
    # Gap between this candidate and the runner-up: a score sitting in the grey
    # zone is far more trustworthy when nothing else comes close.
    margin: Optional[float] = None


@dataclass
class Unsatisfied:
    index: Optional[int]
    brief: str
    reason: str
    require: str = ""


@dataclass
class Selection:
    assignments: list[Assignment] = field(default_factory=list)
    unsatisfied: list[Unsatisfied] = field(default_factory=list)


def _conf_float(key: str, default: float) -> float:
    try:
        return float(config.app.get(key, default))
    except (TypeError, ValueError):
        return default


def _conf_int(key: str, default: int) -> int:
    try:
        return int(config.app.get(key, default))
    except (TypeError, ValueError):
        return default


def score_verdict(score: float) -> str:
    """Where a score falls on the accept / grey zone / reject ladder."""
    if score >= _conf_float("photo_library_score_accept", DEFAULT_SCORE_ACCEPT):
        return VERDICT_ACCEPT
    if score >= _conf_float("photo_library_score_reject", DEFAULT_SCORE_REJECT):
        return VERDICT_GRAY
    return VERDICT_REJECT


def _cosine(asset: Asset) -> float:
    # pgvector's <=> operator returns cosine distance, not similarity.
    if asset.distance is None:
        return 0.0
    return 1.0 - float(asset.distance)


def _tag_score(asset: Asset, prefer_tags: Sequence[str]) -> float:
    wanted = {str(tag).strip().lower() for tag in prefer_tags if str(tag).strip()}
    if not wanted:
        return 0.0
    weights = {
        str(tag.tag).strip().lower(): min(max(float(tag.weight), 0.0), 1.0)
        for tag in asset.tags
    }
    return sum(weights.get(name, 0.0) for name in wanted) / len(wanted)


def _recency_penalty(uses: int) -> float:
    if uses <= 0:
        return 0.0
    return 1.0 - 1.0 / (1.0 + uses)


def _usage_counts() -> dict[int, int]:
    window = _conf_int("photo_library_recency_window", DEFAULT_RECENCY_WINDOW)
    if window <= 0:
        return {}
    try:
        return asset_library.usage_counts(window)
    except Exception as e:  # noqa: BLE001 - freshness is a nudge, not a requirement
        logger.warning(f"asset_retrieval: usage lookup failed: {e}")
        return {}


def _score(
    assets: Sequence[Asset], prefer_tags: Sequence[str], usage: dict[int, int]
) -> list[ScoredCandidate]:
    weight_semantic = _conf_float(
        "photo_library_weight_semantic", DEFAULT_WEIGHT_SEMANTIC
    )
    weight_tags = _conf_float("photo_library_weight_tags", DEFAULT_WEIGHT_TAGS)
    weight_recency = _conf_float("photo_library_weight_recency", DEFAULT_WEIGHT_RECENCY)

    scored: list[ScoredCandidate] = []
    for asset in assets:
        cosine = _cosine(asset)
        tag_score = _tag_score(asset, prefer_tags)
        recency = _recency_penalty(usage.get(asset.id, 0))
        scored.append(
            ScoredCandidate(
                asset=asset,
                cosine=cosine,
                tag_score=tag_score,
                recency_penalty=recency,
                score=weight_semantic * cosine
                + weight_tags * tag_score
                - weight_recency * recency,
            )
        )
    scored.sort(key=lambda item: (-item.score, item.asset.id))
    return scored


def _rank(
    brief: str,
    usage: dict[int, int],
    *,
    prefer_tags: Sequence[str] = (),
    only_tags: Sequence[str] = (),
    exclude_tags: Sequence[str] = (),
    exclude_ids: Sequence[int] = (),
    limit: int = 5,
) -> list[ScoredCandidate]:
    embedding = asset_embed.embed_text(brief)
    if embedding is None:
        logger.warning(f"asset_retrieval: no embedding for brief: {brief!r}")
        return []
    try:
        found = asset_library.search_assets(
            embedding.vector,
            limit=max(limit, _POOL_LIMIT),
            any_tags=tuple(only_tags),
            exclude_tags=tuple(exclude_tags),
            exclude_ids=tuple(exclude_ids),
        )
    except Exception as e:  # noqa: BLE001 - an unreachable library degrades, not raises
        logger.warning(f"asset_retrieval: library search failed: {e}")
        return []
    return _score(found, prefer_tags, usage)[:limit]


def rank_candidates(
    brief: str,
    *,
    prefer_tags: Sequence[str] = (),
    only_tags: Sequence[str] = (),
    exclude_tags: Sequence[str] = (),
    exclude_ids: Sequence[int] = (),
    limit: int = 5,
) -> list[ScoredCandidate]:
    """
    Best library assets for one visual brief, with the score broken into parts.

    The parts are the point: thresholds are calibrated by looking at them on a
    live library, so they must survive the trip to the caller.
    """
    return _rank(
        brief,
        _usage_counts(),
        prefer_tags=prefer_tags,
        only_tags=only_tags,
        exclude_tags=exclude_tags,
        exclude_ids=exclude_ids,
        limit=limit,
    )


def _normalize_path(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    return os.path.normpath(text).replace("\\", "/").strip("/")


def _asset_by_path(rel_path: str) -> Optional[Asset]:
    wanted = _normalize_path(rel_path)
    if not wanted:
        return None
    offset = 0
    while True:
        page = asset_library.list_assets(limit=_PATH_PAGE, offset=offset)
        for asset in page:
            if _normalize_path(asset.rel_path) == wanted:
                return asset
        if len(page) < _PATH_PAGE:
            return None
        offset += _PATH_PAGE


def _resolve_require(token: str) -> list[Asset]:
    value = str(token or "").strip()
    if value.startswith(REQUIRE_PATH_PREFIX):
        found = _asset_by_path(value[len(REQUIRE_PATH_PREFIX) :])
        return [found] if found else []
    if value.startswith(REQUIRE_TAG_PREFIX):
        tag = value[len(REQUIRE_TAG_PREFIX) :].strip()
        if not tag:
            return []
        return asset_library.list_assets(any_tags=[tag], limit=_REQUIRE_LIMIT)
    logger.warning(f"asset_retrieval: unknown photo requirement: {value!r}")
    return []


def _place_required(
    require: Sequence[str],
    order: list[int],
    pools: dict[int, list[ScoredCandidate]],
    briefs: dict[int, str],
    taken: dict[int, Assignment],
    used_ids: set[int],
) -> list[str]:
    """Lay the owner's assets over the timeline, keeping the requested order."""
    cosines = {
        position: {item.asset.id: item.cosine for item in pool}
        for position, pool in pools.items()
    }
    missing: list[str] = []
    cursor = 0
    for token in require:
        assets = [a for a in _resolve_require(token) if a.id not in used_ids]
        free = [(slot, pos) for slot, pos in enumerate(order) if pos not in taken]
        free = [pair for pair in free if pair[0] >= cursor]
        if not assets or not free:
            missing.append(str(token))
            continue

        best: Optional[tuple[float, int, int]] = None
        chosen: Optional[Asset] = None
        for asset in assets:
            for slot, pos in free:
                cosine = cosines.get(pos, {}).get(asset.id)
                if cosine is None:
                    continue
                key = (-cosine, slot, asset.id)
                if best is None or key < best:
                    best, chosen = key, asset
        if best is None:
            # Nothing said where this asset fits, so the owner's own order does.
            slot, chosen = free[0][0], assets[0]
        else:
            slot = best[1]

        position = order[slot]
        taken[position] = Assignment(
            index=position,
            brief=briefs[position],
            asset=chosen,
            verdict=VERDICT_REQUIRED,
        )
        used_ids.add(chosen.id)
        cursor = slot + 1
    return missing


def select_assets(
    video_subject: str,
    subtitle_lines: Sequence[tuple],
    *,
    amount: int = 5,
    require: Sequence[str] = (),
    prefer_tags: Sequence[str] = (),
    only_tags: Sequence[str] = (),
    exclude_tags: Sequence[str] = (),
    app_config: Optional[dict] = None,
) -> Selection:
    """
    Pick a library asset for each line of the script worth illustrating.

    ``subtitle_lines`` holds ``((start, end), text)`` entries as produced by
    ``subtitle.file_to_subtitles``; assignments reference them by position.
    Places nothing could be found for come back as ``Unsatisfied`` carrying the
    brief, which doubles as a ready image search query.
    """
    try:
        return _select(
            video_subject,
            subtitle_lines,
            amount=amount,
            require=require,
            prefer_tags=prefer_tags,
            only_tags=only_tags,
            exclude_tags=exclude_tags,
            app_config=app_config,
        )
    except Exception as e:  # noqa: BLE001 - a broken library must not fail the task
        logger.warning(f"asset_retrieval: selection failed: {e}")
        return Selection()


def _select(
    video_subject: str,
    subtitle_lines: Sequence[tuple],
    *,
    amount: int,
    require: Sequence[str],
    prefer_tags: Sequence[str],
    only_tags: Sequence[str],
    exclude_tags: Sequence[str],
    app_config: Optional[dict],
) -> Selection:
    selection = Selection()
    if not asset_library.is_enabled():
        logger.warning("asset_retrieval: photo library is off, nothing to select")
        return selection
    if not subtitle_lines or amount <= 0:
        return selection

    raw_briefs = llm.generate_photo_briefs(
        video_subject, list(subtitle_lines), amount, app_config
    )
    briefs = {int(item["index"]): str(item["brief"]) for item in raw_briefs}
    if not briefs:
        logger.warning("asset_retrieval: no visual briefs for this script")

    usage = _usage_counts()
    order = sorted(briefs)
    pools = {
        position: _rank(
            briefs[position],
            usage,
            prefer_tags=prefer_tags,
            only_tags=only_tags,
            exclude_tags=exclude_tags,
            limit=_POOL_LIMIT,
        )
        for position in order
    }

    taken: dict[int, Assignment] = {}
    used_ids: set[int] = set()
    for token in _place_required(require, order, pools, briefs, taken, used_ids):
        logger.warning(
            f"asset_retrieval: no room left for required asset {token!r}, "
            f"{len(order)} slots in this video"
        )
        selection.unsatisfied.append(
            Unsatisfied(
                index=None, brief="", reason=REASON_REQUIRED_MISSING, require=token
            )
        )

    for position in order:
        if position in taken:
            continue
        brief = briefs[position]
        pool = [item for item in pools[position] if item.asset.id not in used_ids]
        if not pool:
            selection.unsatisfied.append(
                Unsatisfied(index=position, brief=brief, reason=REASON_NO_CANDIDATES)
            )
            continue
        top = pool[0]
        verdict = score_verdict(top.score)
        if verdict == VERDICT_REJECT:
            selection.unsatisfied.append(
                Unsatisfied(index=position, brief=brief, reason=REASON_BELOW_REJECT)
            )
            continue
        taken[position] = Assignment(
            index=position,
            brief=brief,
            asset=top.asset,
            verdict=verdict,
            candidate=top,
            margin=top.score - pool[1].score if len(pool) > 1 else None,
        )
        used_ids.add(top.asset.id)

    selection.assignments = [taken[position] for position in sorted(taken)]
    return selection
