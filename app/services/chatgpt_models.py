"""Models available to the active ChatGPT account through the public API."""

from dataclasses import dataclass
import threading
import time

from app.services import chatgpt_oauth


@dataclass(frozen=True)
class Model:
    id: str
    name: str


@dataclass(frozen=True)
class Catalog:
    models: tuple[Model, ...]
    fetched_at: float


class CatalogError(ValueError):
    pass


_lock = threading.Lock()
_cached = None
_identity = None


def parse_catalog(payload):
    entries = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise CatalogError("chatgpt.models.failed")
    result = {}
    for item in entries:
        if not isinstance(item, dict) or item.get("visibility") != "list":
            continue
        slug, name = item.get("slug"), item.get("display_name")
        if isinstance(slug, str) and slug.strip():
            result[slug] = Model(slug, name if isinstance(name, str) and name else slug)
    return tuple(result.values())


def get_catalog(force_refresh=False):
    global _cached, _identity
    details = chatgpt_oauth.account_details()
    if not details["authorized"]:
        raise chatgpt_oauth.ChatGPTError(
            "plan_required" if details["connected"] else "not_connected"
        )
    identity = (details["active"], details["revision"])
    with _lock:
        if (
            not force_refresh
            and identity == _identity
            and _cached
            and time.time() - _cached.fetched_at < 60
        ):
            return _cached
        models = parse_catalog(chatgpt_oauth.get_models())
        current = chatgpt_oauth.account_details()
        if identity != (current["active"], current["revision"]):
            raise chatgpt_oauth.ChatGPTError("changed")
        _cached = Catalog(models, time.time())
        _identity = identity
        return _cached
