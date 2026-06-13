from __future__ import annotations

from plextui.models import LibraryItem, MediaItem
from plextui.plex_service import PlexService, media_details, progress_label, row_progress_marker, watched_state


class RawItem:
    TYPE = "movie"
    title = "Movie"
    ratingKey = "1"

    def getStreamURL(self):
        return "http://plex/movie"


class SecondRawItem(RawItem):
    title = "Second Movie"
    ratingKey = "2"


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

    def iterParts(self):
        return [Part()]


class RawPage(list):
    totalSize = 250


class RawLibrary:
    def __init__(self) -> None:
        self.calls = []

    def all(self, **kwargs):
        self.calls.append(kwargs)
        return RawPage([RawItem()])

    def search(self, query, **kwargs):
        self.calls.append((query, kwargs))
        return RawPage([RawItem()])


class RawLibraryHub:
    def __init__(self) -> None:
        self.calls = []

    def onDeck(self):
        self.calls.append(())
        return [RawItem(), SecondRawItem()]


class RawServer:
    def __init__(self) -> None:
        self.calls = []

    def search(self, query, **kwargs):
        self.calls.append((query, kwargs))
        return [RawItem()]


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


def test_media_details_include_audio_and_subtitle_locations():
    item = MediaItem("Movie", "", "movie", "1", True, DetailedRawItem())

    details = media_details(item)

    assert ("Status", "in progress") in details.metadata
    assert ("Progress", "2m / 10m (20%)") in details.metadata
    assert details.audio == ["Japanese (aac, 2ch, selected)"]
    assert details.subtitles == [
        "English (srt, external, selected)",
        "Signs (vobsub, embedded, forced)",
    ]
    assert details.artwork_path == "/library/metadata/show/thumb"


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
    assert row_progress_marker(Watched()) == "[watched]"
    assert watched_state(Partial()) == "in progress"
    assert progress_label(Partial()) == "1m / 10m (11%)"
    assert row_progress_marker(Partial()) == "[resume 1m]"
    assert watched_state(Unwatched()) == "unwatched"
    assert row_progress_marker(Unwatched()) == ""
