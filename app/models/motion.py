"""Motion Studio models: the studio's job request and the storyboard the LLM must return."""

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)

ProviderId = Literal[
    "openai", "anthropic", "gemini", "openrouter", "deepseek", "ollama", "custom"
]
Tone = Literal["good", "bad", "neutral"]
Mood = Literal["neutral", "happy", "excited", "wink", "shocked", "sad"]
Layout = Literal["hook", "big_number", "compare", "list", "statement", "outro"]


def text(max_length: int, min_length: int = 1):
    """A stripped string with length bounds."""
    return Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=min_length, max_length=max_length
        ),
    ]


# ---------- request ----------
class LlmSettings(BaseModel):
    provider: ProviderId
    model: text(120)
    # Used for one provider call and dropped; never stored, logged or returned.
    api_key: SecretStr | None = None
    base_url: text(300, 0) | None = None

    @field_validator("api_key")
    @classmethod
    def key_length(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) > 512:
            raise ValueError("API key is too long")
        return value

    @field_validator("base_url")
    @classmethod
    def http_only(cls, value: str | None) -> str | None:
        if value and not value.lower().startswith(("http://", "https://")):
            raise ValueError("base URL must start with http:// or https://")
        return value or None


class MotionJobRequest(BaseModel):
    title: text(100)
    topic: text(300)
    description: text(3000, 0) = ""
    voice: text(80)
    character_id: (
        Annotated[str, StringConstraints(pattern=r"^(up|preset)-[A-Za-z0-9_-]{1,80}$")]
        | None
    ) = None
    llm: LlmSettings


# ---------- storyboard (LLM output) ----------
# Field caps are generous on purpose: the prompt asks for much shorter text and the engine shrinks
# text to fit its box, so only structural problems trigger a repair round.
class Side(BaseModel):
    label: text(40)
    value: text(24)
    tone: Tone = "neutral"


class Item(BaseModel):
    text: text(60)
    tone: Tone = "neutral"


LAYOUT_NEEDS = {
    "hook": ("headline",),
    "big_number": ("label", "value"),
    "compare": ("headline", "left", "right"),
    "list": ("headline", "items"),
    "statement": ("headline",),
    "outro": ("headline",),
}


class Beat(BaseModel):
    say: text(400)
    layout: Layout
    mood: Mood = "neutral"
    emphasis: text(60, 0) | None = None
    headline: text(160, 0) | None = None
    kicker: text(40, 0) | None = None
    label: text(140, 0) | None = None
    value: text(24, 0) | None = None
    tone: Tone = "good"
    left: Side | None = None
    right: Side | None = None
    items: list[Item] | None = Field(default=None, min_length=2, max_length=4)
    numbered: bool = False

    @model_validator(mode="after")
    def layout_fields(self) -> "Beat":
        missing = [name for name in LAYOUT_NEEDS[self.layout] if not getattr(self, name)]
        if missing:
            raise ValueError(f"a {self.layout} beat needs: {', '.join(missing)}")
        return self


class YoutubeMeta(BaseModel):
    title: text(100)
    description: text(4500)
    hashtags: list[str] = Field(min_length=1, max_length=10)

    @field_validator("hashtags", mode="before")
    @classmethod
    def tidy_tags(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        tags = []
        for raw in value:
            tag = "#" + "".join(str(raw).split()).lstrip("#")
            if 1 < len(tag) <= 60 and tag.lower() not in {t.lower() for t in tags}:
                tags.append(tag)
        if "#shorts" not in {t.lower() for t in tags}:
            tags.append("#Shorts")
        return tags[:10]


class Storyboard(BaseModel):
    beats: list[Beat] = Field(min_length=3, max_length=10)
    youtube: YoutubeMeta

    @model_validator(mode="after")
    def bounded_script(self) -> "Storyboard":
        spoken = sum(len(beat.say) for beat in self.beats)
        if spoken > 2400:
            raise ValueError(
                f"the narration is {spoken} characters; keep the whole video under about 55 seconds"
            )
        return self
