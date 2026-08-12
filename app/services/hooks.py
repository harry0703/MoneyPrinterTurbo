"""Hook generation and scoring for the script step.

The rules come from docs/playbook/hooks.md: a hook is produced by its own step
that proposes several candidates and picks one, never as a first sentence the
script generator writes in passing. This module owns the prompts and the
validation; the provider calls live in ``app.services.llm``.
"""

import json
import re

from loguru import logger

from app.services import script_prompt

# Registry from docs/playbook/hooks.md. The value is the gloss handed to the
# model; the key is what gets logged as hook_type and joined with retention.
HOOK_CLASSES: dict[str, str] = {
    "contradiction": "a widely held belief set against the fact",
    "specific_detail": "a small concrete detail almost nobody noticed",
    "direct_question": "a question aimed straight at the viewer",
    "unexpected_number": "a number that does not fit expectations",
    "visual_instruction": "an instruction to look at one exact point of the frame",
    "controversy": "a claim the audience will want to argue with",
    "stakes": "what was actually at risk",
    "prediction": "a claim about what happens next",
    "before_after": "the state before set against the state after",
    "myth": "everyone says X",
    "confession": "an admission or first-hand experience",
    "challenge": "a challenge thrown at the viewer",
}

MIN_HOOK_LENGTH = 8
MAX_HOOK_WORDS = 25
DEFAULT_CANDIDATE_COUNT = 5
MAX_CANDIDATE_COUNT = 12

# Openings docs/playbook/hooks.md rules out: greetings, channel intros and topic
# announcements. Matched against the start of the hook only — the same words
# later in a sentence can be legitimate.
_BANNED_OPENINGS = re.compile(
    r"^\W*("
    r"hi\b|hello\b|hey\b|welcome\b|greetings\b|good\s+(morning|evening)\b"
    r"|today\s+(we|i)\b|in\s+this\s+video\b|let'?s\s+(talk|look|dive)\b"
    r"|we('| a)re\s+going\s+to\s+(talk|look)\b|i'?m\s+going\s+to\s+(tell|show)\b"
    r"|привет|здравствуй|добрый\s+(день|вечер)|сегодня\s+(мы|я)\b"
    r"|в\s+этом\s+(видео|ролике)\b|поговорим\b|расскажу\b|давайте\b"
    r")",
    re.IGNORECASE,
)


def normalize_candidate_count(count: object) -> int:
    try:
        value = int(count)
    except (TypeError, ValueError):
        return DEFAULT_CANDIDATE_COUNT
    if value <= 0:
        return 0
    return min(value, MAX_CANDIDATE_COUNT)


def rejection_reason(hook: str) -> str:
    """Return why a hook is unusable, or an empty string when it passes."""
    text = (hook or "").strip()
    if len(text) < MIN_HOOK_LENGTH:
        return "too short"
    if len(text.split()) > MAX_HOOK_WORDS:
        return f"longer than {MAX_HOOK_WORDS} words"
    if _BANNED_OPENINGS.match(text):
        return "opens with a greeting, an intro or a topic announcement"
    return ""


def build_candidates_prompt(
    video_subject: str,
    language: str = "",
    count: int = DEFAULT_CANDIDATE_COUNT,
    platform: str = "",
    video_format: str = "",
) -> str:
    count = normalize_candidate_count(count) or DEFAULT_CANDIDATE_COUNT
    classes = "\n".join(f"- {name}: {gloss}" for name, gloss in HOOK_CLASSES.items())
    resolved_format, skeleton = script_prompt.format_skeleton(video_format)

    prompt = f"""
# Role: Short-Form Video Hook Writer

## Goals:
Write {count} competing opening lines for one short vertical video about the
subject below. The opening line is spoken first and has to earn the next second
on its own.

## Constrains:
1. return a json-array of objects with the keys "hook" and "hook_type".
2. "hook_type" must be one of the classes listed below.
3. give every candidate a different angle; {count} rewordings of one idea is a
   failed answer. Use at least three different hook_type values.
4. concrete from the very first word: a name, a number, a place, a visible
   detail. No adjectives standing in for facts.
5. open a loop the video can close later.
6. never open with a greeting, a channel intro or a topic announcement.
7. one sentence, at most {MAX_HOOK_WORDS} words, spoken language, no markdown,
   no emojis, no quotes around the line.
8. write hooks for this exact subject; a template where only the proper nouns
   change is a failed answer.
9. you must only return the json-array. you must not return anything else.

## Hook classes:
{classes}

## Output Example:
[{{"hook": "This goal should never have counted.", "hook_type": "controversy"}}]

## Video Subject:
{video_subject}
""".strip()

    if resolved_format:
        line = f"\n\n## Format:\nThe video uses the {resolved_format.replace('_', ' ')} mechanic."
        if skeleton:
            line += f"\nSkeleton: {skeleton}."
        prompt += line
    if platform:
        prompt += f"\n\n## Platform:\n{script_prompt.platform_label(platform)}."
    if language:
        prompt += f"\n\n## Language:\nWrite the hooks in {language}."

    return prompt


def parse_candidates(parsed: object, count: int) -> list[dict]:
    """Validate a parsed candidates payload into usable hooks."""
    if not isinstance(parsed, list):
        logger.error("hook candidates response is not a list")
        return []

    candidates: list[dict] = []
    seen: set[str] = set()
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        hook = str(entry.get("hook") or "").strip().strip('"')
        reason = rejection_reason(hook)
        if reason:
            if hook:
                logger.warning(f"dropping hook candidate ({reason}): {hook}")
            continue

        key = hook.casefold()
        if key in seen:
            continue
        seen.add(key)

        hook_type = str(entry.get("hook_type") or "").strip().lower()
        if hook_type not in HOOK_CLASSES:
            # An unusable label must not cost a usable hook: the text still
            # holds, only the analytics dimension is lost.
            if hook_type:
                logger.warning(f"unknown hook_type '{hook_type}', storing as unknown")
            hook_type = "unknown"

        candidates.append({"hook": hook, "hook_type": hook_type})
        if len(candidates) >= count:
            break

    return candidates


def build_scorer_prompt(video_subject: str, candidates: list[dict]) -> str:
    numbered = "\n".join(
        f"{index}. [{item['hook_type']}] {item['hook']}"
        for index, item in enumerate(candidates)
    )
    return f"""
# Role: Short-Form Video Hook Scorer

## Goals:
Pick the one opening line most likely to stop a viewer from scrolling on a short
vertical video about the subject below.

## Judge on, in this order:
1. does it make the next second feel necessary,
2. is it concrete from the first word,
3. does it open a loop the video can close,
4. is it specific to this subject rather than a reusable template,
5. would a viewer who knows the subject still find it new.

## Constrains:
1. return a json-object with the keys "best" and "reason".
2. "best" must be the number of one of the candidates listed below.
3. "reason" must be one short sentence.
4. do not rewrite, merge or improve the candidates; pick one as written.
5. you must only return the json-object. you must not return anything else.

## Output Example:
{{"best": 2, "reason": "names the detail the viewer is told to look for"}}

## Video Subject:
{video_subject}

## Candidates:
{numbered}
""".strip()


def parse_choice(parsed: object, candidates: list[dict]) -> dict:
    """Resolve a scorer payload into the winning candidate."""
    if not candidates:
        return {}
    if not isinstance(parsed, dict):
        logger.warning("hook scorer response is not an object, keeping the first hook")
        return dict(candidates[0])

    try:
        index = int(parsed.get("best"))
    except (TypeError, ValueError):
        logger.warning("hook scorer returned no usable index, keeping the first hook")
        return dict(candidates[0])

    if not 0 <= index < len(candidates):
        logger.warning(
            f"hook scorer picked {index}, outside 0..{len(candidates) - 1}; "
            "keeping the first hook"
        )
        return dict(candidates[0])

    chosen = dict(candidates[index])
    reason = str(parsed.get("reason") or "").strip()
    if reason:
        chosen["reason"] = reason
    return chosen


def extract_json(text: str) -> object:
    """Parse a JSON payload out of a raw provider response."""
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped).strip()
    try:
        return json.loads(stripped)
    except Exception:
        match = re.search(r"[\[{].*[\]}]", stripped, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group())
