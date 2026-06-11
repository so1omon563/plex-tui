from __future__ import annotations

import asyncio
from unittest.mock import patch

from plextui.app import (
    BrowseState,
    LoadMoreRow,
    PlexTuiApp,
    render_loaded_status,
    should_auto_load_more,
)
from plextui.config import AppConfig
from plextui.models import LibraryItem, MediaItem
from plextui.player import StreamChoice
from plextui.plex_service import MediaPage


class Raw:
    TYPE = "movie"
    title = "Raw"


def test_picker_return_preserves_highlighted_media():
    asyncio.run(run_picker_return_check())


def test_show_media_highlights_first_rebuilt_row():
    asyncio.run(run_show_media_highlight_check())


def test_populate_libraries_highlights_first_rebuilt_row():
    asyncio.run(run_library_highlight_check())


def test_show_browse_state_adds_load_more_row():
    asyncio.run(run_load_more_row_check())


def test_render_loaded_status():
    assert render_loaded_status("Movies", 100, 250, True) == "Movies: 100 of 250 items loaded"
    assert render_loaded_status("Movies", 250, 250, False) == "Movies: 250 items"


def test_load_more_media_appends_next_page():
    asyncio.run(run_load_more_media_check())


def test_load_more_media_can_preserve_selected_row():
    asyncio.run(run_load_more_media_preserve_selection_check())


def test_grid_browse_state_preserves_selected_media():
    asyncio.run(run_grid_browse_state_preserve_selection_check())


def test_grid_selection_scrolls_to_selected_row():
    asyncio.run(run_grid_selection_scroll_check())


def test_search_state_adds_load_more_row():
    asyncio.run(run_search_load_more_row_check())


def test_load_more_media_appends_search_page():
    asyncio.run(run_load_more_search_check())


def test_settings_actions_update_preferences():
    asyncio.run(run_settings_action_check())


def test_help_view_returns_to_media_on_escape():
    asyncio.run(run_help_back_check())


def test_should_auto_load_more_near_end_only():
    library = LibraryItem("Movies", "1", "movie", object())
    items = [
        MediaItem(str(index), "", "movie", str(index), True, Raw())
        for index in range(20)
    ]
    state = BrowseState("Movies", items, library, next_start=20, total=30)

    assert not should_auto_load_more(state, "8", threshold=10)
    assert should_auto_load_more(state, "10", threshold=10)
    assert should_auto_load_more(state, "19", threshold=10)
    assert not should_auto_load_more(BrowseState("Movies", items), "19", threshold=10)


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


async def run_load_more_row_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        library = LibraryItem("Movies", "1", "movie", object())
        items = [
            MediaItem("First", "", "movie", "1", True, Raw()),
            MediaItem("Second", "", "movie", "2", True, Raw()),
        ]
        state = BrowseState("Movies", items, library, next_start=2, total=5)

        app.show_browse_state(state)
        await pilot.pause(0.2)

        rows = list(app.query_one("#media").children)
        assert len(rows) == 3
        assert isinstance(rows[-1], LoadMoreRow)


class FakePagedService:
    def __init__(self, page: MediaPage) -> None:
        self.page = page
        self.calls = []
        self.search_calls = []

    def library_page(self, library: LibraryItem, start: int, size: int) -> MediaPage:
        self.calls.append((library, start, size))
        return self.page

    def search_page(self, query: str, library: LibraryItem | None, start: int, size: int) -> MediaPage:
        self.search_calls.append((query, library, start, size))
        return self.page


async def run_load_more_media_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        library = LibraryItem("Movies", "1", "movie", object())
        first = MediaItem("First", "", "movie", "1", True, Raw())
        second = MediaItem("Second", "", "movie", "2", True, Raw())
        page = MediaPage([second], start=1, total=3)
        service = FakePagedService(page)
        app.service = service
        app.browsing_stack = [BrowseState("Movies", [first], library, next_start=1, total=3)]

        app.load_more_media()
        await pilot.pause(0.5)

        state = app.browsing_stack[-1]
        assert service.calls
        assert [item.title for item in state.items] == ["First", "Second"]
        assert state.next_start == 2
        assert state.has_more


async def run_load_more_media_preserve_selection_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        library = LibraryItem("Movies", "1", "movie", object())
        first = MediaItem("First", "", "movie", "1", True, Raw())
        second = MediaItem("Second", "", "movie", "2", True, Raw())
        third = MediaItem("Third", "", "movie", "3", True, Raw())
        page = MediaPage([third], start=2, total=4)
        app.service = FakePagedService(page)
        app.browsing_stack = [BrowseState("Movies", [first, second], library, next_start=2, total=4)]

        app.load_more_media(selected_key="2")
        await pilot.pause(0.5)

        selected = app.selected_media()
        assert selected is not None
        assert selected.title == "Second"


async def run_grid_browse_state_preserve_selection_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        items = [
            MediaItem("First", "", "movie", "1", True, Raw()),
            MediaItem("Second", "", "movie", "2", True, Raw()),
            MediaItem("Third", "", "movie", "3", True, Raw()),
        ]
        state = BrowseState("Movies", items)

        app.show_browse_state(state, selected_key="2")
        await pilot.pause(0.2)

        grid = app.query_one("#media-grid")
        assert app.query_one("#media-grid-scroll").display
        assert grid.selected_media is not None
        assert grid.selected_media.title == "Second"

        grid.focus()
        await pilot.press("right")
        await pilot.pause(0.2)

        assert grid.selected_media is not None
        assert grid.selected_media.title == "Third"


async def run_grid_selection_scroll_check():
    app = PlexTuiApp()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        items = [
            MediaItem(f"Movie {index}", "", "movie", str(index), True, Raw())
            for index in range(40)
        ]

        app.show_browse_state(BrowseState("Movies", items))
        await pilot.pause(0.2)
        grid = app.query_one("#media-grid")
        grid_scroll = app.query_one("#media-grid-scroll")
        start_scroll = grid_scroll.scroll_y

        grid.set_selected_index(30)
        await pilot.pause(0.2)

        assert grid_scroll.scroll_y > start_scroll


async def run_search_load_more_row_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        library = LibraryItem("Movies", "1", "movie", object())
        items = [
            MediaItem("First", "", "movie", "1", True, Raw()),
            MediaItem("Second", "", "movie", "2", True, Raw()),
        ]
        state = BrowseState(
            "Search: first",
            items,
            library,
            search=True,
            search_query="first",
            next_start=2,
            total=5,
        )

        app.show_browse_state(state)
        await pilot.pause(0.2)

        rows = list(app.query_one("#media").children)
        assert len(rows) == 3
        assert isinstance(rows[-1], LoadMoreRow)


async def run_load_more_search_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        library = LibraryItem("Movies", "1", "movie", object())
        first = MediaItem("First", "", "movie", "1", True, Raw())
        second = MediaItem("Second", "", "movie", "2", True, Raw())
        page = MediaPage([second], start=1, total=3)
        service = FakePagedService(page)
        app.service = service
        app.browsing_stack = [
            BrowseState(
                "Search: first",
                [first],
                library,
                search=True,
                search_query="first",
                next_start=1,
                total=3,
            )
        ]

        app.load_more_media(selected_key="1")
        await pilot.pause(0.5)

        state = app.browsing_stack[-1]
        assert service.search_calls == [("first", library, 1, 100)]
        assert [item.title for item in state.items] == ["First", "Second"]
        assert state.next_start == 2
        assert state.has_more


async def run_settings_action_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig(
            "http://plex",
            "token",
            "client-id",
            preferred_audio_language="jpn",
            preferred_subtitle_language="eng",
            subtitle_mode="preferred",
        )

        with patch("plextui.app.save_config") as save_config:
            app.run_settings_action("clear_audio")
            assert app.config.preferred_audio_language == ""
            app.run_settings_action("subtitle_none")
            assert app.config.subtitle_mode == "none"
            assert app.config.preferred_subtitle_language == ""
            app.run_settings_action("subtitle_auto")
            assert app.config.subtitle_mode == "auto"

        assert save_config.call_count == 3


async def run_help_back_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        items = [
            MediaItem("First", "", "movie", "1", True, Raw()),
            MediaItem("Second", "", "movie", "2", True, Raw()),
        ]
        app.browsing_stack = [BrowseState("Movies", items)]
        app.show_browse_state(app.browsing_stack[-1])
        await pilot.pause(0.2)

        app.action_show_help()
        await pilot.pause(0.2)
        assert app.query_one("#media-title").content == "Help"
        assert "Keyboard reference" in app.query_one("#detail-content").content

        app.action_back_or_clear()
        await pilot.pause(0.2)
        assert app.query_one("#media-title").content == "Movies"
        assert app.query_one("#detail-content").content.splitlines()[0] == "First"
