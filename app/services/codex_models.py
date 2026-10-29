"""Public Codex model catalog, following Jarvys' models.dev discovery rules."""

from dataclasses import dataclass, replace
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time

import requests

from app import paths

CATALOG_URL = "https://models.dev/api.json"
CACHE_TTL = 24 * 60 * 60
MAX_BYTES = 12 * 1024 * 1024
_lock = threading.Lock()
_cached = None
_retry_after = 0.0


@dataclass(frozen=True)
class Model:
    id: str
    name: str


@dataclass(frozen=True)
class Catalog:
    models: tuple[Model, ...]
    fetched_at: float
    stale: bool = False


class CatalogError(ValueError):
    pass


def _cache_path():
    return paths.runtime_root() / "storage" / "cache" / "codex_models.json"


def _compatible(model_id, item):
    """Protocol compatibility rules from Jarvys, not a fixed model menu."""
    options = item.get("options")
    if isinstance(options, dict) and options.get("reasoningMode") == "pro":
        return False
    if model_id in {"gpt-5.5-pro", "gpt-5.6"}:
        return False
    if model_id in {"gpt-5.5", "gpt-5.3-codex-spark", "gpt-5.4", "gpt-5.4-mini"}:
        return True
    match = re.match(r"^gpt-(\d+)(?:\.(\d+))?", model_id)
    if not match:
        return False
    return (int(match[1]), int(match[2] or 0)) > (5, 4)


def parse_catalog(payload):
    try:
        entries = payload["openai"]["models"]
        if not isinstance(entries, dict):
            raise TypeError()
    except (KeyError, TypeError):
        raise CatalogError("codex.models.failed") from None
    models = {}
    for key, item in entries.items():
        if not isinstance(item, dict):
            continue
        model_id = item.get("id", key)
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        model_id = model_id.strip()
        if not _compatible(model_id, item):
            continue
        modalities = item.get("modalities")
        if isinstance(modalities, dict):
            output = modalities.get("output")
            if not isinstance(output, list) or "text" not in output:
                continue
        name = item.get("name")
        models[model_id] = Model(
            model_id, name if isinstance(name, str) and name else model_id
        )
    if not models:
        raise CatalogError("codex.models.failed")
    return tuple(
        sorted(models.values(), key=lambda model: (model.name.casefold(), model.id))
    )


def _download():
    try:
        with requests.get(
            CATALOG_URL,
            headers={"Accept": "application/json", "User-Agent": "MoneyPrinterTurbo"},
            stream=True,
            timeout=(5, 10),
            allow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise CatalogError("codex.models.failed")
            chunks = []
            size = 0
            deadline = time.monotonic() + 30
            for chunk in response.iter_content(64 * 1024):
                size += len(chunk)
                if size > MAX_BYTES or time.monotonic() > deadline:
                    raise CatalogError("codex.models.failed")
                chunks.append(chunk)
            return parse_catalog(json.loads(b"".join(chunks)))
    except (requests.RequestException, ValueError):
        raise CatalogError("codex.models.failed") from None


def _read_cache():
    try:
        raw = _cache_path().read_bytes()
        if len(raw) > MAX_BYTES:
            return None
        payload = json.loads(raw)
        if payload["version"] != 1:
            return None
        fetched_at = float(payload["fetched_at"])
        if not math.isfinite(fetched_at) or not 0 < fetched_at <= time.time() + 60:
            return None
        # Reapply compatibility rules when restoring an older cache.
        models = parse_catalog({"openai": {"models": payload["models"]}})
        return Catalog(models, fetched_at)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_cache(catalog):
    destination = _cache_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "fetched_at": catalog.fetched_at,
        "models": {
            model.id: {"id": model.id, "name": model.name} for model in catalog.models
        },
    }
    fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix=".codex-models-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def get_catalog(force_refresh=False):
    """Keep the last valid catalog on outages; explicit refresh bypasses the TTL."""
    global _cached, _retry_after
    with _lock:
        if _cached is None:
            _cached = _read_cache()
        if not force_refresh:
            if _cached and time.time() - _cached.fetched_at < CACHE_TTL:
                return _cached
            if time.monotonic() < _retry_after:
                if _cached:
                    return replace(_cached, stale=True)
                raise CatalogError("codex.models.failed")
        try:
            models = _download()
        except CatalogError:
            _retry_after = time.monotonic() + 60
            if _cached:
                return replace(_cached, stale=True)
            raise
        _cached = Catalog(models, time.time())
        _retry_after = 0
        try:
            _write_cache(_cached)
        except OSError:
            # Discovery remains usable in memory even on a read-only disk.
            pass
        return _cached
