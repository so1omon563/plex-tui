from __future__ import annotations

from plextui.models import LibraryItem
from plextui.plex_service import PlexService


class RawItem:
    TYPE = "movie"
    title = "Movie"
    ratingKey = "1"

    def getStreamURL(self):
        return "http://plex/movie"


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
