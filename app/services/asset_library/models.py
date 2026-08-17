from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

EMBEDDING_DIM = 768

ORIGIN_MANUAL = "manual"
ORIGIN_SEARCH = "search"


@dataclass
class AssetTag:
    tag: str
    weight: float = 1.0
    manual: bool = False


@dataclass
class Asset:
    id: int
    sha256: str
    rel_path: str
    width: int
    height: int
    caption: str = ""
    caption_manual: bool = False
    has_text: bool | None = None
    min_display: float | None = None
    min_display_manual: bool = False
    origin: str = ORIGIN_MANUAL
    source_query: str | None = None
    source_url: str | None = None
    embed_model: str | None = None
    annotate_model: str | None = None
    created_at: datetime | None = None
    last_used_at: datetime | None = None
    use_count: int = 0
    tags: list[AssetTag] = field(default_factory=list)
    # Only search_assets fills this in: cosine distance to the query vector.
    distance: float | None = None

    def tag_names(self) -> list[str]:
        return [tag.tag for tag in self.tags]


@dataclass
class IngestResult:
    asset: Asset
    created: bool


@dataclass
class LibrarySummary:
    total: int
    without_annotation: int
    without_embedding: int
    tags: dict[str, int]
