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
