from __future__ import annotations

from datetime import date, datetime, timezone

from plextui.models import LibraryItem, MediaItem
from plextui.plex_service import (
    EPG_PROVIDER_BASE,
    HostedLiveTVChannel,
    MediaPage,
    PlexService,
    artwork_path,
    category_items,
    episode_context_label,
    episode_parent_key,
    episode_show_parent_key,
    kind_label,
    hosted_live_tv_channel_from_raw,
    hosted_live_tv_guide_date,
    media_key,
    media_details,
    progress_bar,
    progress_label,
    row_progress_marker,
    to_media_item,
    availability_urls,
    hosted_live_tv_program_on_air,
    hosted_live_tv_program_from_raw,
    signed_epg_url,
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


class NoneTitleRawItem:
    TYPE = "movie"
    title = None


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

    def hubs(self, **kwargs):
        self.calls.append(("hubs", kwargs))
        return [RawHub([RawItem(), SecondRawItem()])]

    def onDeck(self):
        self.calls.append(())
        return [RawItem(), SecondRawItem()]


class RawLibraryOnDeck:
    def __init__(self) -> None:
        self.calls = []

    def onDeck(self):
        self.calls.append(())
        return [RawItem(), SecondRawItem()]


class RawHub:
    def __init__(self, items) -> None:
        self._items = items

    def items(self):
        return self._items


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

    def continueWatching(self):
        self.calls.append(("continueWatching",))
        return [RawItem(), SecondRawItem()]

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


class JsonResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


class ContinueWatchHubWrapper:
    title = "Wrapped Episode"
    ratingKey = "hub-wrapper-1"

    def __init__(self, metadata: RawItem) -> None:
        self.metadata = metadata


class BareContinueWatchRawItem:
    TYPE = "movie"
    title = "Wrapped Movie"
    ratingKey = "10"


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
    recently_added = service.library_entry_page(library, "recently_added", start=25, size=25)
    collections = service.library_entry_page(library, "collections", start=50, size=25)
    playlists = service.library_entry_page(library, "playlists", start=75, size=25)
    categories = service.library_entry_page(library, "categories", start=0, size=25)

    assert raw_library.calls == [
        ("hubs", {}),
        (None, {"sort": "addedAt:desc", "maxresults": 25, "container_start": 25, "container_size": 25}),
        ("collections", {"maxresults": 25, "container_start": 50, "container_size": 25}),
        ("playlists", {"maxresults": 25, "container_start": 75, "container_size": 25}),
        ("choices", "genre"),
    ]
    assert [item.title for item in recommended.items] == ["Recently Released Movies", "Second Movie"]
    assert [item.kind for item in recommended.items] == ["hub", "hub"]
    assert [item.playable for item in recommended.items] == [False, False]
    assert recommended.start == 0
    assert recommended.total == 2
    assert len(recently_added.items) == 1
    assert recently_added.start == 25
    assert recently_added.has_more
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


def test_continue_watching_page_fetches_home_continue_hub():
    raw_library = RawLibraryHub()
    service = object.__new__(PlexService)
    service.server = RawServer()
    service.server.library = raw_library

    page = service.continue_watching_page(start=1, size=1)

    assert service.server.calls == [("continueWatching",)]
    assert raw_library.calls == [("hubs", {"identifier": "home.continue"})]
    assert len(page.items) == 1
    assert page.items[0].title == "Second Movie"
    assert page.start == 1
    assert page.total == 2
    assert not page.has_more


def test_continue_watching_page_uses_metadata_payload_for_playable_items():
    raw_episode = TvEpisodeRawItem()
    hub_item = ContinueWatchHubWrapper(metadata=raw_episode)
    class WrappedContinueLibrary:
        def __init__(self) -> None:
            self.calls = []

        def hubs(self, **kwargs):
            self.calls.append(("hubs", kwargs))
            return [RawHub([hub_item])]

        def onDeck(self):
            self.calls.append(("onDeck",))
            return []

    class WrappedContinueServer:
        def __init__(self) -> None:
            self.library = WrappedContinueLibrary()

    service = object.__new__(PlexService)
    service.server = WrappedContinueServer()

    page = service.continue_watching_page(start=0, size=1)

    assert [item.kind for item in page.items] == ["episode"]
    assert page.items[0].playable
    assert page.items[0].raw is raw_episode
    assert service.server.library.calls == [("hubs", {"identifier": "home.continue"})]


def test_continue_watching_page_keeps_playable_items_with_media_children():
    class MediaChild:
        duration = 654321

    class MovieWithMediaChildren(RawItem):
        media = [MediaChild()]

    raw_movie = MovieWithMediaChildren()
    raw_library = type(
        "Library",
        (),
        {
            "calls": [],
            "hubs": lambda self, **kwargs: self.calls.append(("hubs", kwargs))
            or [RawHub([raw_movie])],
            "onDeck": lambda self: self.calls.append(("onDeck",))
            or [],
        },
    )()
    service = object.__new__(PlexService)
    service.server = type("Server", (), {"library": raw_library})()

    page = service.continue_watching_page(start=0, size=1)

    assert page.items[0].title == "Movie"
    assert page.items[0].kind == "movie"
    assert page.items[0].playable
    assert page.items[0].raw is raw_movie


def test_continue_watching_page_includes_items_from_all_sources():
    endpoint_second = SecondRawItem()
    endpoint_first = RawItem()
    raw_library = type(
        "Library",
        (),
        {
            "calls": [],
            "hubs": lambda self, **kwargs: self.calls.append(("hubs", kwargs))
            or [RawHub([endpoint_first])],
            "onDeck": lambda self: self.calls.append(("onDeck",))
            or [],
        },
    )()
    service = object.__new__(PlexService)
    service.server = type(
        "Server",
        (),
        {
            "library": raw_library,
            "calls": [],
            "continueWatching": lambda self: self.calls.append(("continueWatching",))
            or [endpoint_second, endpoint_first],
        },
    )()

    page = service.continue_watching_page(start=0, size=10)

    assert raw_library.calls == [("hubs", {"identifier": "home.continue"})]
    assert service.server.calls == [("continueWatching",)]
    assert [item.title for item in page.items] == ["Second Movie", "Movie"]
    assert page.total == 2


def test_continue_watching_dedupes_same_guid_with_different_keys():
    class AndorVariant(TvEpisodeRawItem):
        title = "Andor"
        guid = "plex://episode/andor-1"

        def __init__(self, rating_key: str) -> None:
            self.ratingKey = rating_key
            self.key = f"/library/metadata/{rating_key}"

    hub_item = AndorVariant("direct")
    endpoint_item = AndorVariant("optimized")
    raw_library = type(
        "Library",
        (),
        {
            "calls": [],
            "hubs": lambda self, **kwargs: self.calls.append(("hubs", kwargs))
            or [RawHub([hub_item])],
            "onDeck": lambda self: self.calls.append(("onDeck",))
            or [],
        },
    )()
    service = object.__new__(PlexService)
    service.server = type(
        "Server",
        (),
        {
            "library": raw_library,
            "calls": [],
            "continueWatching": lambda self: self.calls.append(("continueWatching",))
            or [endpoint_item],
        },
    )()

    page = service.continue_watching_page(start=0, size=10)

    assert [item.title for item in page.items] == ["Andor"]
    assert page.total == 1


def test_continue_watching_page_fetches_non_playable_items_by_key():
    raw_library = type(
        "Library",
        (),
        {
            "calls": [],
            "hubs": lambda self, **kwargs: self.calls.append(("hubs", kwargs))
            or [RawHub([BareContinueWatchRawItem()])],
            "onDeck": lambda self: self.calls.append(("onDeck",))
            or [],
        },
    )()

    class ContinueServer:
        def __init__(self) -> None:
            self.library = raw_library
            self.calls = []
            self.fetched = []

        def continueWatching(self):
            self.calls.append(("continueWatching",))
            return [BareContinueWatchRawItem()]

        def fetchItem(self, key: str):
            self.fetched.append(key)
            resolved = TvEpisodeRawItem()
            resolved.ratingKey = key
            return resolved

    service = object.__new__(PlexService)
    service.server = ContinueServer()

    page = service.continue_watching_page(start=0, size=10)

    assert page.items[0].playable
    assert service.server.fetched == [10, 10]


def test_continue_watching_page_falls_back_to_continue_watching_endpoint():
    raw_library = RawLibraryHub()

    def broken_hubs(**kwargs):
        raw_library.calls.append(("hubs", kwargs))
        raise RuntimeError("unsupported")

    raw_library.hubs = broken_hubs
    service = object.__new__(PlexService)
    service.server = RawServer()
    service.server.library = raw_library

    page = service.continue_watching_page(start=1, size=1)

    assert raw_library.calls == [("hubs", {"identifier": "home.continue"})]
    assert service.server.calls == [("continueWatching",)]
    assert page.items[0].title == "Second Movie"


def test_media_from_key_uses_server_fetch_item():
    raw = RawItem()
    class FetchServer(RawServer):
        def __init__(self) -> None:
            super().__init__()
            self.fetched = []

        def fetchItem(self, key: str):
            self.fetched.append(key)
            return raw

    service = object.__new__(PlexService)
    service.server = FetchServer()

    result = service.media_from_key("1")

    assert result is raw
    assert service.server.fetched == [1]


def test_continue_watching_page_falls_back_to_on_deck():
    raw_library = RawLibraryOnDeck()
    service = object.__new__(PlexService)
    service.server = type("Server", (), {"library": raw_library})()

    page = service.continue_watching_page(start=1, size=1)

    assert raw_library.calls == [()]
    assert page.items[0].title == "Second Movie"


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


def test_hosted_live_tv_page_fetches_channels_with_account_token(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, dict(request.header_items()), timeout))
        return JsonResponse(
            b"""
            {
              "MediaContainer": {
                "Channel": [
                  {
                    "id": "channel-1",
                    "title": "Live One",
                    "callSign": "ONE",
                    "summary": "Live channel description",
                    "isHd": true,
                    "thumb": "https://images.example/one.png",
                    "Media": [{"protocol": "hls", "container": "mpegts", "Part": [{"key": "/hls/one.m3u8"}]}]
                  },
                  {
                    "id": "channel-2",
                    "title": "Locked",
                    "drm": true,
                    "Media": [{"protocol": "hls", "Part": [{"key": "/hls/locked.m3u8"}]}]
                  }
                ]
              }
            }
            """
        )

    monkeypatch.setattr("plextui.plex_service.urlopen", fake_urlopen)
    service = object.__new__(PlexService)
    service.config = type("Config", (), {"account_token": "account-token"})()

    page = service.hosted_live_tv_page(start=0, size=10)

    assert calls == [
        (
            f"{EPG_PROVIDER_BASE}/lineups/plex/channels",
            {"Accept": "application/json", "X-plex-token": "account-token"},
            10,
        )
    ]
    assert [(item.title, item.subtitle, item.kind, item.playable) for item in page.items] == [
        ("Live One", "ONE  HD  HLS", "livetv", True),
        ("Locked", "HLS", "livetv", False),
    ]
    assert page.items[0].artwork_path == "https://images.example/one.png"
    assert media_details(page.items[0]).summary == "Live channel description"
    assert page.items[0].raw.getStreamURL() == f"{EPG_PROVIDER_BASE}/hls/one.m3u8?X-Plex-Token=account-token"
    assert page.total == 2


def test_hosted_live_tv_guide_page_fetches_selected_channel_programs(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, dict(request.header_items()), timeout))
        return JsonResponse(
            b"""
            {
              "MediaContainer": {
                "Metadata": [
                  {
                    "ratingKey": "program-1",
                    "title": "Morning News",
                    "summary": "Headlines",
                    "year": 2026,
                    "Image": [{"type": "coverPoster", "url": "https://images.example/news.png"}],
                    "Media": [{"beginsAt": 1782925200000, "endsAt": 1782928800000, "duration": 3600000, "onAir": true, "videoResolution": "1080"}]
                  },
                  {
                    "ratingKey": "program-2",
                    "title": "Earlier Show",
                    "Media": [{"beginsAt": 1782921600000, "endsAt": 1782925200000, "duration": 3600000}]
                  },
                  {
                    "ratingKey": "program-3",
                    "title": "Next Show",
                    "Media": [{"beginsAt": 1782928800000, "endsAt": 1782932400000, "duration": 3600000}]
                  }
                ]
              }
            }
            """
        )

    monkeypatch.setattr("plextui.plex_service.urlopen", fake_urlopen)
    monkeypatch.setattr("plextui.plex_service.time.time", lambda: 1782927000)
    service = object.__new__(PlexService)
    service.config = type("Config", (), {"account_token": "account-token"})()
    channel = to_media_item(
        HostedLiveTVChannel(
            title="Live One",
            key="channel-1",
            stream_url="https://stream.example/one.m3u8",
            grid_key="grid-1",
        )
    )

    page = service.hosted_live_tv_guide_page(channel, guide_date=date(2026, 7, 1), start=0, size=10)

    assert calls == [
        (
            f"{EPG_PROVIDER_BASE}/grid?channelGridKey=grid-1&date=2026-07-01",
            {"Accept": "application/json", "X-plex-token": "account-token"},
            10,
        )
    ]
    assert [(item.title, item.kind, item.playable) for item in page.items] == [
        ("Morning News", "livetv_program", False),
        ("Next Show", "livetv_program", False),
        ("Earlier Show", "livetv_program", False),
    ]
    assert "On now" in page.items[0].subtitle
    assert page.items[0].artwork_path == "https://images.example/news.png"
    details = media_details(page.items[0])
    metadata = dict(details.metadata)
    assert metadata["Begins"]
    assert metadata["Ends"]
    assert ("Resolution", "1080") in details.metadata
    assert details.summary == "Headlines"


def test_hosted_live_tv_channel_enrichment_adds_now_next(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, dict(request.header_items()), timeout))
        return JsonResponse(
            b"""
            {
              "MediaContainer": {
                "Metadata": [
                  {
                    "ratingKey": "program-0",
                    "title": "Already Over",
                    "Media": [{"beginsAt": 1782921600000, "endsAt": 1782925200000}]
                  },
                  {
                    "ratingKey": "program-1",
                    "title": "Now Showing",
                    "Media": [{"beginsAt": 1782925200000, "endsAt": 1782928800000, "onAir": true}]
                  },
                  {
                    "ratingKey": "program-2",
                    "title": "Up Next",
                    "Media": [{"beginsAt": 1782928800000, "endsAt": 1782932400000}]
                  }
                ]
              }
            }
            """
        )

    monkeypatch.setattr("plextui.plex_service.urlopen", fake_urlopen)
    monkeypatch.setattr("plextui.plex_service.time.time", lambda: 1782927000)
    service = object.__new__(PlexService)
    service.config = type("Config", (), {"account_token": "account-token"})()
    channel = to_media_item(
        HostedLiveTVChannel(
            title="Live One",
            key="channel-1",
            stream_url="https://stream.example/one.m3u8",
            grid_key="grid-1",
        )
    )

    enriched = service.enrich_hosted_live_tv_channel(channel)

    assert calls == [
        (
            f"{EPG_PROVIDER_BASE}/grid?channelGridKey=grid-1&date={hosted_live_tv_guide_date().isoformat()}",
            {"Accept": "application/json", "X-plex-token": "account-token"},
            10,
        )
    ]
    assert enriched.raw.current_program.title == "Now Showing"
    assert enriched.raw.next_program.title == "Up Next"


def test_hosted_live_tv_guide_date_uses_utc(monkeypatch):
    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            assert tz is timezone.utc
            return datetime(2026, 7, 3, 0, 48, tzinfo=timezone.utc)

    monkeypatch.setattr("plextui.plex_service.datetime", FakeDateTime)

    assert hosted_live_tv_guide_date() == date(2026, 7, 3)


def test_hosted_live_tv_channel_enrichment_keeps_channel_on_missing_data(monkeypatch):
    def fake_urlopen(request, timeout):
        raise OSError("guide unavailable")

    monkeypatch.setattr("plextui.plex_service.urlopen", fake_urlopen)
    service = object.__new__(PlexService)
    service.config = type("Config", (), {"account_token": "account-token"})()
    channel = to_media_item(
        HostedLiveTVChannel(
            title="Live One",
            key="channel-1",
            stream_url="https://stream.example/one.m3u8",
            grid_key="grid-1",
        )
    )

    assert service.enrich_hosted_live_tv_channel(channel) is channel


def test_hosted_live_tv_program_mapping_accepts_second_epoch_timestamps():
    program = hosted_live_tv_program_from_raw(
        {
            "ratingKey": "program-1",
            "title": "Late Show",
            "Media": [{"beginsAt": 1782921600, "endsAt": 1782925200}],
        }
    )

    assert program is not None
    assert program.begins_at == 1782921600000
    assert program.ends_at == 1782925200000


def test_hosted_live_tv_program_on_air_prefers_schedule_window():
    assert hosted_live_tv_program_on_air(False, 1_000, 2_000, now_ms=1_500)
    assert not hosted_live_tv_program_on_air(True, 1_000, 2_000, now_ms=2_500)
    assert hosted_live_tv_program_on_air(True, 0, 0, now_ms=2_500)


def test_hosted_live_tv_channel_mapping_signs_absolute_and_relative_urls():
    relative = hosted_live_tv_channel_from_raw(
        {
            "id": "relative",
            "title": "Relative",
            "Media": [{"protocol": "hls", "Part": [{"key": "/hls/channel.m3u8?foo=1"}]}],
        },
        "token",
    )
    absolute = hosted_live_tv_channel_from_raw(
        {
            "id": "absolute",
            "title": "Absolute",
            "Media": [{"protocol": "hls", "Part": [{"url": "https://cdn.example/live.m3u8"}]}],
        },
        "token",
    )

    assert relative is not None
    assert relative.stream_url == f"{EPG_PROVIDER_BASE}/hls/channel.m3u8?foo=1&X-Plex-Token=token"
    assert absolute is not None
    assert absolute.stream_url == "https://cdn.example/live.m3u8?X-Plex-Token=token"
    assert signed_epg_url(f"{EPG_PROVIDER_BASE}/hls/channel.m3u8?X-Plex-Token=old", "new") == (
        f"{EPG_PROVIDER_BASE}/hls/channel.m3u8?X-Plex-Token=new"
    )


def test_hosted_live_tv_channel_without_part_is_unplayable():
    channel = hosted_live_tv_channel_from_raw(
        {
            "id": "metadata-only",
            "title": "Metadata Only",
            "Media": [{"protocol": "hls"}],
        },
        "token",
    )

    assert channel is not None
    assert channel.key == "metadata-only"
    assert channel.stream_url == ""
    assert not to_media_item(channel).playable


def test_hosted_live_tv_drm_channel_rejects_stream_url():
    channel = HostedLiveTVChannel(
        title="Locked",
        key="locked",
        stream_url=f"{EPG_PROVIDER_BASE}/hls/locked.m3u8?X-Plex-Token=token",
        drm=True,
    )
    item = to_media_item(channel)

    assert not item.playable
    try:
        channel.getStreamURL()
    except RuntimeError as exc:
        assert "DRM-protected" in str(exc)
    else:
        raise AssertionError("expected DRM channel to reject stream URL")


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


def test_to_media_item_falls_back_when_title_is_missing():
    item = to_media_item(NoneTitleRawItem())

    assert item.title == "Untitled"


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


def test_episode_parent_uses_parent_key_to_fetch_season():
    class Episode(TvEpisodeRawItem):
        parentKey = "/library/metadata/season-1"

    class Season(TvSeasonRawItem):
        title = "Season 1"
        ratingKey = "season-1"

    class Server:
        def __init__(self) -> None:
            self.calls = []

        def fetchItem(self, key):
            self.calls.append(key)
            return Season()

    service = object.__new__(PlexService)
    service.server = Server()

    parent = service.episode_parent(to_media_item(Episode()))

    assert episode_parent_key(Episode()) == "/library/metadata/season-1"
    assert service.server.calls == ["/library/metadata/season-1"]
    assert parent is not None
    assert (parent.title, parent.kind) == ("Season 1", "season")


def test_episode_parent_falls_back_to_parent_rating_key():
    class Episode(TvEpisodeRawItem):
        parentRatingKey = "season-1"

    assert episode_parent_key(Episode()) == "season-1"


def test_episode_show_uses_grandparent_key_to_fetch_show():
    class Episode(TvEpisodeRawItem):
        grandparentKey = "/library/metadata/show-1"

    class Show(RawItem):
        TYPE = "show"
        title = "Berserk"
        ratingKey = "show-1"

    class Server:
        def __init__(self) -> None:
            self.calls = []

        def fetchItem(self, key):
            self.calls.append(key)
            return Show()

    service = object.__new__(PlexService)
    service.server = Server()

    show = service.episode_show(to_media_item(Episode()))

    assert episode_show_parent_key(Episode()) == "/library/metadata/show-1"
    assert service.server.calls == ["/library/metadata/show-1"]
    assert show is not None
    assert (show.title, show.kind) == ("Berserk", "show")


def test_episode_show_falls_back_to_grandparent_rating_key():
    class Episode(TvEpisodeRawItem):
        grandparentRatingKey = "show-1"

    assert episode_show_parent_key(Episode()) == "show-1"


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

    class ReplayedWatched(RawItem):
        viewCount = 1
        duration = 600000
        viewOffset = 30000

    assert watched_state(Watched()) == "watched"
    assert progress_bar(Watched()) == "[########] 100%"
    assert row_progress_marker(Watched()) == "[########] 100%"
    assert watched_state(Partial()) == "in progress"
    assert progress_label(Partial()) == "1m / 10m (11%)"
    assert progress_bar(Partial()) == "[#-------] 11%"
    assert row_progress_marker(Partial()) == "[#-------] 11%"
    assert watched_state(Unwatched()) == "unwatched"
    assert row_progress_marker(Unwatched()) == ""
    assert watched_state(ReplayedWatched()) == "in progress"
    assert progress_bar(ReplayedWatched()) == "[#-------] 5%"
    assert row_progress_marker(ReplayedWatched()) == "[#-------] 5%"


def test_online_metadata_row_progress_does_not_trigger_reload():
    class OnlineServer:
        _baseurl = "https://metadata.provider.plex.tv"

    class OnlineRaw(RawItem):
        _server = OnlineServer()

        @property
        def viewCount(self):
            raise AssertionError("online list rows must not reload watch state")

    assert row_progress_marker(OnlineRaw()) == ""


def test_playable_online_metadata_children_do_not_probe_provider():
    class OnlineServer:
        _baseurl = "https://metadata.provider.plex.tv"

    class OnlinePart:
        _server = OnlineServer()

    class OnlineMovie(RawItem):
        class LocalServer:
            _baseurl = "http://plex"

        _server = LocalServer()

        def items(self):
            raise AssertionError("playable online metadata should not fetch children")

        def iterParts(self):
            return [OnlinePart()]

    service = object.__new__(PlexService)
    media = to_media_item(OnlineMovie())

    assert media.playable
    assert service.children(media) == []


def test_online_metadata_show_child_errors_return_empty_list():
    class OnlineServer:
        _baseurl = "https://metadata.provider.plex.tv"

    class OnlinePart:
        _server = OnlineServer()

    class OnlineShow(RawItem):
        TYPE = "show"

        def iterParts(self):
            return [OnlinePart()]

        def seasons(self):
            raise RuntimeError("provider children endpoint not found")

    service = object.__new__(PlexService)

    assert service.children(to_media_item(OnlineShow())) == []


def test_online_metadata_children_use_key_children_endpoint():
    class OnlineServer:
        _baseurl = "https://metadata.provider.plex.tv"

    class OnlineSeason(RawItem):
        TYPE = "season"
        title = "Season 1"
        key = "/library/metadata/season-1"

    class OnlineShow(RawItem):
        TYPE = "show"
        key = "/library/metadata/show-1"
        _server = OnlineServer()

        def __init__(self):
            self.calls = []

        def fetchItems(self, key, **kwargs):
            self.calls.append((key, kwargs))
            return [OnlineSeason()]

    service = object.__new__(PlexService)
    raw = OnlineShow()

    children = service.children(to_media_item(raw), size=5)

    assert raw.calls == [("/library/metadata/show-1/children", {"maxresults": 5})]
    assert [(child.title, child.kind) for child in children] == [("Season 1", "season")]


def test_online_metadata_children_use_details_key_when_key_is_empty():
    class OnlineServer:
        _baseurl = "https://metadata.provider.plex.tv"

    class OnlineEpisode(RawItem):
        TYPE = "episode"
        title = "Episode 1"

    class OnlineSeason(RawItem):
        TYPE = "season"
        title = "Season 1"
        key = ""
        _details_key = "/library/metadata/season-1?includeBandwidths=1"
        _server = OnlineServer()

        def __init__(self):
            self.calls = []

        def fetchItems(self, key, **kwargs):
            self.calls.append((key, kwargs))
            return [OnlineEpisode()]

    service = object.__new__(PlexService)
    raw = OnlineSeason()

    children = service.children(to_media_item(raw), size=6)

    assert raw.calls == [("/library/metadata/season-1/children", {"maxresults": 6})]
    assert [(child.title, child.kind) for child in children] == [("Episode 1", "episode")]
