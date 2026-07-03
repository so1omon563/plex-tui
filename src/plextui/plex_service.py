from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
import json
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from typing import Any

from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer

from .config import AppConfig, config_path
from .models import LibraryItem, MediaDetails, MediaItem


PLAYABLE_TYPES = {"movie", "episode", "track", "clip", "livetv"}
DEFAULT_PAGE_SIZE = 100
DISCOVER_PROVIDERS = "discover,PLEXAVOD"
EPG_PROVIDER_BASE = "https://epg.provider.plex.tv"

KIND_LABELS: dict[str, str] = {
    "movie": "Movie",
    "show": "TV Show",
    "season": "Season",
    "episode": "Episode",
    "track": "Track",
    "album": "Album",
    "artist": "Artist",
    "collection": "Collection",
    "playlist": "Playlist",
    "clip": "Clip",
    "livetv": "Live TV Channel",
    "livetv_program": "Live TV Program",
    "photoalbum": "Photo Album",
}


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind.capitalize())


def rating_compact(raw: Any) -> str:
    rating = getattr(raw, "audienceRating", None) or getattr(raw, "rating", None)
    if rating is None:
        return ""
    try:
        return f"Rating {float(rating):.1f}"
    except (TypeError, ValueError):
        return f"Rating {rating}"


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


@dataclass(frozen=True)
class CategoryRef:
    title: str
    key: str
    library: LibraryItem
    raw: Any
    filter_name: str = "genre"
    filter_value: str = ""


@dataclass(frozen=True)
class HostedLiveTVChannel:
    title: str
    key: str
    stream_url: str
    grid_key: str = ""
    drm: bool = False
    call_sign: str = ""
    language: str = ""
    is_hd: bool = False
    protocol: str = ""
    container: str = ""
    thumb: str = ""
    art: str = ""
    summary: str = ""
    current_program: HostedLiveTVGuideProgram | None = None
    next_program: HostedLiveTVGuideProgram | None = None
    guide_status: str = ""

    TYPE = "livetv"

    @property
    def playable(self) -> bool:
        return bool(self.stream_url and not self.drm)

    @property
    def subtitle(self) -> str:
        return "  ".join(
            bit
            for bit in (
                self.call_sign,
                "HD" if self.is_hd else "",
                self.protocol.upper() if self.protocol else "",
            )
            if bit
        )

    def getStreamURL(self, **kwargs: Any) -> str:
        if self.drm:
            raise RuntimeError("Plex Live TV channel is DRM-protected")
        if not self.stream_url:
            raise RuntimeError("Plex Live TV channel does not provide a stream URL")
        return self.stream_url


@dataclass(frozen=True)
class HostedLiveTVGuideProgram:
    title: str
    key: str
    begins_at: int = 0
    ends_at: int = 0
    duration: int = 0
    on_air: bool = False
    video_resolution: str = ""
    summary: str = ""
    thumb: str = ""
    art: str = ""
    year: int | None = None

    TYPE = "livetv_program"


class PlexService:
    def __init__(self, config: AppConfig) -> None:
        if not config.base_url or not config.token:
            raise ValueError(
                "missing Plex config. Set PLEX_TUI_BASE_URL and PLEX_TUI_TOKEN, "
                f"or create {config_path()}"
            )
        self.config = config
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
            return sliced_media_page([to_hub_media_item(item) for item in raw_items], start, size)
        if entry == "recently_added":
            raw_items = library.raw.search(
                sort="addedAt:desc",
                maxresults=size,
                container_start=start,
                container_size=size,
            )
            return media_page_from_raw(raw_items, start)
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
        if entry == "categories":
            return sliced_media_page(category_items(library), start, size)
        raise ValueError(f"unknown library entry: {entry}")

    def playlists(self) -> list[MediaItem]:
        return [to_media_item(item) for item in self.server.playlists()]

    def create_playlist_from_items(self, title: str, items: list[MediaItem]) -> MediaItem:
        playlist = self.server.createPlaylist(title, items=[item.raw for item in items])
        return to_media_item(playlist)

    def add_items_to_playlist(self, playlist: MediaItem, items: list[MediaItem]) -> MediaItem:
        result = playlist.raw.addItems([item.raw for item in items])
        return to_media_item(result or playlist.raw)

    def remove_items_from_playlist(self, playlist: MediaItem, items: list[MediaItem]) -> MediaItem:
        result = playlist.raw.removeItems([item.raw for item in items])
        return to_media_item(result or playlist.raw)

    def rename_playlist(self, playlist: MediaItem, title: str) -> MediaItem:
        edit = getattr(playlist.raw, "_edit", None)
        if not callable(edit):
            raise AttributeError("playlist does not support rename")
        result = edit(title=title)
        return to_media_item(result or playlist.raw)

    def delete_playlist(self, playlist: MediaItem) -> None:
        delete = getattr(playlist.raw, "delete", None)
        if not callable(delete):
            raise AttributeError("playlist does not support delete")
        delete()

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

    def discover_page(
        self,
        query: str,
        start: int = 0,
        size: int = DEFAULT_PAGE_SIZE,
        media_type: str = "movies_shows",
    ) -> MediaPage:
        if not self.config.account_token:
            raise ValueError("missing Plex account token; start plex-tui and sign in first")
        account = MyPlexAccount(token=self.config.account_token)
        limit = start + size if media_type == "all" else (start + size) * 4
        raw_items = account.searchDiscover(query, limit=limit, providers=DISCOVER_PROVIDERS)
        items = [
            item
            for item in (to_discover_media_item(raw) for raw in raw_items)
            if discover_media_type_matches(item, media_type)
        ]
        matching_items = [item for item in items if discover_title_matches(query, item)]
        if matching_items:
            items = matching_items
        return sliced_media_page(items, start, size)

    def video_on_demand_page(self, start: int = 0, size: int = DEFAULT_PAGE_SIZE) -> MediaPage:
        if not self.config.account_token:
            raise ValueError("missing Plex account token; start plex-tui and sign in first")
        account = MyPlexAccount(token=self.config.account_token)
        hubs = [to_hub_media_item(raw) for raw in account.videoOnDemand()]
        return sliced_media_page(hubs, start, size)

    def hosted_live_tv_page(self, start: int = 0, size: int = DEFAULT_PAGE_SIZE) -> MediaPage:
        if not self.config.account_token:
            raise ValueError("missing Plex account token; start plex-tui and sign in first")
        data = epg_provider_json("/lineups/plex/channels", self.config.account_token)
        container = data.get("MediaContainer", {})
        channels = [
            channel
            for channel in (
                hosted_live_tv_channel_from_raw(raw, self.config.account_token)
                for raw in container.get("Channel", [])
            )
            if channel is not None
        ]
        return sliced_media_page([to_media_item(channel) for channel in channels], start, size)

    def hosted_live_tv_guide_page(
        self,
        channel: MediaItem,
        guide_date: date | None = None,
        start: int = 0,
        size: int = DEFAULT_PAGE_SIZE,
    ) -> MediaPage:
        if not self.config.account_token:
            raise ValueError("missing Plex account token; start plex-tui and sign in first")
        raw = channel.raw
        grid_key = getattr(raw, "grid_key", "") if isinstance(raw, HostedLiveTVChannel) else ""
        if not grid_key:
            raise ValueError("Live TV channel does not include a guide key")
        query = urlencode({"channelGridKey": grid_key, "date": (guide_date or hosted_live_tv_guide_date()).isoformat()})
        data = epg_provider_json(f"/grid?{query}", self.config.account_token)
        container = data.get("MediaContainer", {})
        programs = [
            program
            for program in (hosted_live_tv_program_from_raw(raw) for raw in container.get("Metadata", []))
            if program is not None
        ]
        programs.sort(key=hosted_live_tv_program_sort_key)
        return sliced_media_page([to_media_item(program) for program in programs], start, size)

    def enrich_hosted_live_tv_channels(self, items: list[MediaItem]) -> list[MediaItem]:
        return [self.enrich_hosted_live_tv_channel(item) for item in items]

    def enrich_hosted_live_tv_channel(self, item: MediaItem) -> MediaItem:
        raw = item.raw
        if not isinstance(raw, HostedLiveTVChannel) or not raw.grid_key:
            return item
        try:
            current, next_program = self.hosted_live_tv_now_next(raw)
        except Exception:
            return item
        if current is None and next_program is None:
            return item
        return to_media_item(replace(raw, current_program=current, next_program=next_program))

    def hosted_live_tv_now_next(
        self,
        channel: HostedLiveTVChannel,
        guide_date: date | None = None,
    ) -> tuple[HostedLiveTVGuideProgram | None, HostedLiveTVGuideProgram | None]:
        query = urlencode({"channelGridKey": channel.grid_key, "date": (guide_date or hosted_live_tv_guide_date()).isoformat()})
        data = epg_provider_json(f"/grid?{query}", self.config.account_token)
        container = data.get("MediaContainer", {})
        programs = [
            program
            for program in (hosted_live_tv_program_from_raw(raw) for raw in container.get("Metadata", []))
            if program is not None
        ]
        programs.sort(key=hosted_live_tv_program_sort_key)
        current = next((program for program in programs if program.on_air), None)
        after_ms = current.ends_at if current is not None and current.ends_at else int(time.time() * 1000)
        next_program = next(
            (program for program in programs if program is not current and program.begins_at >= after_ms),
            None,
        )
        return current, next_program

    def continue_watching_page(self, start: int = 0, size: int = DEFAULT_PAGE_SIZE) -> MediaPage:
        hubs = getattr(self.server.library, "hubs", None)
        hub_items: list[Any] = []
        if callable(hubs):
            try:
                hub_items = [
                    to_continue_watching_media(item)
                    for hub in hubs(identifier="home.continue")
                    for item in hub.items()
                ]
            except Exception:
                hub_items = []
        continue_watching = getattr(self.server, "continueWatching", None)
        raw_items: list[Any] = []
        if callable(continue_watching):
            try:
                raw_items = [
                    to_continue_watching_media(item)
                    for item in continue_watching()
                ]
            except Exception:
                pass
        raw_items.extend(hub_items)
        if not raw_items:
            raw_items = [to_continue_watching_media(item) for item in self.server.library.onDeck()]
        raw_items = [self.resolve_continue_watching_media(item) for item in raw_items]
        raw_items = dedupe_media_items(raw_items)
        items = [to_media_item(item) for item in raw_items[start : start + size]]
        return MediaPage(items=items, start=start, total=len(raw_items))

    def resolve_continue_watching_media(self, raw: Any) -> Any:
        media = to_continue_watching_media(raw)
        if callable(getattr(media, "getStreamURL", None)):
            return media
        media = self._fetch_continue_watching_media(media)
        if callable(getattr(media, "getStreamURL", None)):
            return media
        return to_continue_watching_media(media)

    def _fetch_continue_watching_media(self, raw: Any) -> Any:
        for key in (getattr(raw, "ratingKey", None), getattr(raw, "key", None), getattr(raw, "guid", None)):
            if not key:
                continue
            try:
                resolved = self.media_from_key(str(key))
            except Exception:
                resolved = None
            if resolved is not None:
                return to_continue_watching_media(resolved)
        return raw

    def media_from_key(self, key: str) -> Any | None:
        fetch_item = getattr(self.server, "fetchItem", None)
        if not callable(fetch_item):
            return None
        fetch_key = int(key) if key.isdigit() else key
        try:
            return fetch_item(fetch_key)
        except Exception:
            return None

    def episode_parent(self, item: MediaItem) -> MediaItem | None:
        if item.kind != "episode":
            return None
        key = episode_parent_key(item.raw)
        if not key:
            return None
        raw = self.media_from_key(key)
        return to_media_item(raw) if raw is not None else None

    def episode_show(self, item: MediaItem) -> MediaItem | None:
        if item.kind != "episode":
            return None
        key = episode_show_parent_key(item.raw)
        if not key:
            return None
        raw = self.media_from_key(key)
        return to_media_item(raw) if raw is not None else None

    def children(self, item: MediaItem, size: int = DEFAULT_PAGE_SIZE) -> list[MediaItem]:
        raw = item.raw
        if isinstance(raw, CategoryRef):
            return self.category_page(raw, 0, DEFAULT_PAGE_SIZE).items
        if item.playable and is_online_metadata(raw):
            return []
        editions = movie_edition_items(raw)
        if len(editions) > 1:
            return editions
        if is_online_metadata(raw):
            return online_metadata_children(raw, size)
        if hasattr(raw, "seasons"):
            try:
                return [to_media_item(child) for child in raw.seasons()]
            except Exception:
                if is_online_metadata(raw):
                    return []
                raise
        if hasattr(raw, "episodes"):
            try:
                return [to_media_item(child) for child in raw.episodes()]
            except Exception:
                if is_online_metadata(raw):
                    return []
                raise
        if hasattr(raw, "items"):
            return [to_media_item(child) for child in hub_items(raw, size=size)]
        return []

    def category_page(self, category: CategoryRef, start: int = 0, size: int = DEFAULT_PAGE_SIZE) -> MediaPage:
        raw = category.raw
        category_children = getattr(raw, "items", None)
        if callable(category_children):
            return sliced_media_page([to_media_item(item) for item in category_children()], start, size)
        if category_children:
            return sliced_media_page([to_media_item(item) for item in category_children], start, size)
        filters = {category.filter_name: category.filter_value or category.title}
        raw_items = category.library.raw.search(
            maxresults=size,
            container_start=start,
            container_size=size,
            **filters,
        )
        return media_page_from_raw(raw_items, start)


def media_page_from_raw(raw_items: Iterable[Any], start: int) -> MediaPage:
    items = [to_media_item(item) for item in raw_items]
    total = getattr(raw_items, "totalSize", None)
    if total is None:
        total = start + len(items)
    return MediaPage(items=items, start=start, total=int(total))


def sliced_media_page(raw_items: list[Any], start: int, size: int) -> MediaPage:
    items = [item if isinstance(item, MediaItem) else to_media_item(item) for item in raw_items[start:start + size]]
    return MediaPage(items=items, start=start, total=len(raw_items))


def hub_items(raw: Any, size: int = DEFAULT_PAGE_SIZE) -> list[Any]:
    key = str(getattr(raw, "key", "") or "")
    server = getattr(raw, "_server", None)
    vod_base = str(getattr(server, "VOD", "") or "")
    fetch_items = getattr(raw, "fetchItems", None)
    if key.startswith("/") and vod_base and callable(fetch_items):
        items = list(fetch_items(f"{vod_base.rstrip('/')}{key}", maxresults=size))[:size]
        to_online_metadata = getattr(server, "_toOnlineMetadata", None)
        return list(to_online_metadata(items)) if callable(to_online_metadata) else items
    return list(raw.items())


def to_continue_watching_media(raw: Any) -> Any:
    current = raw
    seen: set[int] = {id(current)}
    while True:
        if getattr(current, "TYPE", None) is not None or callable(getattr(current, "getStreamURL", None)):
            return current
        next_raw = (
            getattr(current, "metadata", None)
            or getattr(current, "item", None)
            or getattr(current, "metadataItem", None)
            or getattr(current, "child", None)
            or getattr(current, "mediaItem", None)
            or getattr(current, "media", None)
        )
        if next_raw is None or next_raw is current:
            return current
        if isinstance(next_raw, list):
            if len(next_raw) != 1:
                return current
            next_raw = next_raw[0]
        next_id = id(next_raw)
        if next_id in seen:
            return current
        seen.add(next_id)
        current = next_raw


def dedupe_media_items(raw_items: list[Any]) -> list[Any]:
    unique: list[Any] = []
    seen = set[str]()
    for raw in raw_items:
        key = dedupe_media_key(raw)
        if key not in seen:
            seen.add(key)
            unique.append(raw)
    return unique


def dedupe_media_key(raw: Any) -> str:
    for attr in ("guid", "ratingKey", "key"):
        value = getattr(raw, attr, None)
        if value is None or value == "" or value != value:
            continue
        return str(value)
    return f"unkeyed:{id(raw)}"


def to_media_item(raw: Any) -> MediaItem:
    if isinstance(raw, HostedLiveTVChannel):
        return MediaItem(
            title=raw.title or "Untitled Channel",
            subtitle=raw.subtitle,
            kind=raw.TYPE,
            key=raw.key,
            playable=raw.playable,
            raw=raw,
            artwork_path=raw.thumb or raw.art,
        )
    if isinstance(raw, HostedLiveTVGuideProgram):
        return MediaItem(
            title=raw.title or "Untitled Program",
            subtitle=hosted_live_tv_program_subtitle(raw),
            kind=raw.TYPE,
            key=raw.key,
            playable=False,
            raw=raw,
            artwork_path=raw.thumb or raw.art,
        )
    if isinstance(raw, CategoryRef):
        return MediaItem(
            title=raw.title,
            subtitle="Category",
            kind="category",
            key=raw.key,
            playable=False,
            raw=raw,
        )
    kind = str(getattr(raw, "TYPE", raw.__class__.__name__)).lower()
    year = getattr(raw, "year", None)
    duration = format_duration(getattr(raw, "duration", None))
    edition = edition_label(raw)
    context = episode_context_label(raw) if kind == "episode" else ""
    bits = [context, str(year) if year else "", edition, duration]
    subtitle = "  ".join(bit for bit in bits if bit)
    key = media_key(raw)
    title = getattr(raw, "title", "Untitled") or "Untitled"
    return MediaItem(
        title=str(title),
        subtitle=subtitle,
        kind=kind,
        key=key,
        playable=kind in PLAYABLE_TYPES and hasattr(raw, "getStreamURL"),
        raw=raw,
        artwork_path=artwork_path(raw),
    )


def to_hub_media_item(raw: Any) -> MediaItem:
    item = to_media_item(raw)
    if item.kind == "hub":
        return item
    return replace(item, kind="hub", playable=False)


def epg_provider_json(path: str, account_token: str) -> dict[str, Any]:
    request = Request(
        f"{EPG_PROVIDER_BASE}{path}",
        headers={
            "Accept": "application/json",
            "X-Plex-Token": account_token,
        },
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def hosted_live_tv_channel_from_raw(raw: dict[str, Any], account_token: str) -> HostedLiveTVChannel | None:
    media = first_mapping(raw.get("Media"))
    part = first_mapping(media.get("Part") if media else None)
    stream_url = signed_epg_url(str(part.get("key", "") or part.get("url", "") or ""), account_token) if part else ""
    key = str(raw.get("id") or raw.get("key") or raw.get("gridKey") or stream_url)
    if not key:
        return None
    drm = bool(raw.get("drm") or (media and media.get("drm")) or (part and part.get("drm")))
    return HostedLiveTVChannel(
        title=str(raw.get("title") or raw.get("callSign") or "Untitled Channel"),
        key=key,
        grid_key=str(raw.get("gridKey") or key),
        stream_url=stream_url,
        drm=drm,
        call_sign=str(raw.get("callSign") or ""),
        language=str(raw.get("language") or ""),
        is_hd=bool(raw.get("isHd")),
        protocol=str((media.get("protocol") if media else "") or ""),
        container=str((media.get("container") if media else "") or (part.get("container") if part else "") or ""),
        thumb=str(raw.get("thumb") or raw.get("coverPoster") or ""),
        art=str(raw.get("art") or ""),
        summary=str(raw.get("summary") or ""),
    )


def hosted_live_tv_program_from_raw(raw: dict[str, Any]) -> HostedLiveTVGuideProgram | None:
    media = first_mapping(raw.get("Media")) or {}
    key = str(raw.get("ratingKey") or raw.get("key") or raw.get("guid") or "")
    if not key:
        return None
    begins_at = parse_timestamp_ms(media.get("beginsAt"))
    ends_at = parse_timestamp_ms(media.get("endsAt"))
    return HostedLiveTVGuideProgram(
        title=str(raw.get("title") or "Untitled Program"),
        key=key,
        begins_at=begins_at,
        ends_at=ends_at,
        duration=parse_int(media.get("duration")),
        on_air=hosted_live_tv_program_on_air(media.get("onAir"), begins_at, ends_at),
        video_resolution=str(media.get("videoResolution") or ""),
        summary=str(raw.get("summary") or ""),
        thumb=hosted_live_tv_program_image(raw),
        art=str(raw.get("art") or ""),
        year=parse_optional_int(raw.get("year")),
    )


def hosted_live_tv_program_on_air(flag: Any, begins_at: int, ends_at: int, now_ms: int | None = None) -> bool:
    if begins_at and ends_at:
        current = now_ms if now_ms is not None else int(time.time() * 1000)
        return begins_at <= current < ends_at
    return bool(flag)


def hosted_live_tv_guide_date() -> date:
    return datetime.now(timezone.utc).date()


def hosted_live_tv_program_image(raw: dict[str, Any]) -> str:
    for image in raw.get("Image", []):
        if isinstance(image, dict) and image.get("url"):
            return str(image["url"])
    return str(raw.get("thumb") or "")


def hosted_live_tv_program_subtitle(program: HostedLiveTVGuideProgram) -> str:
    bits = [hosted_live_tv_time_range(program), "On now" if program.on_air else "", program.video_resolution.upper()]
    return "  ".join(bit for bit in bits if bit)


def hosted_live_tv_program_sort_key(program: HostedLiveTVGuideProgram) -> tuple[int, str]:
    return (program.begins_at or program.ends_at, program.key)


def hosted_live_tv_time_range(program: HostedLiveTVGuideProgram) -> str:
    if program.begins_at and program.ends_at:
        return f"{format_timestamp_time(program.begins_at)}-{format_timestamp_time(program.ends_at)}"
    if program.begins_at:
        return format_timestamp_time(program.begins_at)
    return format_duration(program.duration)


def format_timestamp_time(milliseconds: int) -> str:
    return datetime.fromtimestamp(milliseconds / 1000).strftime("%-I:%M %p")


def first_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    if isinstance(value, dict):
        return value
    return None


def signed_epg_url(value: str, account_token: str) -> str:
    if not value:
        return ""
    url = value if value.startswith(("http://", "https://")) else f"{EPG_PROVIDER_BASE}{value}"
    parts = urlsplit(url)
    query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True) if key.lower() != "x-plex-token"]
    query.append(("X-Plex-Token", account_token))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def media_key(raw: Any) -> str:
    for attr in ("ratingKey", "key", "guid"):
        value = getattr(raw, attr, None)
        if value is None or value == "" or value != value:
            continue
        return str(value)
    return f"unkeyed:{id(raw)}"


def episode_parent_key(raw: Any) -> str:
    if getattr(raw, "TYPE", "") != "episode":
        return ""
    for attr in ("parentKey", "parentRatingKey"):
        value = getattr(raw, attr, None)
        if value:
            return str(value)
    return ""


def episode_show_parent_key(raw: Any) -> str:
    if getattr(raw, "TYPE", "") != "episode":
        return ""
    for attr in ("grandparentKey", "grandparentRatingKey"):
        value = getattr(raw, attr, None)
        if value:
            return str(value)
    return ""


def to_discover_media_item(raw: Any) -> MediaItem:
    item = to_media_item(raw)
    subtitle = "  ".join(bit for bit in (item.subtitle, availability_label(raw)) if bit)
    return replace(item, subtitle=subtitle, playable=False)


def discover_media_type_matches(item: MediaItem, media_type: str) -> bool:
    if media_type == "all":
        return True
    if media_type == "movies_shows":
        return item.kind in {"movie", "show"}
    return item.kind == media_type


def discover_title_matches(query: str, item: MediaItem) -> bool:
    query_tokens = [token for token in title_tokens(query) if token not in {"a", "an", "and", "of", "the", "to"}]
    if not query_tokens:
        return False
    title = set(title_tokens(item.title))
    return all(token in title for token in query_tokens)


def title_tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.lower())


def availability_label(raw: Any) -> str:
    services = availability_services(raw)
    labels = []
    for service in services[:3]:
        label = provider_label(service)
        if label:
            labels.append(label)
    if not labels:
        return "No availability"
    extra = len(services) - len(labels)
    suffix = f" +{extra} more" if extra > 0 else ""
    provider_count = f"{len(services)} provider" if len(services) == 1 else f"{len(services)} providers"
    return f"{provider_count}: " + ", ".join(labels) + suffix


def availability_urls(raw: Any) -> list[tuple[str, str]]:
    urls = []
    for service in availability_services(raw):
        url = str(getattr(service, "url", "") or "")
        if url:
            urls.append((provider_label(service) or "Provider", url))
    return urls


def availability_services(raw: Any) -> list[Any]:
    streaming_services = getattr(raw, "streamingServices", None)
    if not callable(streaming_services):
        return []
    try:
        return list(streaming_services())
    except Exception:
        return []


def provider_label(service: Any) -> str:
    title = str(getattr(service, "title", "") or getattr(service, "platform", "") or "Provider")
    offer = offer_label(str(getattr(service, "offerType", "") or ""))
    return f"{title} · {offer}" if offer else title


def offer_label(offer: str) -> str:
    labels = {
        "free": "Free",
        "rent": "Rent",
        "buy": "Buy",
        "subscription": "Subscription",
        "sub": "Subscription",
    }
    return labels.get(offer.strip().lower(), offer.strip().title())


def media_details(item: MediaItem) -> MediaDetails:
    raw = item.raw
    facts = [kind_label(item.kind)]
    for value in (
        getattr(raw, "year", None),
        playlist_count_label(raw),
        format_duration(getattr(raw, "duration", None)),
        edition_label(raw),
        watched_state(raw),
        "" if item.kind == "episode" else episode_label(raw),
        getattr(raw, "contentRating", None),
        rating_compact(raw),
        getattr(raw, "studio", None),
    ):
        if value:
            facts.append(str(value))
    sub_count = subtitle_label(raw)
    if sub_count:
        facts.append(sub_count)

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
    kind = str(getattr(raw, "TYPE", raw.__class__.__name__)).lower()
    attrs = (
        ("thumb", "parentThumb", "grandparentThumb", "art")
        if kind in {"show", "season", "episode"}
        else ("grandparentThumb", "parentThumb", "thumb", "art")
    )
    for attr in attrs:
        value = getattr(raw, attr, None)
        if value:
            return str(value)
    return ""


def metadata_fields(raw: Any) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for label, value in (
        ("Type", getattr(raw, "TYPE", "")),
        ("Year", getattr(raw, "year", None)),
        ("Begins", format_optional_timestamp_time(getattr(raw, "begins_at", 0))),
        ("Ends", format_optional_timestamp_time(getattr(raw, "ends_at", 0))),
        ("Duration", format_duration(getattr(raw, "duration", None))),
        ("On Air", bool_label(getattr(raw, "on_air", None))),
        ("Resolution", getattr(raw, "video_resolution", None)),
        ("Items", playlist_count_label(raw)),
        ("Playlist Type", getattr(raw, "playlistType", None)),
        ("Smart Playlist", bool_label(getattr(raw, "smart", None))),
        ("Edition", edition_label(raw)),
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


def parse_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_timestamp_ms(value: Any) -> int:
    parsed = parse_int(value)
    if parsed and parsed < 10_000_000_000:
        return parsed * 1000
    return parsed


def format_optional_timestamp_time(milliseconds: int) -> str:
    return format_timestamp_time(milliseconds) if milliseconds else ""


def playlist_count_label(raw: Any) -> str:
    count = getattr(raw, "leafCount", None)
    if count is None:
        return ""
    try:
        parsed = int(count)
    except (TypeError, ValueError):
        return ""
    label = "item" if parsed == 1 else "items"
    return f"{parsed} {label}"


def bool_label(value: Any) -> str:
    if value is None or value == "":
        return ""
    return "yes" if bool(value) else "no"


def category_items(library: LibraryItem) -> list[MediaItem]:
    categories: list[Any] = []
    native_categories = getattr(library.raw, "categories", None)
    if callable(native_categories):
        try:
            categories = list(native_categories())
        except Exception:
            categories = []
    if not categories:
        choices = getattr(library.raw, "listFilterChoices", None)
        if callable(choices):
            try:
                categories = list(choices("genre"))
            except Exception:
                categories = []
    refs = []
    seen = set()
    for index, category in enumerate(categories):
        title = category_title(category)
        if not title:
            continue
        filter_value = category_filter_value(category) or title
        key = f"{library.key}:category:{filter_value or index}"
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            to_media_item(
                CategoryRef(
                    title=title,
                    key=key,
                    library=library,
                    raw=category,
                    filter_value=filter_value,
                )
            )
        )
    return refs


def category_title(category: Any) -> str:
    for attr in ("title", "tag", "name", "key"):
        value = getattr(category, attr, "")
        if value:
            return str(value)
    return str(category or "")


def category_filter_value(category: Any) -> str:
    for attr in ("key", "tag", "title", "name"):
        value = getattr(category, attr, "")
        if value:
            return str(value)
    return ""


def movie_edition_items(raw: Any) -> list[MediaItem]:
    editions = getattr(raw, "editions", None)
    if not callable(editions):
        return []
    try:
        return [to_media_item(item) for item in editions()]
    except Exception:
        return []


def edition_label(raw: Any) -> str:
    for attr in ("editionTitle", "edition"):
        value = getattr(raw, attr, "")
        if value:
            return str(value)
    return ""


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
    if resume_offset(raw):
        return "in progress"
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


def progress_label(raw: Any) -> str:
    offset = resume_offset(raw)
    if not offset:
        return ""
    duration = duration_ms(raw)
    if duration:
        percent = min(99, max(1, round(offset / duration * 100)))
        return f"{format_position(offset)} / {format_position(duration)} ({percent}%)"
    return f"Resume at {format_position(offset)}"


def progress_percent(raw: Any) -> int:
    if watched_state(raw) == "watched":
        return 100
    offset = resume_offset(raw)
    duration = duration_ms(raw)
    if not offset or not duration:
        return 0
    return min(99, max(1, round(offset / duration * 100)))


def progress_bar(raw: Any, width: int = 8) -> str:
    width = max(1, width)
    percent = progress_percent(raw)
    if not percent:
        return ""
    filled = width if percent == 100 else max(1, round(width * percent / 100))
    filled = min(width, filled)
    empty = width - filled
    return f"[{'#' * filled}{'-' * empty}] {percent}%"


def row_progress_marker(raw: Any) -> str:
    if is_online_metadata(raw):
        return ""
    state = watched_state(raw)
    if state == "watched":
        return progress_bar(raw)
    if state == "in progress":
        bar = progress_bar(raw)
        return bar or f"[resume {format_position(resume_offset(raw))}]"
    return ""


def is_online_metadata(raw: Any) -> bool:
    if is_metadata_provider_server(getattr(raw, "_server", None)):
        return True
    iter_parts = getattr(raw, "iterParts", None)
    if not callable(iter_parts):
        return False
    try:
        parts = list(iter_parts())
    except Exception:
        return False
    return bool(parts and is_metadata_provider_server(getattr(parts[0], "_server", None)))


def online_metadata_children(raw: Any, size: int = DEFAULT_PAGE_SIZE) -> list[MediaItem]:
    key = online_metadata_key(raw)
    fetch_items = getattr(raw, "fetchItems", None)
    if not key or not callable(fetch_items):
        return []
    try:
        return [to_media_item(child) for child in fetch_items(f"{key.rstrip('/')}/children", maxresults=size)]
    except Exception:
        return []


def online_metadata_key(raw: Any) -> str:
    key = str(getattr(raw, "key", "") or "")
    if key:
        return key
    details_key = str(getattr(raw, "_details_key", "") or "").split("?", 1)[0]
    if details_key:
        return details_key
    guid = str(getattr(raw, "guid", "") or "")
    if guid.startswith("plex://") and "/" in guid:
        return "/library/metadata/" + guid.rsplit("/", 1)[-1]
    return ""


def is_metadata_provider_server(server: Any) -> bool:
    baseurl = str(getattr(server, "_baseurl", "") or "")
    return "metadata.provider.plex.tv" in baseurl


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


def episode_context_label(raw: Any) -> str:
    if getattr(raw, "TYPE", "") != "episode":
        return ""
    parts = [
        getattr(raw, "grandparentTitle", None),
        getattr(raw, "parentTitle", None),
        episode_label(raw),
    ]
    return " / ".join(str(part) for part in parts if part)


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
