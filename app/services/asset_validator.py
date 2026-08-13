"""Asset Validator (heuristic scoring).

Provides a simple, measurable scoring function per candidate asset.
This is intentionally heuristic and easy to extend.

Score components (0..1 each):
- semantic_score: placeholder (use search relevance later)
- duration_score: compares candidate duration vs requested
- aspect_score: matches aspect_ratio if provided
- quality_score: based on resolution if provided
- uniqueness_score: placeholder (requires history)

final_score = weighted sum (equal weights initially)
"""
from __future__ import annotations

from typing import Dict, Any


def _clamp01(v: float) -> float:
    if v is None:
        return 0.0
    try:
        v = float(v)
    except Exception:
        return 0.0
    if v < 0:
        return 0.0
    if v > 1:
        return 1.0
    return v


def score_candidate(scene: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Return component scores and final_score for a single candidate.

    candidate expected fields (best-effort): duration, width, height
    """
    # placeholders for components not yet implemented
    semantic_score = _clamp01(candidate.get("semantic_score", 0.0))

    # duration score: 1 if candidate.duration >= scene.duration; else ratio
    req_dur = float(scene.get("duration") or 0.0)
    cand_dur = float(candidate.get("duration") or 0.0)
    duration_score = 0.0
    if req_dur <= 0:
        duration_score = 1.0 if cand_dur > 0 else 0.0
    else:
        duration_score = min(1.0, cand_dur / req_dur)

    # aspect score: if scene requests aspect, compare; otherwise 1.0
    aspect_score = 1.0
    req_aspect = scene.get("aspect_ratio")
    if req_aspect:
        # candidate may provide width/height
        w = candidate.get("width")
        h = candidate.get("height")
        try:
            if w and h:
                cand_aspect = float(w) / float(h)
                # tolerance 10%
                aspect_score = max(0.0, 1.0 - abs(cand_aspect - float(req_aspect)) / float(req_aspect) )
                aspect_score = _clamp01(aspect_score)
            else:
                aspect_score = 0.0
        except Exception:
            aspect_score = 0.0

    # quality_score: crude resolution check (HD 720p baseline)
    quality_score = 0.0
    w = candidate.get("width") or 0
    h = candidate.get("height") or 0
    try:
        if int(w) >= 1280 and int(h) >= 720:
            quality_score = 1.0
        elif int(w) >= 854 and int(h) >= 480:
            quality_score = 0.8
        elif int(w) > 0 and int(h) > 0:
            quality_score = 0.5
        else:
            quality_score = 0.0
    except Exception:
        quality_score = 0.0

    uniqueness_score = _clamp01(candidate.get("uniqueness_score", 1.0))

    # equal weights
    components = [semantic_score, duration_score, aspect_score, quality_score, uniqueness_score]
    final_score = sum(components) / len(components) if components else 0.0

    return {
        "asset": candidate.get("asset_id") or candidate.get("local_file") or None,
        "semantic_score": round(semantic_score, 3),
        "duration_score": round(duration_score, 3),
        "aspect_score": round(aspect_score, 3),
        "quality_score": round(quality_score, 3),
        "uniqueness_score": round(uniqueness_score, 3),
        "final_score": round(final_score, 3),
    }
