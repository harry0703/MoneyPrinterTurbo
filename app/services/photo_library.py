"""
Group overlay photos into themes.

A photo directory is scouted per theme (see docs/playbook/media-scouting.md):
several queries, a pile of files each. Themes are what the LLM matches against
script lines — matching every single file would be both a huge prompt and a
choice the model cannot make from a file name.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from loguru import logger

PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
THEMES_MANIFEST = "themes.json"

_TOKEN_SPLIT = re.compile(r"[-_\s.]+")
_DEFAULT_THEME = "misc"


@dataclass
class PhotoTheme:
    name: str
    files: list[str] = field(default_factory=list)
    description: str = ""

    def samples(self, limit: int = 3) -> list[str]:
        return [os.path.basename(photo) for photo in self.files[:limit]]


def list_photo_files(photo_dir: str) -> list[str]:
    """Collect overlay photos, subdirectories included, sorted for determinism."""
    if not photo_dir or not os.path.isdir(photo_dir):
        return []
    found: list[str] = []
    for root, dirs, names in os.walk(photo_dir):
        dirs.sort()
        for name in sorted(names):
            if not name.lower().endswith(PHOTO_EXTENSIONS):
                continue
            full = os.path.join(root, name)
            if os.path.isfile(full):
                found.append(full)
    return found


def _theme_from_name(file_name: str) -> str:
    """`20-spider-01.jpg` -> `spider`: order prefixes are numbers, the theme is not."""
    stem = os.path.splitext(file_name)[0]
    for token in _TOKEN_SPLIT.split(stem):
        token = re.sub(r"[^0-9a-zA-Zа-яА-ЯёЁ]+", "", token).lower()
        if token and not token.isdigit():
            return token
    return _DEFAULT_THEME


def _theme_of(photo_dir: str, photo_path: str) -> str:
    relative = os.path.relpath(photo_path, photo_dir)
    parent = os.path.dirname(relative)
    if parent:
        return parent.replace(os.sep, "/").lower()
    return _theme_from_name(os.path.basename(photo_path))


def _load_descriptions(photo_dir: str) -> dict[str, str]:
    manifest = os.path.join(photo_dir, THEMES_MANIFEST)
    if not os.path.isfile(manifest):
        return {}
    try:
        with open(manifest, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
    except Exception as error:
        logger.warning(f"failed to read {manifest}: {str(error)}")
        return {}
    if not isinstance(parsed, dict):
        logger.warning(f"{manifest} must be an object of theme -> description")
        return {}
    return {
        str(key).strip().lower(): str(value).strip()
        for key, value in parsed.items()
        if str(value).strip()
    }


def discover_photo_themes(photo_dir: str) -> list[PhotoTheme]:
    """Split a photo directory into themes, keeping file order inside each one."""
    photos = list_photo_files(photo_dir)
    if not photos:
        return []

    descriptions = _load_descriptions(photo_dir)
    grouped: dict[str, PhotoTheme] = {}
    for photo in photos:
        name = _theme_of(photo_dir, photo)
        theme = grouped.get(name)
        if theme is None:
            theme = PhotoTheme(name=name, description=descriptions.get(name, ""))
            grouped[name] = theme
        theme.files.append(photo)
    return list(grouped.values())


class ThemedPhotoPicker:
    """Hand out photos of a requested theme, moving through the pool in order."""

    def __init__(self, themes: list[PhotoTheme]) -> None:
        self._pools = {theme.name: list(theme.files) for theme in themes if theme.files}
        self._cursors = {name: 0 for name in self._pools}

    def take(self, theme_name: str) -> str | None:
        name = str(theme_name).strip().lower()
        pool = self._pools.get(name)
        if not pool:
            return None
        cursor = self._cursors[name]
        self._cursors[name] = cursor + 1
        # Wrapping repeats a photo of the right theme instead of showing a
        # wrong one, which is the lesser evil for a themed insert.
        return pool[cursor % len(pool)]
