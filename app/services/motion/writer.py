"""Motion Studio writer: asks the user's chosen LLM for a storyboard and validates it.

The API key arrives with the request, is passed to litellm for this call only, and is never stored,
logged or returned. Provider errors are mapped to plain messages with the key scrubbed out.
"""

import json
import re
from dataclasses import asdict, dataclass

from pydantic import ValidationError

from app.models.motion import LlmSettings, MotionJobRequest, Storyboard
from app.services.motion.errors import MotionError
from app.services.motion.speech import VOICE_BY_ID

MAX_TOKENS = 8000  # reasoning models spend part of this before answering
TIMEOUT_S = 150


@dataclass(frozen=True)
class Provider:
    label: str
    prefix: str  # litellm route prefix
    models: tuple[str, ...]  # suggestions only; any model name is accepted
    needs_key: bool = True
    needs_base_url: bool = False
    default_base_url: str | None = None
    key_url: str | None = None
    json_mode: bool = False  # supports response_format json_object reliably


PROVIDERS = {
    "openai": Provider("OpenAI", "openai/", ("gpt-5-mini", "gpt-5", "gpt-4.1"),
                       key_url="https://platform.openai.com/api-keys", json_mode=True),
    "anthropic": Provider("Anthropic", "anthropic/", ("claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"),
                          key_url="https://console.anthropic.com/settings/keys"),
    "gemini": Provider("Google Gemini", "gemini/", ("gemini-2.5-flash", "gemini-2.5-pro"),
                       key_url="https://aistudio.google.com/apikey", json_mode=True),
    "openrouter": Provider("OpenRouter", "openrouter/", ("anthropic/claude-sonnet-5-5", "openai/gpt-5-mini", "google/gemini-2.5-flash"),
                           key_url="https://openrouter.ai/keys"),
    "deepseek": Provider("DeepSeek", "deepseek/", ("deepseek-chat",),
                         key_url="https://platform.deepseek.com/api_keys", json_mode=True),
    "ollama": Provider("Ollama (local)", "ollama_chat/", ("llama3.1", "qwen2.5"), needs_key=False,
                       default_base_url="http://127.0.0.1:11434"),
    "custom": Provider("OpenAI-compatible", "openai/", (), needs_key=False, needs_base_url=True),
}


def provider_options() -> list[dict]:
    return [{"id": pid, **{k: v for k, v in asdict(p).items() if k not in ("prefix", "json_mode")}} for pid, p in PROVIDERS.items()]


SYSTEM_PROMPT = """You write and storyboard vertical YouTube Shorts (1080x1920) that are animated as motion graphics: big text, numbers and cards timed to the narration, with a cartoon host who speaks every line.

Return ONLY a JSON object, no markdown, in this shape:
{{"beats": [{{"say": "...", "layout": "...", "mood": "...", "emphasis": "...", "...layout fields": "..."}}],
 "youtube": {{"title": "...", "description": "...", "hashtags": ["#..."]}}}}

Beats
- 4 to 8 beats. The whole narration is about 90 to 130 words, 35 to 55 seconds when spoken.
- Beat 1 is the hook (a sharp question or a surprising fact) and uses the "hook" or "big_number" layout. The last beat uses "outro" with a call to action.
- "say": what the host speaks in this beat, 1 or 2 short sentences in {language}. {language_rules}
- "emphasis": one word copied exactly from "say": the moment the main visual pops.
- "mood": neutral, happy, excited, wink, shocked or sad. Match the content and vary it.
- On-screen text is short and punchy. Never copy "say" onto the screen.

Layouts and fields (stay within the limits):
- hook: headline (max 48 characters), kicker (big punchline, max 18), tone
- big_number: label (max 40), value (the number as shown, max 14, e.g. "₹10,00,000", "42%", "3x"), headline (optional line under it, max 60), tone
- compare: headline (max 48), left {{label (max 26), value (max 14), tone}}, right {{same}}, kicker (optional verdict, max 24)
- list: headline (max 48), items (2 to 4 of {{text (max 34), tone}}), numbered (true for steps)
- statement: headline (the key sentence, max 110), kicker (optional label, max 24)
- outro: headline (the call to action, max 28), label (optional disclaimer, max 90)
- tone is "good" (gains, right choices), "bad" (losses, risks, mistakes) or "neutral".

Facts
- Use only facts from the brief or well-established common knowledge. Never invent statistics, prices or rates; if the brief gives no number, pick a layout without one.
- For money, health or legal topics, the outro label says it is information only, not advice.

YouTube
- title: max 70 characters. Keep the creator's title unless it is unclear.
- description: 2 to 4 short lines in {language} summing up the video, plus the disclaimer when one applies.
- hashtags: 3 to 6 relevant tags including #Shorts."""

DEVANAGARI_RULES = (
    "Write in Devanagari, keeping common English terms (credit card, SIP, AI, app names) in English letters. "
    "In \"say\", write numbers as words (e.g. \"साढ़े तीन प्रतिशत\"); on screen use digits and symbols."
)
DEFAULT_RULES = "In \"say\", write numbers the way they are spoken; on screen use digits and symbols."

BRIEF = """Creator's brief
Title: {title}
Topic: {topic}
Description and key points:
{description}"""


def build_messages(request: MotionJobRequest) -> list[dict]:
    language = VOICE_BY_ID[request.voice]["language"]
    rules = DEVANAGARI_RULES if language in ("Hindi", "Marathi") else DEFAULT_RULES
    return [
        {"role": "system", "content": SYSTEM_PROMPT.format(language=language, language_rules=rules)},
        {"role": "user", "content": BRIEF.format(title=request.title, topic=request.topic,
                                                  description=request.description or "(none given)")},
    ]


def extract_json(reply: str) -> dict:
    """The first JSON object in a reply, tolerating code fences and chatter around it."""
    fence = re.search(r"```(?:json)?\s*(.*?)```", reply, re.S)
    text = fence.group(1) if fence else reply
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("the reply has no JSON object")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("the reply is not a JSON object")
    return data


def describe_problems(error: Exception) -> str:
    if isinstance(error, ValidationError):
        return "; ".join(f"{'.'.join(map(str, e['loc'])) or 'root'}: {e['msg']}" for e in error.errors()[:8])
    return str(error)


_KEYLIKE = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{20,}|[A-Za-z0-9_-]{32,})")


def scrub(text: str, key: str | None) -> str:
    if key:
        text = text.replace(key, "***")
    return _KEYLIKE.sub("***", text)


def friendly_error(error: Exception, provider: Provider, key: str | None) -> str:
    import litellm

    name = provider.label
    known = [
        (litellm.AuthenticationError, f"{name} rejected the API key. Check it and try again."),
        (litellm.NotFoundError, f"{name} doesn't know that model. Check the model name."),
        (litellm.RateLimitError, f"{name} says you're over your rate limit or quota. Wait a minute or check your billing."),
        (litellm.ContextWindowExceededError, "The brief is too long for this model. Shorten the description."),
        (litellm.Timeout, f"{name} took too long to answer. Try again or pick a faster model."),
        (litellm.APIConnectionError, f"Couldn't reach {name}. Check your internet connection or the base URL."),
    ]
    for cls, message in known:
        if isinstance(error, cls):
            return message
    if provider.needs_base_url or provider.default_base_url:
        # A user-supplied URL may point at an internal service; don't reflect what it answered.
        status = getattr(error, "status_code", None)
        return f"{name} returned an error{f' (HTTP {status})' if status else ''}. Check the base URL and model name."
    detail = scrub(str(error), key).strip().splitlines()[0][:240] if str(error).strip() else type(error).__name__
    return f"{name} returned an error: {detail}"


def complete(settings: LlmSettings, messages: list[dict]) -> str:
    import litellm

    provider = PROVIDERS[settings.provider]
    key = settings.api_key.get_secret_value() if settings.api_key else None
    if provider.needs_key and not key:
        raise MotionError(f"Add your {provider.label} API key.")
    base_url = settings.base_url or provider.default_base_url
    if provider.needs_base_url and not base_url:
        raise MotionError("Add the base URL of your OpenAI-compatible endpoint.")
    extra = {"response_format": {"type": "json_object"}} if provider.json_mode else {}
    try:
        response = litellm.completion(
            # Never None: litellm would fall back to the server's own OPENAI_API_KEY etc. and send it to
            # whatever base URL the request named.
            model=provider.prefix + settings.model, messages=messages, api_key=key or "no-key", api_base=base_url,
            max_tokens=MAX_TOKENS, timeout=TIMEOUT_S, drop_params=True, **extra,
        )
        reply = response.choices[0].message.content or ""
    except Exception as error:  # every provider failure becomes a safe message; no traceback with the key
        raise MotionError(friendly_error(error, provider, key)) from None
    if not reply.strip():
        raise MotionError(f"{provider.label} returned an empty answer. Try again or pick another model.")
    return reply


def write(request: MotionJobRequest) -> Storyboard:
    """Storyboard for the brief; one repair round when the first answer doesn't validate."""
    messages = build_messages(request)
    reply = complete(request.llm, messages)
    try:
        return Storyboard.model_validate(extract_json(reply))
    except ValueError as error:  # bad JSON or schema (pydantic's ValidationError is a ValueError)
        messages += [
            {"role": "assistant", "content": reply},
            {"role": "user", "content": f"That JSON is invalid: {describe_problems(error)}. "
                                        "Reply with the corrected, complete JSON object only."},
        ]
    reply = complete(request.llm, messages)
    try:
        return Storyboard.model_validate(extract_json(reply))
    except ValueError:
        raise MotionError("The AI's storyboard didn't match the required format twice. "
                          "Try again or pick a stronger model.") from None
