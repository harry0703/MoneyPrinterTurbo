"""Playbook-shaped system prompt for the script step.

The rules come from docs/playbook (script.md, hooks.md, timing.md, formats.md).
Selected with ``script_prompt_preset = "playbook"``; with the key unset the
pipeline keeps the generic upstream prompt.
"""

from functools import lru_cache
from pathlib import Path

from loguru import logger

PLAYBOOK_PRESET = "playbook"
DEFAULT_PLATFORM = "tiktok"
# Narration pace of the TTS voices at rate 1.0, used to turn a duration prior
# into a word budget the model can actually aim at.
WORDS_PER_SECOND = 2.5

_TEMPLATE_PATH = Path(__file__).parent / "data" / "script_prompt_playbook.md"

# Duration priors from docs/playbook/timing.md. They are experiment priors, not
# constants: account-level data is expected to replace them.
DURATION_PRIORS: dict[str, tuple[int, int]] = {
    "tiktok": (20, 30),
    "instagram_reels": (45, 60),
    "youtube_shorts": (20, 40),
}

_PLATFORM_ALIASES = {
    "tiktok": "tiktok",
    "tt": "tiktok",
    "instagram": "instagram_reels",
    "instagram_reels": "instagram_reels",
    "reels": "instagram_reels",
    "youtube": "youtube_shorts",
    "youtube_shorts": "youtube_shorts",
    "shorts": "youtube_shorts",
}

_PLATFORM_LABELS = {
    "tiktok": "TikTok",
    "instagram_reels": "Instagram Reels",
    "youtube_shorts": "YouTube Shorts",
}

# Format registry from docs/playbook/formats.md. Formats with a documented
# skeleton carry it; the rest only constrain the storytelling mechanic.
FORMAT_SKELETONS: dict[str, str] = {
    "micro_documentary": "",
    "mystery_reveal": (
        "hook -> open loop -> clues and context -> escalation -> reveal -> "
        "optional second payoff"
    ),
    "myth_busting": "everyone says X -> why X is believed -> what actually happened",
    "explainer": "why does X happen -> mechanism -> consequence",
    "one_detail": (
        "point at a detail almost nobody noticed -> show it -> explain why it matters"
    ),
    "hot_take": "",
    "story_twist": "",
    "ranking": "",
    "timeline": "",
    "primary_source_reveal": (
        "point at a real document, chart, map or record -> highlight the exact "
        "part that matters -> what it proves"
    ),
    "before_after": "",
    "three_clues": "",
    "comment_followup": "",
    "news_context": "",
    "why_it_happened": "",
}


def _resolve_platform(platform: str | None) -> str:
    value = (platform or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not value:
        return DEFAULT_PLATFORM
    resolved = _PLATFORM_ALIASES.get(value)
    if resolved is None:
        logger.warning(
            f"script prompt preset: unknown platform '{platform}', "
            f"falling back to '{DEFAULT_PLATFORM}'"
        )
        return DEFAULT_PLATFORM
    return resolved


def _resolve_format(video_format: str | None) -> str:
    value = (video_format or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not value:
        return ""
    if value not in FORMAT_SKELETONS:
        logger.warning(
            f"script prompt preset: unknown format '{video_format}', "
            "the model will pick the storytelling mechanic"
        )
        return ""
    return value


def _format_block(video_format: str) -> str:
    if not video_format:
        return ""

    skeleton = FORMAT_SKELETONS[video_format]
    lines = [
        "",
        "## Format:",
        f"Build the story with the {video_format.replace('_', ' ')} mechanic.",
    ]
    if skeleton:
        lines.append(f"Skeleton: {skeleton}.")
    lines.append("")
    return "\n".join(lines)


@lru_cache(maxsize=1)
def _template() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def build_playbook_system_prompt(
    platform: str = "",
    video_format: str = "",
) -> str:
    resolved_platform = _resolve_platform(platform)
    resolved_format = _resolve_format(video_format)
    low_seconds, high_seconds = DURATION_PRIORS[resolved_platform]
    low_words = int(low_seconds * WORDS_PER_SECOND)
    high_words = int(high_seconds * WORDS_PER_SECOND)

    return (
        _template()
        .format(
            duration_line=(
                f"Target runtime for {_PLATFORM_LABELS[resolved_platform]}: "
                f"{low_seconds}-{high_seconds} seconds when read aloud."
            ),
            word_budget_line=(
                f"That is roughly {low_words}-{high_words} spoken words in total, "
                f"and {high_words} words is a hard cap for the whole script."
            ),
            format_block=_format_block(resolved_format),
        )
        .strip()
    )
