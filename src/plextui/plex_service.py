from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from plexapi.server import PlexServer

from .config import AppConfig, config_path
from .models import LibraryItem, MediaDetails, MediaItem


PLAYABLE_TYPES = {"movie", "episode", "track", "clip"}
DEFAULT_PAGE_SIZE = 100


@dataclass(frozen=True)
class MediaPage:
    items: list[MediaItem]
    start: int
    total: int

    @property
    def next_start(self) -> int:
        return self.start + len(self.items)

    @property
    def has_more(self) -> bool:
        return self.next_start < self.total


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

    def library_page(self, library: LibraryItem, start: int = 0, size: int = DEFAULT_PAGE_SIZE) -> MediaPage:
        raw_items = library.raw.all(maxresults=size, container_start=start, container_size=size)
        return media_page_from_raw(raw_items, start)

    def library_entry_page(
        self,
        library: LibraryItem,
        entry: str = "library",
        start: int = 0,
        size: int = DEFAULT_PAGE_SIZE,
    ) -> MediaPage:
        if entry == "library":
            return self.library_page(library, start, size)
        if entry == "recommended":
            raw_items = list(library.raw.hubs())
            return sliced_media_page(raw_items, start, size)
        if entry == "collections":
            raw_items = library.raw.collections(
                maxresults=size,
                container_start=start,
                container_size=size,
            )
            return media_page_from_raw(raw_items, start)
        if entry == "playlists":
            raw_items = library.raw.playlists(
                maxresults=size,
                container_start=start,
                container_size=size,
            )
            return media_page_from_raw(raw_items, start)
        raise ValueError(f"unknown library entry: {entry}")

    def library_items(self, library: LibraryItem) -> list[MediaItem]:
        return self.library_page(library, 0, DEFAULT_PAGE_SIZE).items

    def search_page(
        self,
        query: str,
        library: LibraryItem | None = None,
        start: int = 0,
        size: int = DEFAULT_PAGE_SIZE,
    ) -> MediaPage:
        if library is not None:
            raw_items = library.raw.search(
                query,
                maxresults=size,
                container_start=start,
                container_size=size,
            )
            return media_page_from_raw(raw_items, start)

        if start:
            return MediaPage(items=[], start=start, total=start)
        raw_items = self.server.search(query, limit=size)
        items = [to_media_item(item) for item in raw_items]
        return MediaPage(items=items, start=0, total=len(items))

    def continue_watching_page(self, start: int = 0, size: int = DEFAULT_PAGE_SIZE) -> MediaPage:
        raw_items = list(self.server.library.onDeck())
        items = [to_media_item(item) for item in raw_items[start:start + size]]
        return MediaPage(items=items, start=start, total=len(raw_items))

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
        if library is not None:
            return self.search_page(query, library, 0, DEFAULT_PAGE_SIZE).items
        source: Iterable[Any] = self.server.search(query, limit=DEFAULT_PAGE_SIZE)
        return [to_media_item(item) for item in source]


def media_page_from_raw(raw_items: Iterable[Any], start: int) -> MediaPage:
    items = [to_media_item(item) for item in raw_items]
    total = getattr(raw_items, "totalSize", None)
    if total is None:
        total = start + len(items)
    return MediaPage(items=items, start=start, total=int(total))


def sliced_media_page(raw_items: list[Any], start: int, size: int) -> MediaPage:
    items = [to_media_item(item) for item in raw_items[start:start + size]]
    return MediaPage(items=items, start=start, total=len(raw_items))


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
        artwork_path=artwork_path(raw),
    )


def media_details(item: MediaItem) -> MediaDetails:
    raw = item.raw
    facts = [item.kind]
    for value in (
        getattr(raw, "year", None),
        format_duration(getattr(raw, "duration", None)),
        watched_state(raw),
        episode_label(raw),
        subtitle_label(raw),
        getattr(raw, "contentRating", None),
        rating_label(raw),
    ):
        if value:
            facts.append(str(value))

    for label, value in (
        ("Show", getattr(raw, "grandparentTitle", None)),
        ("Season", getattr(raw, "parentTitle", None)),
        ("Studio", getattr(raw, "studio", None)),
    ):
        if value:
            facts.append(f"{label}: {value}")

    return MediaDetails(
        title=item.title,
        kind=item.kind,
        facts=facts,
        metadata=metadata_fields(raw),
        audio=audio_details(raw),
        subtitles=subtitle_details(raw),
        summary=str(getattr(raw, "summary", "") or ""),
        playable=item.playable,
        artwork_path=artwork_path(raw) or item.artwork_path,
    )


def artwork_path(raw: Any) -> str:
    for attr in ("grandparentThumb", "parentThumb", "thumb", "art"):
        value = getattr(raw, attr, None)
        if value:
            return str(value)
    return ""


def metadata_fields(raw: Any) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for label, value in (
        ("Type", getattr(raw, "TYPE", "")),
        ("Year", getattr(raw, "year", None)),
        ("Duration", format_duration(getattr(raw, "duration", None))),
        ("Status", watched_state(raw)),
        ("Progress", progress_label(raw)),
        ("Episode", episode_label(raw)),
        ("Content Rating", getattr(raw, "contentRating", None)),
        ("Rating", rating_label(raw).replace("Rating ", "")),
        ("Show", getattr(raw, "grandparentTitle", None)),
        ("Season", getattr(raw, "parentTitle", None)),
        ("Studio", getattr(raw, "studio", None)),
    ):
        if value:
            fields.append((label, str(value)))
    return fields


def audio_details(raw: Any) -> list[str]:
    audio: list[str] = []
    try:
        if not hasattr(raw, "iterParts"):
            return audio
        for part in raw.iterParts():
            for stream in part.audioStreams():
                audio.append(stream_detail_label(stream, include_location=False))
    except Exception:
        return audio
    return audio


def subtitle_details(raw: Any) -> list[str]:
    subtitles: list[str] = []
    try:
        if not hasattr(raw, "iterParts"):
            return subtitles
        for part in raw.iterParts():
            for stream in part.subtitleStreams():
                subtitles.append(stream_detail_label(stream, include_location=True))
    except Exception:
        return subtitles
    return subtitles


def stream_detail_label(stream: Any, include_location: bool = False) -> str:
    label = getattr(stream, "displayTitle", None) or getattr(stream, "language", None) or "Unknown"
    values = []
    codec = getattr(stream, "codec", None)
    if codec:
        values.append(str(codec))
    channels = getattr(stream, "channels", None)
    if channels:
        values.append(f"{channels}ch")
    if include_location:
        values.append("external" if getattr(stream, "key", None) else "embedded")
    if getattr(stream, "selected", False):
        values.append("selected")
    if getattr(stream, "forced", False):
        values.append("forced")
    if getattr(stream, "hearingImpaired", False):
        values.append("SDH")
    suffix = ", ".join(values)
    return f"{label} ({suffix})" if suffix else str(label)


def watched_state(raw: Any) -> str:
    view_count = getattr(raw, "viewCount", None)
    if view_count:
        return "watched"
    if resume_offset(raw):
        return "in progress"
    if hasattr(raw, "isWatched"):
        try:
            value = raw.isWatched() if callable(raw.isWatched) else raw.isWatched
            return "watched" if value else "unwatched"
        except Exception:
            return ""
    return ""


def progress_label(raw: Any) -> str:
    offset = resume_offset(raw)
    if not offset:
        return ""
    duration = duration_ms(raw)
    if duration:
        percent = min(99, max(1, round(offset / duration * 100)))
        return f"{format_position(offset)} / {format_position(duration)} ({percent}%)"
    return f"Resume at {format_position(offset)}"


def row_progress_marker(raw: Any) -> str:
    state = watched_state(raw)
    if state == "watched":
        return "[watched]"
    if state == "in progress":
        label = progress_label(raw)
        return f"[resume {format_position(resume_offset(raw))}]" if label else "[resume]"
    return ""


def resume_offset(raw: Any) -> int:
    try:
        return max(0, int(getattr(raw, "viewOffset", 0) or 0))
    except (TypeError, ValueError):
        return 0


def duration_ms(raw: Any) -> int:
    try:
        return max(0, int(getattr(raw, "duration", 0) or 0))
    except (TypeError, ValueError):
        return 0


def format_position(milliseconds: int) -> str:
    seconds = max(0, milliseconds // 1000)
    hours, remainder = divmod(seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def episode_label(raw: Any) -> str:
    season = getattr(raw, "parentIndex", None)
    episode = getattr(raw, "index", None)
    if season is not None and episode is not None and getattr(raw, "TYPE", "") == "episode":
        return f"S{int(season):02d}E{int(episode):02d}"
    if episode is not None and getattr(raw, "TYPE", "") == "season":
        return f"Season {episode}"
    return ""


def rating_label(raw: Any) -> str:
    rating = getattr(raw, "audienceRating", None) or getattr(raw, "rating", None)
    if rating is None:
        return ""
    try:
        return f"Rating {float(rating):.1f}"
    except (TypeError, ValueError):
        return f"Rating {rating}"


def subtitle_label(raw: Any) -> str:
    count = 0
    try:
        if hasattr(raw, "iterParts"):
            for part in raw.iterParts():
                count += len(part.subtitleStreams())
    except Exception:
        return ""
    if count == 1:
        return "1 subtitle"
    if count > 1:
        return f"{count} subtitles"
    return ""


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
