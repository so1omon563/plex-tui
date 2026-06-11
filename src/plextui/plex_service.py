from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from plexapi.server import PlexServer

from .config import AppConfig, config_path
from .models import LibraryItem, MediaItem


PLAYABLE_TYPES = {"movie", "episode", "track", "clip"}


class PlexService:
    def __init__(self, config: AppConfig) -> None:
        if not config.base_url or not config.token:
            raise ValueError(
                "missing Plex config. Set PLEX_TUI_BASE_URL and PLEX_TUI_TOKEN, "
                f"or create {config_path()}"
            )
        self.server = PlexServer(config.base_url, config.token)

    @property
    def friendly_name(self) -> str:
        return getattr(self.server, "friendlyName", "Plex")

    def libraries(self) -> list[LibraryItem]:
        sections = self.server.library.sections()
        return [
            LibraryItem(
                title=section.title,
                key=str(section.key),
                kind=getattr(section, "TYPE", section.__class__.__name__),
                raw=section,
            )
            for section in sections
        ]

    def library_items(self, library: LibraryItem) -> list[MediaItem]:
        return [to_media_item(item) for item in library.raw.all()]

    def children(self, item: MediaItem) -> list[MediaItem]:
        raw = item.raw
        if hasattr(raw, "seasons"):
            return [to_media_item(child) for child in raw.seasons()]
        if hasattr(raw, "episodes"):
            return [to_media_item(child) for child in raw.episodes()]
        if hasattr(raw, "items"):
            return [to_media_item(child) for child in raw.items()]
        return []

    def search(self, query: str, library: LibraryItem | None = None) -> list[MediaItem]:
        source: Iterable[Any]
        if library is not None:
            source = library.raw.search(query)
        else:
            source = self.server.search(query)
        return [to_media_item(item) for item in source]


def to_media_item(raw: Any) -> MediaItem:
    kind = str(getattr(raw, "TYPE", raw.__class__.__name__)).lower()
    year = getattr(raw, "year", None)
    duration = format_duration(getattr(raw, "duration", None))
    bits = [str(year) if year else "", duration]
    subtitle = "  ".join(bit for bit in bits if bit)
    key = str(getattr(raw, "ratingKey", getattr(raw, "key", "")))
    return MediaItem(
        title=getattr(raw, "title", "Untitled"),
        subtitle=subtitle,
        kind=kind,
        key=key,
        playable=kind in PLAYABLE_TYPES and hasattr(raw, "getStreamURL"),
        raw=raw,
    )


def format_duration(milliseconds: Any) -> str:
    if not milliseconds:
        return ""
    try:
        minutes = int(milliseconds) // 60_000
    except (TypeError, ValueError):
        return ""
    hours, mins = divmod(minutes, 60)
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"
