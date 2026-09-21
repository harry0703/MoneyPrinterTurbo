"""Creative production pipeline data models.

Used only by the flag-gated creative pipeline (``VideoParams.creative_mode``).
The vanilla MoneyPrinterTurbo flow never touches these models.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Where the visual asset of a shot comes from.
SHOT_SOURCE_STOCK = "stock"
SHOT_SOURCE_LOCAL = "local"
SHOT_SOURCE_GENERATED_IMAGE = "generated_image"
SHOT_SOURCE_GENERATED_VIDEO = "generated_video"
SHOT_SOURCE_GRAPHIC = "graphic"
SHOT_SOURCE_ARCHIVE = "archive"

SHOT_SOURCE_TYPES = (
    SHOT_SOURCE_STOCK,
    SHOT_SOURCE_LOCAL,
    SHOT_SOURCE_GENERATED_IMAGE,
    SHOT_SOURCE_GENERATED_VIDEO,
    SHOT_SOURCE_GRAPHIC,
    SHOT_SOURCE_ARCHIVE,
)

# Shots that must carry a visual generation prompt.
SHOT_SOURCE_GENERATED = (
    SHOT_SOURCE_GENERATED_IMAGE,
    SHOT_SOURCE_GENERATED_VIDEO,
)

# Shots that must carry a material search query.
SHOT_SOURCE_SEARCHABLE = (
    SHOT_SOURCE_STOCK,
    SHOT_SOURCE_LOCAL,
)

# Shot lifecycle states, tracked per shot in shot_plan.json.
SHOT_STATUS_PLANNED = "planned"
SHOT_STATUS_RESOLVED = "resolved"
SHOT_STATUS_FAILED = "failed"

SHOT_STATUSES = (
    SHOT_STATUS_PLANNED,
    SHOT_STATUS_RESOLVED,
    SHOT_STATUS_FAILED,
)


class CreativeBrief(BaseModel):
    """High-level creative intent for one video."""

    topic: str
    audience: Optional[str] = None
    objective: Optional[str] = None
    thesis: Optional[str] = None
    tone: Optional[str] = None
    visual_language: Optional[str] = None
    references: list[str] = Field(default_factory=list)
    forbidden_elements: list[str] = Field(default_factory=list)
    notes: Optional[str] = None


class StyleProfile(BaseModel):
    """Reusable visual identity constraints applied to every shot."""

    name: str
    visual_style: Optional[str] = None
    palette: list[str] = Field(default_factory=list)
    camera_language: Optional[str] = None
    motion_language: Optional[str] = None
    character_rules: list[str] = Field(default_factory=list)
    negative_rules: list[str] = Field(default_factory=list)
    reference_images: list[str] = Field(default_factory=list)


class ShotPlanItem(BaseModel):
    """One shot of the planned video, in script order."""

    index: int = Field(ge=1)
    script_segment: str = ""
    duration: Optional[float] = Field(default=None, gt=0)

    source_type: str
    query: Optional[str] = None
    prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    provider: Optional[str] = None
    reference_images: list[str] = Field(default_factory=list)
    camera: Optional[str] = None
    framing: Optional[str] = None
    motion: Optional[str] = None
    asset_path: Optional[str] = None
    status: str = SHOT_STATUS_PLANNED

    @field_validator("source_type")
    @classmethod
    def _validate_source_type(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in SHOT_SOURCE_TYPES:
            raise ValueError(
                f"source_type must be one of {', '.join(SHOT_SOURCE_TYPES)}"
            )
        return normalized

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in SHOT_STATUSES:
            raise ValueError(f"status must be one of {', '.join(SHOT_STATUSES)}")
        return normalized


class ShotPlan(BaseModel):
    """Ordered shot plan for one task; persisted as shot_plan.json."""

    version: int = 1
    task_id: str
    shots: list[ShotPlanItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_shot_indices(self) -> "ShotPlan":
        indices = [shot.index for shot in self.shots]
        if indices != list(range(1, len(indices) + 1)):
            raise ValueError(
                f"shot indices must be sequential starting at 1, got {indices}"
            )
        return self


def validate_shot_plan(plan: ShotPlan) -> list[str]:
    """
    Semantic checks beyond Pydantic validation.

    The planner must guarantee that searchable shots carry a search query and
    generated shots carry a generation prompt; callers treat a non-empty
    result as a failed planning attempt.
    """
    issues: list[str] = []
    if not plan.shots:
        return ["shot plan contains no shots"]

    for shot in plan.shots:
        if shot.source_type in SHOT_SOURCE_SEARCHABLE and not (
            shot.query or ""
        ).strip():
            issues.append(
                f"shot {shot.index}: {shot.source_type} shot is missing a "
                "search query"
            )
        if shot.source_type in SHOT_SOURCE_GENERATED and not (
            shot.prompt or ""
        ).strip():
            issues.append(
                f"shot {shot.index}: {shot.source_type} shot is missing a "
                "generation prompt"
            )
    return issues
