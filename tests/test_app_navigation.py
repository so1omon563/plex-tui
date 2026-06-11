from __future__ import annotations

import asyncio
from types import SimpleNamespace
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
from plextui.player import PlayerError, StreamChoice
from plextui.plex_service import MediaPage


class Raw:
    TYPE = "movie"
    title = "Raw"


def test_picker_return_preserves_highlighted_media():
    asyncio.run(run_picker_return_check())


def test_show_media_highlights_first_rebuilt_row():
    asyncio.run(run_show_media_highlight_check())


def test_focus_actions_mark_active_pane():
    asyncio.run(run_focus_pane_check())


def test_tab_focus_updates_active_pane_marker():
    asyncio.run(run_tab_focus_pane_check())


def test_populate_libraries_highlights_first_rebuilt_row():
    asyncio.run(run_library_highlight_check())


def test_show_browse_state_adds_load_more_row():
    asyncio.run(run_load_more_row_check())


def test_render_loaded_status():
    assert render_loaded_status("Movies", 100, 250, True) == "Movies: 100 of 250 items loaded"
    assert render_loaded_status("Movies", 250, 250, False) == "Movies: 250 items"


def test_load_more_media_appends_next_page():
    asyncio.run(run_load_more_media_check())


def test_initial_library_uses_configured_page_size():
    asyncio.run(run_initial_library_page_size_check())


def test_initial_search_uses_configured_page_size():
    asyncio.run(run_initial_search_page_size_check())


def test_load_more_media_can_preserve_selected_row():
    asyncio.run(run_load_more_media_preserve_selection_check())


def test_grid_browse_state_preserves_selected_media():
    asyncio.run(run_grid_browse_state_preserve_selection_check())


def test_grid_selection_pages_visible_cards():
    asyncio.run(run_grid_selection_page_check())


def test_grid_prefetch_schedules_once_per_visible_page():
    asyncio.run(run_grid_prefetch_schedule_check())


def test_grid_detail_refresh_waits_for_idle_selection():
    asyncio.run(run_grid_detail_refresh_idle_check())


def test_list_detail_refresh_waits_for_short_idle_selection():
    asyncio.run(run_list_detail_refresh_idle_check())


def test_search_state_adds_load_more_row():
    asyncio.run(run_search_load_more_row_check())


def test_load_more_media_appends_search_page():
    asyncio.run(run_load_more_search_check())


def test_settings_actions_update_preferences():
    asyncio.run(run_settings_action_check())


def test_settings_recent_debug_log_action_shows_tail(tmp_path):
    asyncio.run(run_settings_recent_debug_log_check(tmp_path))


def test_playback_error_shows_recent_debug_log(tmp_path):
    asyncio.run(run_playback_error_check(tmp_path))


def test_quick_preference_actions_update_config():
    asyncio.run(run_quick_preference_action_check())


def test_mpv_window_size_input_updates_preferences():
    asyncio.run(run_mpv_window_size_input_check())


def test_numeric_settings_input_updates_preferences():
    asyncio.run(run_numeric_settings_input_check())


def test_grid_density_setting_stays_in_settings_view():
    asyncio.run(run_grid_density_settings_view_check())


def test_toggle_media_view_refocuses_visible_browser():
    asyncio.run(run_toggle_media_view_focus_check())


def test_settings_highlight_defaults_and_preserves_changed_row():
    asyncio.run(run_settings_highlight_check())


def test_help_view_returns_to_media_on_escape():
    asyncio.run(run_help_back_check())


def test_completed_player_updates_status():
    asyncio.run(run_completed_player_status_check())


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

        assert app.query_one("#media-title").content.removeprefix("[FOCUS] ") == "Movies"
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


async def run_focus_pane_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.populate_libraries([LibraryItem("Movies", "1", "movie", object())])
        app.show_media("Movies", [MediaItem("First", "", "movie", "1", True, Raw())])
        await pilot.pause(0.2)

        app.action_focus_libraries()
        await pilot.pause(0.1)
        assert app.query_one("#sidebar").has_class("focused-pane")
        assert not app.query_one("#main").has_class("focused-pane")
        assert app.query_one("#libraries-title").content == "[FOCUS] Libraries"
        assert not app.query_one("#media-title").content.startswith("[FOCUS]")

        app.action_focus_media()
        await pilot.pause(0.1)
        assert app.query_one("#main").has_class("focused-pane")
        assert not app.query_one("#sidebar").has_class("focused-pane")
        assert not app.query_one("#details").has_class("focused-pane")
        assert app.query_one("#media-title").content.startswith("[FOCUS]")
        assert app.query_one("#libraries-title").content == "Libraries"

        app.action_focus_details()
        await pilot.pause(0.1)
        assert app.query_one("#details").has_class("focused-pane")
        assert app.query_one("#details-title").content == "[FOCUS] Details"
        assert not app.query_one("#main").has_class("focused-pane")


async def run_tab_focus_pane_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.populate_libraries([LibraryItem("Movies", "1", "movie", object())])
        app.show_media("Movies", [MediaItem("First", "", "movie", "1", True, Raw())])
        await pilot.pause(0.2)

        app.action_focus_libraries()
        await pilot.pause(0.1)
        await pilot.press("tab")
        await pilot.pause(0.2)

        assert app.query_one("#main").has_class("focused-pane")
        assert app.query_one("#media-title").content.startswith("[FOCUS]")
        assert not app.query_one("#libraries-title").content.startswith("[FOCUS]")

        await pilot.press("tab")
        await pilot.pause(0.2)

        assert app.query_one("#details").has_class("focused-pane")
        assert app.query_one("#details-title").content == "[FOCUS] Details"
        assert not app.query_one("#main").has_class("focused-pane")
        assert not app.query_one("#media-title").content.startswith("[FOCUS]")

        await pilot.press("shift+tab")
        await pilot.pause(0.2)

        assert app.query_one("#main").has_class("focused-pane")
        assert app.query_one("#media-title").content.startswith("[FOCUS]")
        assert not app.query_one("#details").has_class("focused-pane")


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


async def run_initial_library_page_size_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        library = LibraryItem("Movies", "1", "movie", object())
        page = MediaPage([MediaItem("First", "", "movie", "1", True, Raw())], start=0, total=1)
        service = FakePagedService(page)
        app.config = AppConfig("http://plex", "token", "client-id", page_size=45)
        app.service = service

        app.open_library(library)
        await pilot.pause(0.5)

        assert service.calls == [(library, 0, 45)]


async def run_initial_search_page_size_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        library = LibraryItem("Movies", "1", "movie", object())
        page = MediaPage([MediaItem("First", "", "movie", "1", True, Raw())], start=0, total=1)
        service = FakePagedService(page)
        app.config = AppConfig("http://plex", "token", "client-id", page_size=55)
        app.service = service
        app.selected_library = library

        app.run_search("first")
        await pilot.pause(0.5)

        assert service.search_calls == [("first", library, 0, 55)]


async def run_load_more_media_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", page_size=50)
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
        assert service.calls == [(library, 1, 50)]
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


async def run_grid_selection_page_check():
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
        first_page = [item.key for item in grid.visible_page_items()]

        grid.set_selected_index(30)
        await pilot.pause(0.2)

        assert first_page[0] == "0"
        next_page = [item.key for item in grid.visible_page_items()]
        assert next_page != first_page
        assert "30" in next_page


async def run_grid_prefetch_schedule_check():
    app = PlexTuiApp()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        items = [
            MediaItem(f"Movie {index}", "", "movie", str(index), True, Raw(), artwork_path=f"/thumb/{index}")
            for index in range(20)
        ]
        scheduled = []

        def capture_prefetch(items, page_key, page_label, delay=0.0):
            scheduled.append((tuple(item.key for item in items), page_key, page_label, delay))
            app.prefetched_grid_pages.add(page_key)
            app.active_grid_prefetch_pages.discard(page_key)

        app.prefetch_grid_items = capture_prefetch
        app.show_browse_state(BrowseState("Movies", items))
        await pilot.pause(0.2)

        grid = app.query_one("#media-grid")
        first_page = tuple(item.key for item in grid.visible_page_items())
        assert scheduled[0][0] == first_page
        assert scheduled[0][1] == first_page
        assert scheduled[0][2] == "current"
        initial_schedule_count = len(scheduled)

        grid.set_selected_index(1)
        app.schedule_grid_prefetch(grid)
        await pilot.pause(0.2)
        assert len(scheduled) == initial_schedule_count

        grid.set_selected_index(grid.page_size)
        app.schedule_grid_prefetch(grid)
        await pilot.pause(0.2)
        assert len(scheduled) > initial_schedule_count


async def run_grid_detail_refresh_idle_check():
    app = PlexTuiApp()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        items = [
            MediaItem(f"Movie {index}", "", "movie", str(index), True, Raw())
            for index in range(3)
        ]
        refreshed = []

        def capture_refresh(item, token):
            refreshed.append(item.title)

        app.refresh_media_details = capture_refresh
        app.show_browse_state(BrowseState("Movies", items))
        await pilot.pause(0.2)

        app.show_media_details(items[1])
        await pilot.pause(0.2)
        assert refreshed == []

        app.show_media_details(items[2])
        await pilot.pause(0.8)
        assert refreshed == ["Movie 2"]


async def run_list_detail_refresh_idle_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="list")
        items = [
            MediaItem(f"Movie {index}", "", "movie", str(index), True, Raw())
            for index in range(3)
        ]
        refreshed = []

        def capture_refresh(item, token):
            refreshed.append(item.title)

        app.refresh_media_details = capture_refresh
        app.show_browse_state(BrowseState("Movies", items))
        await pilot.pause(0.1)

        app.show_media_details(items[1])
        await pilot.pause(0.1)
        assert refreshed == []

        app.show_media_details(items[2])
        await pilot.pause(0.3)
        assert refreshed == ["Movie 2"]


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
        app.config = AppConfig("http://plex", "token", "client-id", page_size=75)
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
        assert service.search_calls == [("first", library, 1, 75)]
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
            assert app.config.preferred_audio_language == "jpn"
            app.run_settings_action("clear_audio")
            assert app.config.preferred_audio_language == ""
            app.run_settings_action("subtitle_none")
            assert app.config.subtitle_mode == "none"
            assert app.config.preferred_subtitle_language == ""
            app.run_settings_action("subtitle_auto")
            assert app.config.subtitle_mode == "auto"
            app.run_settings_action("increase_page_size")
            assert app.config.page_size == 50
            app.run_settings_action("decrease_page_size")
            assert app.config.page_size == 40
            app.run_settings_action("reset_page_size")
            assert app.config.page_size == 40
            app.run_settings_action("increase_auto_load_threshold")
            assert app.config.auto_load_threshold == 15
            app.run_settings_action("decrease_auto_load_threshold")
            assert app.config.auto_load_threshold == 10
            app.run_settings_action("reset_auto_load_threshold")
            assert app.config.auto_load_threshold == 10
            app.run_settings_action("reset_mpv_window_size")
            assert app.config.mpv_window_size == ""
            app.run_settings_action("cycle_grid_density")
            assert app.config.grid_density == "large"

        assert save_config.call_count == 11


async def run_settings_recent_debug_log_check(tmp_path):
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        log = tmp_path / "debug.log"
        log.write_text("first\nsecond\nthird\n", encoding="utf-8")

        with patch("plextui.app.debug_log_path", return_value=log):
            app.action_show_settings()
            await pilot.pause(0.2)
            app.run_settings_action("show_recent_debug_log")
        await pilot.pause(0.2)

        details = app.query_one("#detail-content").content
        assert "Recent Debug Log" in details
        assert f"Path: {log}" in details
        assert "first" in details
        assert "third" in details


async def run_playback_error_check(tmp_path):
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.show_media("Movies", [MediaItem("Broken Movie", "", "movie", "1", True, Raw())])
        await pilot.pause(0.2)
        log = tmp_path / "debug.log"
        log.write_text("launching mpv\nplayback error: mpv missing\n", encoding="utf-8")

        with (
            patch("plextui.app.debug_log_path", return_value=log),
            patch("plextui.app.play_with_mpv", side_effect=PlayerError("mpv missing")),
        ):
            app.action_play_selected()
        await pilot.pause(0.2)

        assert app.query_one("#media-title").content.removeprefix("[FOCUS] ") == "Playback Error"
        details = app.query_one("#detail-content").content
        assert "mpv missing" in details
        assert f"Debug log: {log}" in details
        assert "playback error: mpv missing" in details


async def run_quick_preference_action_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig(
            "http://plex",
            "token",
            "client-id",
            preferred_audio_language="jpn",
            subtitle_mode="auto",
        )

        with patch("plextui.app.save_config") as save_config:
            app.action_clear_audio_preference()
            assert app.config.preferred_audio_language == ""
            app.action_cycle_subtitle_mode()
            assert app.config.subtitle_mode == "none"
            app.action_cycle_subtitle_mode()
            assert app.config.subtitle_mode == "auto"
            app.action_cycle_mpv_window_size()
            assert app.config.mpv_window_size == "1280x720"

        assert save_config.call_count == 4


async def run_mpv_window_size_input_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", mpv_window_size="1280x720")

        with patch("plextui.app.save_config") as save_config:
            app.save_mpv_window_size_input("80%x80%")
            assert app.config.mpv_window_size == "80%x80%"
            app.save_mpv_window_size_input("bad")
            assert app.config.mpv_window_size == "80%x80%"
            app.save_mpv_window_size_input("")
            assert app.config.mpv_window_size == ""

        assert save_config.call_count == 2


async def run_numeric_settings_input_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", page_size=40, auto_load_threshold=10)

        with patch("plextui.app.save_config") as save_config:
            app.save_numeric_setting_input("page_size", "Page size", "120", 25, 500, 40)
            assert app.config.page_size == 120
            app.save_numeric_setting_input("page_size", "Page size", "bad", 25, 500, 40)
            assert app.config.page_size == 120
            app.save_numeric_setting_input("page_size", "Page size", "1000", 25, 500, 40)
            assert app.config.page_size == 120
            app.save_numeric_setting_input("page_size", "Page size", "", 25, 500, 40)
            assert app.config.page_size == 40
            app.save_numeric_setting_input("auto_load_threshold", "Auto-load threshold", "30", 1, 100, 10)
            assert app.config.auto_load_threshold == 30
            app.save_numeric_setting_input("auto_load_threshold", "Auto-load threshold", "", 1, 100, 10)
            assert app.config.auto_load_threshold == 10

        assert save_config.call_count == 4


async def run_grid_density_settings_view_check():
    app = PlexTuiApp()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        app.browsing_stack = [
            BrowseState(
                "Movies",
                [MediaItem(f"Movie {index}", "2024", "movie", str(index), True, Raw()) for index in range(8)],
            )
        ]
        app.show_browse_state(app.browsing_stack[-1])
        app.action_show_settings()

        with patch("plextui.app.save_config"):
            app.run_settings_action("cycle_grid_density")

        await pilot.pause(0.2)
        assert app.settings_visible
        assert app.query_one("#media").display
        assert not app.query_one("#media-grid-scroll").display
        assert app.config.grid_density == "large"


async def run_toggle_media_view_focus_check():
    app = PlexTuiApp()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        app.browsing_stack = [
            BrowseState(
                "Movies",
                [MediaItem(f"Movie {index}", "2024", "movie", str(index), True, Raw()) for index in range(8)],
            )
        ]
        app.show_browse_state(app.browsing_stack[-1])
        app.focus_media_browser()
        await pilot.pause(0.2)
        assert app.query_one("#media-grid-scroll").display

        with patch("plextui.app.save_config"):
            app.action_toggle_media_view()
        await pilot.pause(0.2)
        assert app.query_one("#media").display
        assert app.query_one("#media").has_focus
        assert app.query_one("#main").has_class("focused-pane")

        with patch("plextui.app.save_config"):
            app.action_toggle_media_view()
        await pilot.pause(0.2)
        assert app.query_one("#media-grid-scroll").display
        assert app.query_one("#media-grid").has_focus
        assert app.query_one("#main").has_class("focused-pane")


async def run_settings_highlight_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")

        app.action_show_settings()
        await pilot.pause(0.2)

        media = app.query_one("#media")
        row = media.highlighted_child
        assert row is not None
        assert row.has_class("active-row")
        assert getattr(row, "label_text") == "[ Account ]"
        assert "Settings Section" in app.query_one("#detail-content").content

        with patch("plextui.app.save_config"):
            app.run_settings_action("cycle_grid_density")
        await pilot.pause(0.2)

        row = media.highlighted_child
        assert row is not None
        assert row.has_class("active-row")
        assert getattr(row, "action") == "cycle_grid_density"
        details = app.query_one("#detail-content").content
        assert "Grid Density" in details
        assert "Type: cycle" in details
        assert "Current grid density: Large" in details


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
        assert app.query_one("#media-title").content.removeprefix("[FOCUS] ") == "Help"
        assert "Keyboard reference" in app.query_one("#detail-content").content

        app.action_back_or_clear()
        await pilot.pause(0.2)
        assert app.query_one("#media-title").content.removeprefix("[FOCUS] ") == "Movies"
        assert app.query_one("#detail-content").content.splitlines()[0] == "First"


async def run_completed_player_status_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        item = MediaItem("Movie", "", "movie", "1", True, Raw())
        app.show_media("Movies", [item])
        await pilot.pause(0.2)
        refreshed = []
        app.show_media_details = refreshed.append
        app.player = SimpleNamespace(title="Movie", process=SimpleNamespace(poll=lambda: 0))

        app.check_player_status()
        await pilot.pause(0.1)

        assert app.player is None
        assert app.query_one("#status").content == "Playback ended: Movie"
        assert refreshed == [item]
