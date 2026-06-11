from __future__ import annotations

import asyncio
from unittest.mock import patch

from plextui.app import BrowseState, PlexTuiApp
from plextui.config import AppConfig
from plextui.models import LibraryItem, MediaItem
from plextui.player import StreamChoice


class Raw:
    TYPE = "movie"
    title = "Raw"


def test_picker_return_preserves_highlighted_media():
    asyncio.run(run_picker_return_check())


def test_show_media_highlights_first_rebuilt_row():
    asyncio.run(run_show_media_highlight_check())


def test_populate_libraries_highlights_first_rebuilt_row():
    asyncio.run(run_library_highlight_check())


async def run_picker_return_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        items = [
            MediaItem("First", "", "movie", "1", True, Raw()),
            MediaItem("Second", "", "movie", "2", True, Raw()),
        ]
        app.browsing_stack = [BrowseState("Movies", items)]
        app.config = AppConfig("http://plex", "token", "client-id")
        app.picker_media_key = "2"
        app.picker_visible = True

        with patch("plextui.app.save_config"):
            app.choose_stream(StreamChoice(0, "None (disable subtitles)"), "subtitle")
        await pilot.pause(0.2)

        assert app.query_one("#media-title").content == "Movies"
        assert app.query_one("#detail-content").content.splitlines()[0] == "Second"


async def run_show_media_highlight_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        items = [
            MediaItem("First", "", "movie", "1", True, Raw()),
            MediaItem("Second", "", "movie", "2", True, Raw()),
        ]

        app.show_media("Movies", items)
        media = app.query_one("#media")
        media.focus()
        await pilot.pause(0.2)

        row = media.highlighted_child
        assert row is not None
        assert row.has_class("active-row")
        assert row.media.title == "First"


async def run_library_highlight_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        libraries = [
            LibraryItem("Movies", "1", "movie", object()),
            LibraryItem("TV", "2", "show", object()),
        ]

        app.populate_libraries(libraries)
        libraries_view = app.query_one("#libraries")
        libraries_view.focus()
        await pilot.pause(0.2)

        row = libraries_view.highlighted_child
        assert row is not None
        assert row.has_class("active-row")
        assert row.library.title == "Movies"
