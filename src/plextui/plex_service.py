from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from plexapi.server import PlexServer

from .config import AppConfig, config_path
from .models import LibraryItem, MediaDetails, MediaItem


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
        subtitles=subtitle_details(raw),
        summary=str(getattr(raw, "summary", "") or ""),
        playable=item.playable,
    )


def metadata_fields(raw: Any) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for label, value in (
        ("Type", getattr(raw, "TYPE", "")),
        ("Year", getattr(raw, "year", None)),
        ("Duration", format_duration(getattr(raw, "duration", None))),
        ("Status", watched_state(raw)),
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


def subtitle_details(raw: Any) -> list[str]:
    subtitles: list[str] = []
    try:
        if not hasattr(raw, "iterParts"):
            return subtitles
        for part in raw.iterParts():
            for stream in part.subtitleStreams():
                label = getattr(stream, "displayTitle", None) or getattr(stream, "language", None) or "Unknown"
                codec = getattr(stream, "codec", None)
                flags = []
                if getattr(stream, "selected", False):
                    flags.append("selected")
                if getattr(stream, "forced", False):
                    flags.append("forced")
                if getattr(stream, "hearingImpaired", False):
                    flags.append("SDH")
                values = [str(codec)] if codec else []
                values.extend(flags)
                extra = ", ".join(values)
                subtitles.append(f"{label} ({extra})" if extra else str(label))
    except Exception:
        return subtitles
    return subtitles


def watched_state(raw: Any) -> str:
    view_count = getattr(raw, "viewCount", None)
    if view_count:
        return "watched"
    if hasattr(raw, "isWatched"):
        try:
            value = raw.isWatched() if callable(raw.isWatched) else raw.isWatched
            return "watched" if value else "unwatched"
        except Exception:
            return ""
    return ""


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
