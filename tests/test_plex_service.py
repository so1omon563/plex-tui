from __future__ import annotations

from plextui.models import LibraryItem, MediaItem
from plextui.plex_service import (
    MediaPage,
    PlexService,
    artwork_path,
    category_items,
    episode_context_label,
    kind_label,
    media_key,
    media_details,
    progress_bar,
    progress_label,
    row_progress_marker,
    to_media_item,
    availability_urls,
    watched_state,
)


class Availability:
    title = "Tubi"
    offerType = "free"
    platform = "tubi-tv"
    url = "https://tubitv.example/movie"


class RawItem:
    TYPE = "movie"
    title = "Movie"
    ratingKey = "1"

    def getStreamURL(self):
        return "http://plex/movie"


class SecondRawItem(RawItem):
    title = "Second Movie"
    ratingKey = "2"


class ShowRawItem(RawItem):
    TYPE = "show"
    title = "Second Show"
    ratingKey = "show-2"


class ClipRawItem(RawItem):
    TYPE = "clip"
    title = "Noisy Clip"
    ratingKey = "clip-1"


class DiscoverRawItem(RawItem):
    title = "Free Movie"
    ratingKey = "plex://movie/1"
    year = 2024

    def streamingServices(self):
        return [Availability()]


class BackToFutureRawItem(DiscoverRawItem):
    title = "Back to the Future"
    ratingKey = "plex://movie/back-to-the-future"


class BackToSchoolRawItem(DiscoverRawItem):
    title = "Back to School"
    ratingKey = "plex://movie/back-to-school"


class RawHubItem:
    TYPE = None
    title = "Recently Released Movies"
    ratingKey = "hub-1"
    thumb = "/library/hubs/recently-released/thumb"


class VodHubRawItem(RawHubItem):
    title = "Plex Picks"
    ratingKey = "vod-hub-1"


class EditionRawItem(RawItem):
    title = "Movie"
    ratingKey = "3"
    editionTitle = "Director's Cut"


class AudioStream:
    displayTitle = "Japanese"
    codec = "aac"
    channels = 2
    selected = True


class ExternalSubtitleStream:
    displayTitle = "English"
    codec = "srt"
    key = "/library/streams/1"
    selected = True


class EmbeddedSubtitleStream:
    displayTitle = "Signs"
    codec = "vobsub"
    key = None
    forced = True


class Part:
    def audioStreams(self):
        return [AudioStream()]

    def subtitleStreams(self):
        return [ExternalSubtitleStream(), EmbeddedSubtitleStream()]


class DetailedRawItem(RawItem):
    summary = "Summary"
    grandparentThumb = "/library/metadata/show/thumb"
    parentThumb = "/library/metadata/season/thumb"
    thumb = "/library/metadata/movie/thumb"
    duration = 600000
    viewOffset = 120000
    audienceRating = 8.5
    contentRating = "PG-13"
    studio = "Studio"

    def iterParts(self):
        return [Part()]


class TvEpisodeRawItem(DetailedRawItem):
    TYPE = "episode"
    title = "Episode"
    thumb = "/library/metadata/episode/thumb"
    grandparentTitle = "Berserk"
    parentTitle = "Season 1"
    parentIndex = 1
    index = 2


class TvSeasonRawItem(DetailedRawItem):
    TYPE = "season"
    title = "Season 1"
    thumb = "/library/metadata/season-own/thumb"


class RawPage(list):
    totalSize = 250


class RawLibrary:
    def __init__(self) -> None:
        self.calls = []

    def all(self, **kwargs):
        self.calls.append(kwargs)
        return RawPage([RawItem()])

    def search(self, query=None, **kwargs):
        self.calls.append((query, kwargs))
        return RawPage([RawItem()])

    def hubs(self):
        self.calls.append(("hubs", {}))
        return [RawHubItem(), SecondRawItem()]

    def collections(self, **kwargs):
        self.calls.append(("collections", kwargs))
        return RawPage([RawItem()])

    def playlists(self, **kwargs):
        self.calls.append(("playlists", kwargs))
        return RawPage([RawItem()])

    def listFilterChoices(self, field):
        self.calls.append(("choices", field))
        return [type("Genre", (), {"title": "Sci-Fi", "key": "science_fiction"})()]


class RawLibraryHub:
    def __init__(self) -> None:
        self.calls = []

    def onDeck(self):
        self.calls.append(())
        return [RawItem(), SecondRawItem()]


class RawPlaylist:
    TYPE = "playlist"
    title = "Favorites"
    ratingKey = "playlist-1"
    key = "/playlists/1"
    leafCount = 2
    playlistType = "video"
    smart = False

    def __init__(self) -> None:
        self.calls = []

    def items(self):
        self.calls.append(("items",))
        return [RawItem()]

    def addItems(self, items):
        self.calls.append(("addItems", items))
        return self

    def removeItems(self, items):
        self.calls.append(("removeItems", items))
        return self

    def _edit(self, **kwargs):
        self.calls.append(("edit", kwargs))
        self.title = kwargs.get("title", self.title)
        return self

    def delete(self):
        self.calls.append(("delete",))


class RawServer:
    def __init__(self) -> None:
        self.calls = []
        self.raw_playlist = RawPlaylist()

    def search(self, query, **kwargs):
        self.calls.append((query, kwargs))
        return [RawItem()]

    def playlists(self):
        self.calls.append(("playlists",))
        return [self.raw_playlist]

    def createPlaylist(self, title, items=None):
        self.calls.append(("createPlaylist", title, items))
        playlist = RawPlaylist()
        playlist.title = title
        return playlist


def test_library_page_fetches_single_plex_page():
    raw_library = RawLibrary()
    service = object.__new__(PlexService)
    library = LibraryItem("Movies", "1", "movie", raw_library)

    page = service.library_page(library, start=100, size=50)

    assert raw_library.calls == [
        {"maxresults": 50, "container_start": 100, "container_size": 50}
    ]
    assert len(page.items) == 1
    assert page.start == 100
    assert page.total == 250
    assert page.next_start == 101
    assert page.has_more


def test_library_entry_page_fetches_supported_submenus():
    raw_library = RawLibrary()
    service = object.__new__(PlexService)
    library = LibraryItem("Movies", "1", "movie", raw_library)

    recommended = service.library_entry_page(library, "recommended", start=0, size=2)
    collections = service.library_entry_page(library, "collections", start=50, size=25)
    playlists = service.library_entry_page(library, "playlists", start=75, size=25)
    categories = service.library_entry_page(library, "categories", start=0, size=25)

    assert raw_library.calls == [
        ("hubs", {}),
        ("collections", {"maxresults": 25, "container_start": 50, "container_size": 25}),
        ("playlists", {"maxresults": 25, "container_start": 75, "container_size": 25}),
        ("choices", "genre"),
    ]
    assert [item.title for item in recommended.items] == ["Recently Released Movies", "Second Movie"]
    assert [item.kind for item in recommended.items] == ["hub", "hub"]
    assert [item.playable for item in recommended.items] == [False, False]
    assert recommended.start == 0
    assert recommended.total == 2
    assert len(collections.items) == 1
    assert collections.has_more
    assert len(playlists.items) == 1
    assert playlists.has_more
    assert [item.title for item in categories.items] == ["Sci-Fi"]
    assert categories.items[0].kind == "category"


def test_category_children_fetch_library_search_results():
    raw_library = RawLibrary()
    service = object.__new__(PlexService)
    library = LibraryItem("Movies", "1", "movie", raw_library)
    category = category_items(library)[0]
    raw_library.calls.clear()

    page = service.category_page(category.raw, start=50, size=25)

    assert raw_library.calls == [
        (None, {"maxresults": 25, "container_start": 50, "container_size": 25, "genre": "science_fiction"})
    ]
    assert len(page.items) == 1
    assert page.has_more


def test_playlist_helpers_create_add_and_remove_items():
    service = object.__new__(PlexService)
    service.server = RawServer()
    item = MediaItem("Movie", "", "movie", "1", True, RawItem())

    playlists = service.playlists()
    created = service.create_playlist_from_items("Weekend", [item])
    second = MediaItem("Second Movie", "", "movie", "2", True, SecondRawItem())
    added = service.add_items_to_playlist(playlists[0], [item, second])
    removed = service.remove_items_from_playlist(playlists[0], [item, second])
    renamed = service.rename_playlist(playlists[0], "Renamed")
    service.delete_playlist(playlists[0])

    assert service.server.calls == [
        ("playlists",),
        ("createPlaylist", "Weekend", [item.raw]),
    ]
    assert playlists[0].title == "Favorites"
    assert created.title == "Weekend"
    assert added.title == "Favorites"
    assert removed.title == "Favorites"
    assert renamed.title == "Renamed"
    assert service.server.raw_playlist.calls == [
        ("addItems", [item.raw, second.raw]),
        ("removeItems", [item.raw, second.raw]),
        ("edit", {"title": "Renamed"}),
        ("delete",),
    ]


def test_movie_editions_are_visible_as_variants():
    class MultiEditionRaw(RawItem):
        def editions(self):
            return [RawItem(), EditionRawItem()]

    service = object.__new__(PlexService)
    item = to_media_item(MultiEditionRaw())

    children = service.children(item)

    assert [child.subtitle for child in children] == ["", "Director's Cut"]
    assert media_details(children[1]).metadata[0:2] == [
        ("Type", "movie"),
        ("Edition", "Director's Cut"),
    ]


def test_search_page_fetches_single_library_search_page():
    raw_library = RawLibrary()
    service = object.__new__(PlexService)
    library = LibraryItem("Movies", "1", "movie", raw_library)

    page = service.search_page("akira", library, start=50, size=25)

    assert raw_library.calls == [
        ("akira", {"maxresults": 25, "container_start": 50, "container_size": 25})
    ]
    assert len(page.items) == 1
    assert page.start == 50
    assert page.total == 250
    assert page.has_more


def test_continue_watching_page_fetches_on_deck_page():
    raw_library = RawLibraryHub()
    service = object.__new__(PlexService)
    service.server = type("Server", (), {"library": raw_library})()

    page = service.continue_watching_page(start=1, size=1)

    assert raw_library.calls == [()]
    assert len(page.items) == 1
    assert page.items[0].title == "Second Movie"
    assert page.start == 1
    assert page.total == 2
    assert not page.has_more


def test_global_search_page_is_bounded_and_not_paged():
    service = object.__new__(PlexService)
    service.server = RawServer()

    page = service.search_page("akira", None, start=0, size=25)
    empty_page = service.search_page("akira", None, start=25, size=25)

    assert service.server.calls == [("akira", {"limit": 25})]
    assert len(page.items) == 1
    assert page.total == 1
    assert not page.has_more
    assert empty_page.items == []
    assert empty_page.total == 25


def test_discover_page_uses_account_token_and_slices(monkeypatch):
    calls = []

    class FakeAccount:
        def __init__(self, token):
            calls.append(("token", token))

        def searchDiscover(self, query, **kwargs):
            calls.append((query, kwargs))
            return [DiscoverRawItem(), ShowRawItem(), ClipRawItem(), SecondRawItem()]

    monkeypatch.setattr("plextui.plex_service.MyPlexAccount", FakeAccount)
    service = object.__new__(PlexService)
    service.config = type("Config", (), {"account_token": "account-token"})()

    page = service.discover_page("matrix", start=0, size=2)

    assert calls == [
        ("token", "account-token"),
        ("matrix", {"limit": 8, "providers": "discover,PLEXAVOD"}),
    ]
    assert [item.title for item in page.items] == ["Free Movie", "Second Show"]
    assert page.items[0].subtitle == "2024  1 provider: Tubi · Free"
    assert page.items[0].playable is False
    assert page.total == 3


def test_video_on_demand_page_uses_account_token_and_returns_hubs(monkeypatch):
    calls = []

    class FakeAccount:
        def __init__(self, token):
            calls.append(("token", token))

        def videoOnDemand(self):
            calls.append(("videoOnDemand", None))
            return [VodHubRawItem()]

    monkeypatch.setattr("plextui.plex_service.MyPlexAccount", FakeAccount)
    service = object.__new__(PlexService)
    service.config = type("Config", (), {"account_token": "account-token"})()

    page = service.video_on_demand_page(start=0, size=10)

    assert calls == [("token", "account-token"), ("videoOnDemand", None)]
    assert isinstance(page, MediaPage)
    assert [(item.title, item.kind, item.playable) for item in page.items] == [("Plex Picks", "hub", False)]


def test_vod_hub_children_resolve_relative_hub_key():
    class AccountServer:
        VOD = "https://vod.provider.plex.tv"

        def __init__(self):
            self.converted = []

        def _toOnlineMetadata(self, items):
            self.converted.extend(items)
            for item in items:
                item.converted_to_online_metadata = True
            return items

    class VodHub:
        TYPE = None
        title = "Sci-Fi"
        key = "/hubs/sections/movies/sci-fi"
        ratingKey = "vod-hub"

        def __init__(self):
            self.calls = []
            self._server = AccountServer()

        def fetchItems(self, key, **kwargs):
            self.calls.append((key, kwargs))
            return [RawItem(), SecondRawItem()]

        def items(self):
            raise AssertionError("relative VOD hub keys must be fetched with the VOD host")

    service = object.__new__(PlexService)
    raw = VodHub()

    children = service.children(to_media_item(raw), size=1)

    assert raw.calls == [("https://vod.provider.plex.tv/hubs/sections/movies/sci-fi", {"maxresults": 1})]
    assert raw._server.converted[0].converted_to_online_metadata is True
    assert [child.title for child in children] == ["Movie"]


def test_discover_page_can_show_all_result_types(monkeypatch):
    class FakeAccount:
        def __init__(self, token):
            pass

        def searchDiscover(self, query, **kwargs):
            return [DiscoverRawItem(), ClipRawItem()]

    monkeypatch.setattr("plextui.plex_service.MyPlexAccount", FakeAccount)
    service = object.__new__(PlexService)
    service.config = type("Config", (), {"account_token": "account-token"})()

    page = service.discover_page("matrix", start=0, size=2, media_type="all")

    assert [item.title for item in page.items] == ["Free Movie", "Noisy Clip"]


def test_discover_page_prefers_query_title_matches(monkeypatch):
    class FakeAccount:
        def __init__(self, token):
            pass

        def searchDiscover(self, query, **kwargs):
            return [BackToSchoolRawItem(), BackToFutureRawItem(), ShowRawItem()]

    monkeypatch.setattr("plextui.plex_service.MyPlexAccount", FakeAccount)
    service = object.__new__(PlexService)
    service.config = type("Config", (), {"account_token": "account-token"})()

    page = service.discover_page("Back to the Future", start=0, size=10)

    assert [item.title for item in page.items] == ["Back to the Future"]


def test_discover_media_key_falls_back_when_rating_key_is_nan():
    class DiscoverResult(DiscoverRawItem):
        ratingKey = float("nan")
        key = "/library/metadata/discover-1"

    assert media_key(DiscoverResult()) == "/library/metadata/discover-1"
    assert to_media_item(DiscoverResult()).key == "/library/metadata/discover-1"


def test_availability_urls_include_provider_labels():
    assert availability_urls(DiscoverRawItem()) == [("Tubi · Free", "https://tubitv.example/movie")]


def test_media_details_include_audio_and_subtitle_locations():
    item = MediaItem("Movie", "", "movie", "1", True, DetailedRawItem())

    details = media_details(item)

    assert details.facts == [
        "Movie",
        "10m",
        "in progress",
        "PG-13",
        "Rating 8.5",
        "Studio",
        "2 subtitles",
    ]
    assert ("Status", "in progress") in details.metadata
    assert ("Progress", "2m / 10m (20%)") in details.metadata
    assert details.audio == ["Japanese (aac, 2ch, selected)"]
    assert details.subtitles == [
        "English (srt, external, selected)",
        "Signs (vobsub, embedded, forced)",
    ]
    assert details.artwork_path == "/library/metadata/show/thumb"


def test_episode_items_include_show_and_season_context():
    item = to_media_item(TvEpisodeRawItem())

    assert item.title == "Episode"
    assert item.subtitle == "Berserk / Season 1 / S01E02  10m"
    assert episode_context_label(TvEpisodeRawItem()) == "Berserk / Season 1 / S01E02"

    details = media_details(item)

    assert "Berserk" not in details.facts
    assert "Season 1" not in details.facts
    assert "S01E02" not in details.facts
    assert ("Show", "Berserk") in details.metadata
    assert ("Season", "Season 1") in details.metadata
    assert ("Episode", "S01E02") in details.metadata


def test_tv_episode_artwork_prefers_episode_still():
    assert artwork_path(TvEpisodeRawItem()) == "/library/metadata/episode/thumb"
    assert to_media_item(TvEpisodeRawItem()).artwork_path == "/library/metadata/episode/thumb"


def test_tv_season_artwork_prefers_season_poster():
    assert artwork_path(TvSeasonRawItem()) == "/library/metadata/season-own/thumb"
    assert to_media_item(TvSeasonRawItem()).artwork_path == "/library/metadata/season-own/thumb"


def test_tv_artwork_falls_back_to_parent_then_show_art():
    class EpisodeWithoutStill(TvEpisodeRawItem):
        thumb = ""

    class SeasonWithoutPoster(TvSeasonRawItem):
        thumb = ""

    class EpisodeWithoutSeasonArt(TvEpisodeRawItem):
        thumb = ""
        parentThumb = ""

    assert artwork_path(EpisodeWithoutStill()) == "/library/metadata/season/thumb"
    assert artwork_path(SeasonWithoutPoster()) == "/library/metadata/season/thumb"
    assert artwork_path(EpisodeWithoutSeasonArt()) == "/library/metadata/show/thumb"


def test_kind_label_humanizes_known_and_unknown_media_types():
    assert kind_label("movie") == "Movie"
    assert kind_label("show") == "TV Show"
    assert kind_label("photoalbum") == "Photo Album"
    assert kind_label("weird") == "Weird"


def test_progress_helpers_report_watched_resume_and_unwatched():
    class Watched(RawItem):
        viewCount = 1
        duration = 600000
        viewOffset = 0

    class Partial(RawItem):
        duration = 600000
        viewOffset = 65000

    class Unwatched(RawItem):
        duration = 600000
        viewOffset = 0

        def isWatched(self):
            return False

    assert watched_state(Watched()) == "watched"
    assert progress_bar(Watched()) == "[########] 100%"
    assert row_progress_marker(Watched()) == "[########] 100%"
    assert watched_state(Partial()) == "in progress"
    assert progress_label(Partial()) == "1m / 10m (11%)"
    assert progress_bar(Partial()) == "[#-------] 11%"
    assert row_progress_marker(Partial()) == "[#-------] 11%"
    assert watched_state(Unwatched()) == "unwatched"
    assert row_progress_marker(Unwatched()) == ""


def test_online_metadata_row_progress_does_not_trigger_reload():
    class OnlineServer:
        _baseurl = "https://metadata.provider.plex.tv"

    class OnlineRaw(RawItem):
        _server = OnlineServer()

        @property
        def viewCount(self):
            raise AssertionError("online list rows must not reload watch state")

    assert row_progress_marker(OnlineRaw()) == ""
