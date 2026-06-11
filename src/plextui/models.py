from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LibraryItem:
    title: str
    key: str
    kind: str
    raw: Any


@dataclass(frozen=True)
class MediaItem:
    title: str
    subtitle: str
    kind: str
    key: str
    playable: bool
    raw: Any
    artwork_path: str = ""


@dataclass(frozen=True)
class MediaDetails:
    title: str
    kind: str
    facts: list[str]
    metadata: list[tuple[str, str]]
    audio: list[str]
    subtitles: list[str]
    summary: str
    playable: bool
    artwork_path: str = ""
