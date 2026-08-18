"""
Accumulating photo asset library: files on disk, metadata in Postgres + pgvector.

This package owns the SQL and the on-disk layout. Everything else (retrieval,
CLI, annotation, pipeline) goes through the functions re-exported here, so no
neighbour needs a database handle. Annotation and embedding are not produced
here — they are handed in ready by their owners.

The driver is imported lazily, so importing this package costs nothing while
`photo_library_enabled` is off.
"""

from app.services.asset_library.db import (
    asset_path,
    connect,
    connection_params,
    init_library,
    is_enabled,
    library_root,
)
from app.services.asset_library.ingest import (
    file_digest,
    ingest_directory,
    ingest_file,
)
from app.services.asset_library.models import (
    EMBEDDING_DIM,
    ORIGIN_MANUAL,
    ORIGIN_SEARCH,
    Asset,
    AssetTag,
    IngestResult,
    LibrarySummary,
)
from app.services.asset_library.store import (
    assets_missing_annotation,
    assets_missing_embedding,
    delete_asset,
    get_asset,
    list_assets,
    record_usage,
    save_annotation,
    save_embedding,
    search_assets,
    set_tags,
    summary,
    tagged_assets_without_embedding,
    usage_counts,
)

__all__ = [
    "EMBEDDING_DIM",
    "ORIGIN_MANUAL",
    "ORIGIN_SEARCH",
    "Asset",
    "AssetTag",
    "IngestResult",
    "LibrarySummary",
    "asset_path",
    "assets_missing_annotation",
    "assets_missing_embedding",
    "connect",
    "connection_params",
    "delete_asset",
    "file_digest",
    "get_asset",
    "ingest_directory",
    "ingest_file",
    "init_library",
    "is_enabled",
    "library_root",
    "list_assets",
    "record_usage",
    "save_annotation",
    "save_embedding",
    "search_assets",
    "set_tags",
    "summary",
    "tagged_assets_without_embedding",
    "usage_counts",
]
