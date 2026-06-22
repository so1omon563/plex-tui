from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
import re
from typing import Any

from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer

from .config import AppConfig, config_path
from .models import LibraryItem, MediaDetails, MediaItem


PLAYABLE_TYPES = {"movie", "episode", "track", "clip"}
DEFAULT_PAGE_SIZE = 100
DISCOVER_PROVIDERS = "discover,PLEXAVOD"

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

    def continue_watching_page(self, start: int = 0, size: int = DEFAULT_PAGE_SIZE) -> MediaPage:
        raw_items = list(self.server.library.onDeck())
        items = [to_media_item(item) for item in raw_items[start:start + size]]
        return MediaPage(items=items, start=start, total=len(raw_items))

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


def to_media_item(raw: Any) -> MediaItem:
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
    return MediaItem(
        title=getattr(raw, "title", "Untitled"),
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


def media_key(raw: Any) -> str:
    for attr in ("ratingKey", "key", "guid"):
        value = getattr(raw, attr, None)
        if value is None or value == "" or value != value:
            continue
        return str(value)
    return str(getattr(raw, "title", ""))


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
        ("Duration", format_duration(getattr(raw, "duration", None))),
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
