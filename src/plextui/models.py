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
