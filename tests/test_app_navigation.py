from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import plextui.app as app_module
from plextui.app import (
    AvailabilityRow,
    BrowseState,
    ContinueWatchingRow,
    DiscoverRow,
    EmptyStateRow,
    LibraryRow,
    LibraryMenuRow,
    LoadMoreRow,
    MediaGrid,
    OnPlexLiveRow,
    OnPlexRow,
    PlexServicesRow,
    PlexTuiApp,
    PlaylistsRow,
    PlaylistCreateRow,
    PlaylistTargetRow,
    ProfileRow,
    artwork_fetch_pixel_size,
    card_artwork_fetch_size,
    grid_artwork_cache_key,
    grid_page_key,
    render_loaded_status,
    should_auto_load_more,
)
from textual.widgets import ListView
from plextui.auth import ProfileChoice
from plextui.config import AppConfig
from plextui.models import LibraryItem, MediaItem
from plextui.player import PlayerError, StreamChoice
from plextui.plex_service import MediaPage

STARTUP_LOAD_SERVER = PlexTuiApp.load_server


class Raw:
    TYPE = "movie"
    title = "Raw"


class DiscoverRaw:
    TYPE = "movie"
    title = "Discover Raw"

    def streamingServices(self):
        return [SimpleNamespace(title="Plex", offerType="free", url="https://watch.plex.tv/movie")]


class MultiProviderDiscoverRaw:
    TYPE = "movie"
    title = "Multi Provider Discover Raw"

    def streamingServices(self):
        return [
            SimpleNamespace(title="Plex", offerType="free", url="https://watch.plex.tv/movie"),
            SimpleNamespace(title="Prime", offerType="rent", url="https://example.com/prime"),
        ]


class NoAvailabilityDiscoverRaw:
    TYPE = "movie"
    title = "No Availability Discover Raw"

    def streamingServices(self):
        return []


@pytest.fixture(autouse=True)
def disable_startup_server_load(monkeypatch):
    monkeypatch.setattr(PlexTuiApp, "load_server", lambda self: None)


async def wait_for_selected_title(app: PlexTuiApp, pilot: object, expected: str, attempts: int = 20) -> MediaItem | None:
    selected = app.selected_media()
    for _ in range(attempts):
        if selected is not None and selected.title == expected:
            return selected
        await pilot.pause(0.1)
        selected = app.selected_media()
    return selected


async def wait_for_status(app: PlexTuiApp, pilot: object, expected: str, attempts: int = 20) -> str:
    status = str(app.query_one("#status").content)
    for _ in range(attempts):
        if status == expected:
            return status
        await pilot.pause(0.1)
        status = str(app.query_one("#status").content)
    return status


async def wait_for_browse_titles(app: PlexTuiApp, pilot: object, expected: list[str], attempts: int = 20) -> list[str]:
    titles = [item.title for item in app.browsing_stack[-1].items] if app.browsing_stack else []
    for _ in range(attempts):
        if titles == expected:
            return titles
        await pilot.pause(0.1)
        titles = [item.title for item in app.browsing_stack[-1].items] if app.browsing_stack else []
    return titles


async def wait_for_availability_rows(app: PlexTuiApp, pilot: object, attempts: int = 20) -> list[AvailabilityRow]:
    rows = [row for row in app.query_one("#media").children if isinstance(row, AvailabilityRow)]
    for _ in range(attempts):
        if app.picker_visible and rows:
            return rows
        await pilot.pause(0.1)
        rows = [row for row in app.query_one("#media").children if isinstance(row, AvailabilityRow)]
    return rows


async def wait_for_playlist_rows(app: PlexTuiApp, pilot: object, attempts: int = 20) -> list[object]:
    rows = list(app.query_one("#media").children)
    for _ in range(attempts):
        if any(isinstance(row, PlaylistCreateRow) for row in rows):
            return rows
        await pilot.pause(0.1)
        rows = list(app.query_one("#media").children)
    return rows


async def wait_for_playlist_target_rows(app: PlexTuiApp, pilot: object, attempts: int = 80) -> list[object]:
    rows = list(app.query_one("#media").children)
    for _ in range(attempts):
        if any(isinstance(row, PlaylistTargetRow) for row in rows):
            return rows
        await pilot.pause(0.1)
        rows = list(app.query_one("#media").children)
    raise AssertionError(f"playlist target rows did not appear: {rows!r}")


async def wait_for_calls(calls: list[object], pilot: object, attempts: int = 20) -> list[object]:
    for _ in range(attempts):
        if calls:
            return calls
        await pilot.pause(0.1)
    return calls


async def wait_for_playlist_result(
    app: PlexTuiApp,
    pilot: object,
    calls: list[object],
    *,
    expected_calls: list[object],
    expected_status: str,
    attempts: int = 180,
) -> tuple[list[object], str]:
    # Worker-backed playlist actions can complete their service call and UI
    # cleanup on different event-loop ticks, especially on hosted Python 3.13.
    status = str(app.query_one("#status").content)
    for _ in range(attempts):
        current_calls = list(calls)
        status = str(app.query_one("#status").content)
        if current_calls == expected_calls and status == expected_status and not app.picker_visible:
            return current_calls, status
        await pilot.pause(0.1)
    raise AssertionError(
        "Timed out waiting for playlist worker result: "
        f"expected_calls={expected_calls!r}, calls={list(calls)!r}, "
        f"expected_status={expected_status!r}, status={status!r}, "
        f"picker_visible={app.picker_visible!r}, input_mode={app.input_mode!r}"
    )


async def wait_for_watched_update(
    app: PlexTuiApp,
    pilot: object,
    raw: object,
    *,
    watched: bool,
    expected_status: str,
    attempts: int = 180,
) -> tuple[object, MediaItem, str]:
    row = app.query_one("#media").highlighted_child
    selected = app.selected_media()
    status = str(app.query_one("#status").content)
    watched_calls = 0
    unwatched_calls = 0
    selected_watched = False
    label = ""
    for _ in range(attempts):
        watched_calls = getattr(raw, "mark_watched_calls", 0)
        unwatched_calls = getattr(raw, "mark_unwatched_calls", 0)
        selected_watched = bool(getattr(getattr(selected, "raw", None), "viewCount", 0))
        label = getattr(row, "label_text", "")
        if (
            status == expected_status
            and selected is not None
            and selected_watched is watched
            and ("[########] 100%" in label) is watched
            and ((watched and watched_calls == 1) or (not watched and unwatched_calls == 1))
        ):
            return row, selected, status
        await pilot.pause(0.1)
        row = app.query_one("#media").highlighted_child
        selected = app.selected_media()
        status = str(app.query_one("#status").content)
    raise AssertionError(
        "Timed out waiting for watched-state update: "
        f"expected_status={expected_status!r}, status={status!r}, "
        f"expected_watched={watched!r}, selected_watched={selected_watched!r}, "
        f"label={label!r}, mark_watched_calls={watched_calls}, "
        f"mark_unwatched_calls={unwatched_calls}, selected={selected!r}"
    )


def test_picker_return_preserves_highlighted_media():
    asyncio.run(run_picker_return_check())


def test_show_media_highlights_first_rebuilt_row():
    asyncio.run(run_show_media_highlight_check())


def test_focus_actions_mark_active_pane():
    asyncio.run(run_focus_pane_check())


def test_left_right_respect_focused_pane():
    asyncio.run(run_left_right_focus_ownership_check())


def test_tab_focus_updates_active_pane_marker():
    asyncio.run(run_tab_focus_pane_check())


def test_populate_libraries_highlights_first_rebuilt_row():
    asyncio.run(run_library_highlight_check())


def test_populate_libraries_adds_continue_watching_entrypoint():
    asyncio.run(run_continue_watching_entrypoint_check())


def test_startup_opens_continue_watching_by_default(monkeypatch):
    asyncio.run(run_startup_continue_watching_default_check(monkeypatch))


def test_playlists_sidebar_entrypoint_opens_playlists():
    asyncio.run(run_playlists_entrypoint_check())


def test_discover_sidebar_entrypoint_searches_and_opens_first_availability(monkeypatch):
    asyncio.run(run_discover_entrypoint_check(monkeypatch))


def test_discover_result_with_multiple_providers_opens_provider_picker(monkeypatch):
    asyncio.run(run_discover_provider_picker_check(monkeypatch))


def test_discover_result_without_availability_does_not_fetch_children(monkeypatch):
    asyncio.run(run_discover_without_availability_check(monkeypatch))


def test_escape_cancels_slow_discover_search():
    asyncio.run(run_escape_cancels_slow_discover_search_check())


def test_discover_alternate_action_opens_on_plex_vod():
    asyncio.run(run_discover_vod_entrypoint_check())


def test_on_plex_live_entrypoint_opens_hosted_channels():
    asyncio.run(run_on_plex_live_entrypoint_check())


def test_on_plex_live_channel_enter_opens_guide():
    asyncio.run(run_on_plex_live_channel_guide_check())


def test_on_plex_live_guide_uses_schedule_list_view():
    asyncio.run(run_on_plex_live_guide_list_view_check())


def test_unavailable_on_plex_live_channel_shows_clean_error():
    asyncio.run(run_unavailable_on_plex_live_channel_check())


def test_populate_libraries_can_highlight_selected_library():
    asyncio.run(run_selected_library_highlight_check())


def test_open_library_shows_browse_modes():
    asyncio.run(run_library_menu_check())


def test_sidebar_library_selection_shows_browse_modes():
    asyncio.run(run_sidebar_library_selection_opens_default_library_check())


def test_space_on_sidebar_library_shows_browse_modes():
    asyncio.run(run_sidebar_library_space_menu_check())


def test_sidebar_library_selection_can_default_to_browse_modes():
    asyncio.run(run_sidebar_library_selection_menu_default_check())


def test_back_from_library_entry_returns_to_browse_modes():
    asyncio.run(run_library_entry_back_to_menu_check())


def test_library_submenu_keyboard_flow_with_fake_service():
    asyncio.run(run_library_submenu_keyboard_flow_check())


def test_show_browse_state_adds_load_more_row():
    asyncio.run(run_load_more_row_check())


def test_show_live_tv_guide_adds_load_more_row():
    asyncio.run(run_live_tv_guide_load_more_row_check())


def test_show_browse_state_uses_empty_state_row():
    asyncio.run(run_empty_browse_state_check())


def test_render_loaded_status():
    class PartialRaw:
        viewOffset = 300000
        duration = 600000

    assert render_loaded_status("Movies", 100, 250, True) == "Movies: 100 of 250 items loaded"
    assert render_loaded_status("Movies", 250, 250, False) == "Movies: 250 items"
    items = [MediaItem("Partial", "", "movie", "1", True, PartialRaw())]
    assert render_loaded_status("Movies", 1, 250, True, items) == (
        "Movies: 1 of 250 items loaded / 1 in-progress item"
    )


def test_load_more_media_appends_next_page():
    asyncio.run(run_load_more_media_check())


def test_load_more_media_appends_continue_watching_page():
    asyncio.run(run_load_more_continue_watching_check())


def test_load_more_media_ignores_replaced_browse_state():
    asyncio.run(run_load_more_ignores_replaced_browse_state_check())


def test_load_more_media_appends_library_submenu_page():
    asyncio.run(run_load_more_library_submenu_check())


def test_initial_library_uses_configured_page_size():
    asyncio.run(run_initial_library_page_size_check())


def test_initial_search_uses_configured_page_size():
    asyncio.run(run_initial_search_page_size_check())


def test_current_view_search_uses_fuzzy_loaded_items():
    app = PlexTuiApp()
    library = LibraryItem("Movies", "1", "movie", object())
    page = MediaPage([], start=0, total=0)
    service = FakePagedService(page)
    shown_states = []
    statuses = []
    app.config = AppConfig("http://plex", "token", "client-id")
    app.service = service
    app.selected_library = library
    app.browsing_stack = [
        BrowseState(
            "Movies",
            [
                MediaItem("Blade Runner", "1982", "movie", "1", True, Raw()),
                MediaItem("Interstellar", "2014", "movie", "2", True, Raw()),
                MediaItem("The Matrix", "1999", "movie", "3", True, Raw()),
            ],
            library,
            next_start=3,
            total=3,
        )
    ]
    app.call_from_thread = lambda callback, *args: callback(*args)
    app.post_message = lambda message: None
    app.show_loading_state = lambda *args: None
    app.show_browse_state = shown_states.append
    app.focus_media_browser = lambda: None
    app.set_status = statuses.append

    PlexTuiApp.run_search.__wrapped__(app, "interstelar")

    assert service.search_calls == []
    assert app.browsing_stack[-1].title == "Fuzzy search: interstelar"
    assert [item.title for item in app.browsing_stack[-1].items] == ["Interstellar"]
    assert shown_states == [app.browsing_stack[-1]]
    assert statuses == ["Fuzzy search: interstelar: 1 matches from 3 loaded items"]


def test_current_library_search_queries_plex_when_library_is_not_fully_loaded():
    app = PlexTuiApp()
    library = LibraryItem("TV Shows", "2", "show", object())
    gantz = MediaItem("Gantz", "TV Show", "gantz", "show-1", False, Raw())
    service = FakePagedService(MediaPage([gantz], start=0, total=1))
    shown_states = []
    statuses = []
    app.config = AppConfig("http://plex", "token", "client-id")
    app.service = service
    app.selected_library = library
    app.browsing_stack = [
        BrowseState(
            "TV Shows",
            [
                MediaItem("Attack on Titan", "", "show", "1", False, Raw()),
                MediaItem("Berserk", "", "show", "2", False, Raw()),
            ],
            library,
            next_start=2,
            total=100,
        )
    ]
    app.call_from_thread = lambda callback, *args: callback(*args)
    app.post_message = lambda message: None
    app.show_loading_state = lambda *args: None
    app.show_browse_state = shown_states.append
    app.focus_media_browser = lambda: None
    app.set_status = statuses.append

    PlexTuiApp.run_search.__wrapped__(app, "gantz")

    assert service.search_calls == [("gantz", library, 0, 40)]
    assert app.browsing_stack[-1].title == "Search: gantz"
    assert [item.title for item in app.browsing_stack[-1].items] == ["Gantz"]
    assert shown_states == [app.browsing_stack[-1]]
    assert statuses == ["Search: gantz: 1 items"]


def test_live_current_library_search_queries_plex_when_library_is_not_fully_loaded():
    app = PlexTuiApp()
    library = LibraryItem("TV Shows", "2", "show", object())
    gantz = MediaItem("Gantz", "TV Show", "gantz", "show-1", False, Raw())
    service = FakePagedService(MediaPage([gantz], start=0, total=1))
    shown_states = []
    statuses = []
    app.config = AppConfig("http://plex", "token", "client-id")
    app.service = service
    app.input_mode = "search"
    app.search_global = False
    app.search_return_state = None
    app.search_token = 0
    app.selected_library = library
    app.browsing_stack = [
        BrowseState(
            "TV Shows",
            [
                MediaItem("Attack on Titan", "", "show", "1", False, Raw()),
                MediaItem("Berserk", "", "show", "2", False, Raw()),
            ],
            library,
            next_start=2,
            total=100,
        )
    ]
    app.call_from_thread = lambda callback, *args: callback(*args)
    app.post_message = lambda message: None
    app.show_loading_state = lambda *args: None
    app.show_browse_state = shown_states.append
    app.focus_media_browser = lambda: None
    app.set_status = statuses.append
    app.run_search = lambda query, global_search=False, token=0, live=False: PlexTuiApp.run_search.__wrapped__(
        app,
        query,
        global_search,
        token,
        live,
    )
    search = SimpleNamespace(id="search")

    app.on_input_changed(SimpleNamespace(input=search, value="gantz"))
    app.on_input_changed(SimpleNamespace(input=search, value=""))

    assert service.search_calls == [("gantz", library, 0, 40)]
    assert shown_states[0].title == "Search: gantz"
    assert [item.title for item in shown_states[0].items] == ["Gantz"]
    assert shown_states[-1].title == "TV Shows"
    assert statuses[-1] == "TV Shows: 2 of 100 items loaded"


def test_live_current_library_search_does_not_focus_media_browser():
    app = PlexTuiApp()
    library = LibraryItem("TV Shows", "2", "show", object())
    gantz = MediaItem("Gantz", "TV Show", "gantz", "show-1", False, Raw())
    service = FakePagedService(MediaPage([gantz], start=0, total=1))
    shown_states = []
    focus_calls = []
    app.config = AppConfig("http://plex", "token", "client-id")
    app.service = service
    app.selected_library = library
    app.search_token = 1
    app.browsing_stack = [
        BrowseState(
            "TV Shows",
            [
                MediaItem("Attack on Titan", "", "show", "1", False, Raw()),
                MediaItem("Berserk", "", "show", "2", False, Raw()),
            ],
            library,
            next_start=2,
            total=100,
        )
    ]
    app.call_from_thread = lambda callback, *args: callback(*args)
    app.post_message = lambda message: None
    app.show_loading_state = lambda *args: None
    app.show_browse_state = shown_states.append
    app.focus_media_browser = lambda: focus_calls.append("media")
    app.set_status = lambda *_args: None

    PlexTuiApp.run_search.__wrapped__(app, "gantz", False, token=1, live=True)

    assert service.search_calls == [("gantz", library, 0, 40)]
    assert shown_states[-1].title == "Search: gantz"
    assert focus_calls == []


def test_current_view_search_updates_results_while_typing():
    app = PlexTuiApp()
    library = LibraryItem("Movies", "1", "movie", object())
    shown_states = []
    statuses = []
    app.config = AppConfig("http://plex", "token", "client-id")
    app.input_mode = "search"
    app.search_global = False
    app.browsing_stack = [
        BrowseState(
            "Movies",
            [
                MediaItem("Blade Runner", "1982", "movie", "1", True, Raw()),
                MediaItem("Interstellar", "2014", "movie", "2", True, Raw()),
                MediaItem("The Matrix", "1999", "movie", "3", True, Raw()),
            ],
            library,
            next_start=3,
            total=3,
        )
    ]
    app.show_browse_state = shown_states.append
    app.set_status = statuses.append
    app.focus_media_browser = lambda: None
    search = SimpleNamespace(id="search")

    app.on_input_changed(SimpleNamespace(input=search, value="inter"))
    app.on_input_changed(SimpleNamespace(input=search, value=""))

    assert app.browsing_stack[-1].title == "Movies"
    assert shown_states[0].title == "Fuzzy search: inter"
    assert [item.title for item in shown_states[0].items] == ["Interstellar"]
    assert shown_states[-1].title == "Movies"
    assert statuses[0] == "Fuzzy search: inter: 1 matches from 3 loaded items"
    assert statuses[-1] == "Movies: 3 items"

def test_load_more_media_can_preserve_selected_row():
    asyncio.run(run_load_more_media_preserve_selection_check())


def test_alphabet_jump_moves_list_selection_between_title_groups():
    asyncio.run(run_alphabet_jump_list_check())


def test_alphabet_jump_loads_more_when_next_section_is_not_loaded():
    asyncio.run(run_alphabet_jump_load_more_check())


def test_alphabet_jump_moves_grid_selection_between_title_groups():
    asyncio.run(run_alphabet_jump_grid_check())


def test_grid_browse_state_preserves_selected_media():
    asyncio.run(run_grid_browse_state_preserve_selection_check())


def test_grid_selection_pages_visible_cards():
    asyncio.run(run_grid_selection_page_check())


def test_grid_prefetch_schedules_once_per_visible_page():
    asyncio.run(run_grid_prefetch_schedule_check())


def test_grid_prefetch_schedules_loaded_pages_ahead():
    asyncio.run(run_grid_prefetch_pages_ahead_check())


def test_grid_prefetch_pages_ahead_can_be_disabled():
    asyncio.run(run_grid_prefetch_disabled_lookahead_check())


def test_cached_grid_prefetch_hydrates_visible_artwork():
    asyncio.run(run_cached_grid_prefetch_hydration_check())


def test_stale_cached_grid_prefetch_refetches_missing_artwork():
    asyncio.run(run_stale_cached_grid_prefetch_refetch_check())


def test_cold_grid_prefetch_applies_visible_artwork():
    asyncio.run(run_cold_grid_prefetch_application_check())


def test_same_grid_page_with_missing_artwork_retries_prefetch():
    asyncio.run(run_same_grid_page_missing_artwork_retry_check())


def test_grid_missing_artwork_render_schedules_prefetch():
    asyncio.run(run_grid_missing_artwork_render_schedule_check())


def test_grid_prefetch_queues_while_active_with_current_priority():
    asyncio.run(run_grid_prefetch_queue_check())


def test_grid_prefetch_ignores_duplicate_pending_pages():
    asyncio.run(run_grid_prefetch_duplicate_pending_check())


def test_grid_prefetch_skips_lookahead_while_current_in_flight():
    asyncio.run(run_grid_prefetch_current_in_flight_check())


def test_grid_prefetch_prioritizes_selected_card_without_changing_page_key():
    asyncio.run(run_grid_prefetch_selected_priority_check())


def test_current_grid_prefetch_applies_artwork_progressively():
    app = PlexTuiApp()
    app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
    app.active_grid_prefetch_pages = {("1", "2")}
    app.prefetched_grid_pages = set()
    app.pending_grid_prefetches = []
    app.rendered_grid_artwork_cache = {}
    items = [
        MediaItem("One", "", "movie", "1", True, Raw(), artwork_path="/thumb/1"),
        MediaItem("Two", "", "movie", "2", True, Raw(), artwork_path="/thumb/2"),
    ]
    applied = []
    app.call_from_thread = lambda callback, *args: callback(*args)
    app.apply_grid_artwork = lambda media_key, artwork: applied.append((media_key, artwork))
    app.apply_grid_artworks = lambda artwork_by_key: applied.append(("batch", artwork_by_key))
    app.render_grid_prefetch_item = lambda item, width, height: (item, f"art-{item.key}", 1.0, 1.0)

    PlexTuiApp.prefetch_grid_items.__wrapped__(app, items, ("1", "2"), "current")

    assert ("1", "art-1") in applied
    assert ("2", "art-2") in applied
    assert ("batch", {"1": "art-1", "2": "art-2"}) in applied


def test_partial_grid_prefetch_is_not_marked_complete():
    app = PlexTuiApp()
    app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
    app.active_grid_prefetch_pages = {("1", "2")}
    app.prefetched_grid_pages = set()
    app.pending_grid_prefetches = []
    app.rendered_grid_artwork_cache = {}
    items = [
        MediaItem("One", "", "movie", "1", True, Raw(), artwork_path="/thumb/1"),
        MediaItem("Two", "", "movie", "2", True, Raw(), artwork_path="/thumb/2"),
    ]
    applied = []
    app.call_from_thread = lambda callback, *args: callback(*args)
    app.apply_grid_artwork = lambda media_key, artwork: applied.append((media_key, artwork))
    app.apply_grid_artworks = lambda artwork_by_key: applied.append(("batch", artwork_by_key))

    def render_item(item, width, height):
        if item.key == "2":
            raise RuntimeError("failed")
        return item, f"art-{item.key}", 1.0, 1.0

    app.render_grid_prefetch_item = render_item

    PlexTuiApp.prefetch_grid_items.__wrapped__(app, items, ("1", "2"), "current")

    assert ("1", "art-1") in applied
    assert ("batch", {"1": "art-1"}) in applied
    assert ("1", "2") not in app.prefetched_grid_pages
    assert not app.active_grid_prefetch_pages


def test_grid_prefetch_reuses_rendered_artwork_cache():
    app = PlexTuiApp()
    app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
    app.active_grid_prefetch_pages = {("1",)}
    app.prefetched_grid_pages = set()
    app.pending_grid_prefetches = []
    item = MediaItem("Movie", "", "movie", "1", True, Raw(), artwork_path="/thumb")
    app.rendered_grid_artwork_cache = {grid_artwork_cache_key(item, app.config): "rendered-art"}
    applied = []
    app.call_from_thread = lambda callback, *args: callback(*args)
    app.apply_grid_artworks = lambda artwork_by_key: applied.append(artwork_by_key)
    app.render_grid_prefetch_item = lambda *args: (_ for _ in ()).throw(AssertionError("cache miss"))

    PlexTuiApp.prefetch_grid_items.__wrapped__(app, [item], ("1",), "current")

    assert applied == [{"1": "rendered-art"}]
    assert ("1",) in app.prefetched_grid_pages
    assert not app.active_grid_prefetch_pages


def test_detail_artwork_fetches_resized_detail_and_card_artwork(monkeypatch):
    app = PlexTuiApp()
    app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
    app.detail_refresh_token = 1
    app.rendered_grid_artwork_cache = {}
    full_item = MediaItem("Movie", "", "movie", "1", True, Raw(), artwork_path="/thumb")
    details = SimpleNamespace(artwork_path="/thumb")
    requested_sizes = []

    def capture_fetch(raw, path, config, width=None, height=None):
        requested_sizes.append((width, height))
        return b"image"

    monkeypatch.setattr(app_module, "fetch_artwork", capture_fetch)
    monkeypatch.setattr(app_module, "render_protocol_artwork", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "render_artwork", lambda *args, **kwargs: "detail-art")
    monkeypatch.setattr(app_module, "render_card_artwork", lambda *args, **kwargs: "card-art")
    app.call_from_thread = lambda callback, *args: None

    PlexTuiApp.fetch_media_detail_artwork.__wrapped__(
        app,
        full_item,
        details,
        token=1,
        detail_size=(30, 20),
        include_card_artwork=True,
    )

    assert requested_sizes == [(30, 40), card_artwork_fetch_size(app.config)]
    assert app.rendered_grid_artwork_cache[grid_artwork_cache_key(full_item, app.config)] == "card-art"


def test_detail_artwork_fetches_higher_resolution_for_kitty(monkeypatch):
    monkeypatch.setenv("KITTY_WINDOW_ID", "1")
    app = PlexTuiApp()
    app.config = AppConfig("http://plex", "token", "client-id", artwork_renderer="kitty", media_view="grid")
    app.detail_refresh_token = 1
    app.rendered_grid_artwork_cache = {}
    full_item = MediaItem("Movie", "", "movie", "1", True, Raw(), artwork_path="/thumb")
    details = SimpleNamespace(artwork_path="/thumb")
    requested_sizes = []

    def capture_fetch(raw, path, config, width=None, height=None):
        requested_sizes.append((width, height))
        return b"image"

    monkeypatch.setattr(app_module, "fetch_artwork", capture_fetch)
    monkeypatch.setattr(app_module, "render_protocol_artwork", lambda *args, **kwargs: "detail-art")
    monkeypatch.setattr(app_module, "render_card_artwork", lambda *args, **kwargs: "card-art")
    app.call_from_thread = lambda callback, *args: None

    PlexTuiApp.fetch_media_detail_artwork.__wrapped__(
        app,
        full_item,
        details,
        token=1,
        detail_size=(30, 20),
        include_card_artwork=True,
    )

    assert requested_sizes == [
        artwork_fetch_pixel_size(app.config, 30, 20),
        artwork_fetch_pixel_size(app.config, 18, 9),
    ]
    assert app.rendered_grid_artwork_cache[grid_artwork_cache_key(full_item, app.config)] == "card-art"


def test_detail_artwork_reuses_rendered_grid_card_cache(monkeypatch):
    app = PlexTuiApp()
    app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
    app.detail_refresh_token = 1
    full_item = MediaItem("Movie", "", "movie", "1", True, Raw(), artwork_path="/thumb")
    app.rendered_grid_artwork_cache = {grid_artwork_cache_key(full_item, app.config): "cached-card"}
    details = SimpleNamespace(artwork_path="/thumb")
    requested_sizes = []

    def capture_fetch(raw, path, config, width=None, height=None):
        requested_sizes.append((width, height))
        return b"image"

    monkeypatch.setattr(app_module, "fetch_artwork", capture_fetch)
    monkeypatch.setattr(app_module, "render_protocol_artwork", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "render_artwork", lambda *args, **kwargs: "detail-art")
    monkeypatch.setattr(app_module, "render_card_artwork", lambda *args, **kwargs: "card-art")
    app.call_from_thread = lambda callback, *args: None

    PlexTuiApp.fetch_media_detail_artwork.__wrapped__(
        app,
        full_item,
        details,
        token=1,
        detail_size=(30, 20),
        include_card_artwork=True,
    )

    assert requested_sizes == [(30, 40)]
    assert app.rendered_grid_artwork_cache[grid_artwork_cache_key(full_item, app.config)] == "cached-card"


def test_grid_detail_refresh_waits_for_idle_selection():
    asyncio.run(run_grid_detail_refresh_idle_check())


def test_list_detail_refresh_waits_for_short_idle_selection():
    asyncio.run(run_list_detail_refresh_idle_check())


def test_detail_artwork_refresh_waits_for_stable_selection():
    asyncio.run(run_detail_artwork_idle_check())


def test_grid_detail_artwork_skips_card_only_fetch():
    asyncio.run(run_grid_detail_artwork_card_fetch_check())


def test_detail_refresh_reuses_cached_reload():
    app = PlexTuiApp()
    app.config = AppConfig("http://plex", "token", "client-id", media_view="list")
    app.detail_cache = {}
    app.detail_refresh_token = 1

    class ReloadableRaw(Raw):
        reload_count = 0

        def reload(self):
            self.reload_count += 1
            return self

    raw = ReloadableRaw()
    item = MediaItem("Movie", "", "movie", "1", True, raw)
    applied = []
    app.call_from_thread = lambda callback, *args: callback(*args)
    app.apply_media_details = lambda full_item, token: applied.append((full_item.key, token))

    PlexTuiApp.refresh_media_details.__wrapped__(app, item, 1)

    assert raw.reload_count == 1
    assert app.detail_cache["1"].raw is raw
    assert applied == [("1", 1)]

    app.detail_refresh_token = 2
    PlexTuiApp.refresh_media_details.__wrapped__(app, item, 2)

    assert raw.reload_count == 1
    assert applied == [("1", 1), ("1", 2)]


def test_search_state_adds_load_more_row():
    asyncio.run(run_search_load_more_row_check())


def test_load_more_media_appends_search_page():
    asyncio.run(run_load_more_search_check())


def test_settings_actions_update_preferences():
    asyncio.run(run_settings_action_check())


def test_stale_profile_load_does_not_reopen_profile_picker(monkeypatch):
    asyncio.run(run_stale_profile_load_check(monkeypatch))


def test_settings_toggle_library_visibility_updates_sidebar():
    asyncio.run(run_settings_library_visibility_check())


def test_settings_toggle_sidebar_entrypoints_updates_sidebar():
    asyncio.run(run_settings_sidebar_entrypoint_visibility_check())


def test_plex_services_sidebar_opens_optional_feature_settings():
    asyncio.run(run_plex_services_sidebar_opens_settings_check())


def test_settings_move_library_updates_sidebar_order():
    asyncio.run(run_settings_library_order_check())


def test_settings_recent_debug_log_action_shows_tail(tmp_path):
    asyncio.run(run_settings_recent_debug_log_check(tmp_path))


def test_settings_app_diagnostics_action_shows_runtime_summary():
    asyncio.run(run_settings_app_diagnostics_check())


def test_playback_error_shows_recent_debug_log(tmp_path):
    asyncio.run(run_playback_error_check(tmp_path))


def test_unavailable_vod_stream_uses_clean_error_view():
    asyncio.run(run_unavailable_vod_stream_check())


def test_playback_footer_shows_active_playback():
    asyncio.run(run_playback_footer_check())


def test_playback_controls_update_active_mpv():
    asyncio.run(run_playback_controls_check())


def test_playback_action_starts_from_beginning():
    asyncio.run(run_playback_starts_from_beginning_check())


def test_playback_action_prompts_before_starting_over_resumable_media():
    asyncio.run(run_playback_start_over_prompt_check())


def test_optimized_playback_action_forces_transcode_for_one_launch():
    asyncio.run(run_optimized_playback_action_check())


def test_playback_action_opens_container_media():
    app = PlexTuiApp()
    media = MediaItem("Bubblegum Crisis", "TV Show", "show", "show-1", False, Raw())

    with patch.object(app, "open_media") as open_media:
        app.play_media(media, resume=False)

    open_media.assert_called_once_with(media)


def test_open_playable_media_does_not_fetch_children():
    asyncio.run(run_open_playable_media_does_not_fetch_children_check())


async def run_open_playable_media_does_not_fetch_children_check():
    item = MediaItem("Cabaret", "", "movie", "movie-1", True, Raw())
    service = FakePagedService(MediaPage([item], start=0, total=1))
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.service = service
        app.config = AppConfig("http://plex", "token", "client-id")

        app.open_media(item)
        await wait_for_status(app, pilot, "Selected Cabaret. Press p to play.")

        assert service.children_calls == []


def test_resume_action_uses_saved_position():
    asyncio.run(run_resume_action_check())


def test_resume_key_uses_saved_position():
    asyncio.run(run_resume_key_check())


def test_resume_action_requires_saved_position():
    asyncio.run(run_resume_requires_position_check())


def test_start_over_picker_launches_without_reopening_picker():
    asyncio.run(run_start_over_picker_launch_check())


def test_terminal_playback_defaults_to_low_transcode():
    asyncio.run(run_terminal_playback_low_transcode_check())


def test_terminal_playback_keeps_online_metadata_direct():
    asyncio.run(run_terminal_playback_online_metadata_direct_check())


def test_terminal_playback_exit_invalidates_grid_artwork():
    asyncio.run(run_terminal_playback_exit_invalidates_grid_artwork_check())


def test_toggle_watched_marks_unwatched_media_watched():
    asyncio.run(run_toggle_watched_marks_unwatched_check())


def test_toggle_watched_refreshes_continue_watching_next_episode():
    asyncio.run(run_toggle_watched_continue_watching_refresh_check())


def test_toggle_watched_refreshes_continue_watching_next_episode_when_raw_item_is_hub_wrapper():
    asyncio.run(run_toggle_watched_continue_watching_refresh_resolves_hub_wrapper_check())


def test_playback_refresh_selects_next_continue_watching_episode():
    asyncio.run(run_playback_refresh_selects_next_continue_watching_episode_check())


def test_open_parent_context_from_continue_watching_episode():
    asyncio.run(run_open_parent_context_from_continue_watching_episode_check())


def test_open_show_context_from_continue_watching_episode():
    asyncio.run(run_open_show_context_from_continue_watching_episode_check())


def test_toggle_watched_marks_watched_media_unwatched():
    asyncio.run(run_toggle_watched_marks_watched_check())


def test_toggle_watched_rejects_unsupported_media():
    asyncio.run(run_toggle_watched_unsupported_check())


def test_add_to_playlist_picker_adds_existing_playlist():
    asyncio.run(run_add_to_playlist_existing_check())


def test_add_to_playlist_picker_creates_new_playlist():
    asyncio.run(run_add_to_playlist_create_check())


def test_remove_playlist_item_updates_playlist_view():
    asyncio.run(run_remove_playlist_item_check())


def test_playlist_browse_shows_remove_hint():
    asyncio.run(run_playlist_browse_remove_hint_check())


def test_bulk_add_to_playlist_uses_selected_items():
    asyncio.run(run_bulk_add_to_playlist_check())


def test_bulk_remove_from_playlist_uses_selected_items():
    asyncio.run(run_bulk_remove_from_playlist_check())


def test_rename_playlist_updates_current_view():
    asyncio.run(run_rename_playlist_check())


def test_delete_playlist_removes_current_playlist():
    asyncio.run(run_delete_playlist_check())


def test_remove_continue_watching_removes_selected_item():
    asyncio.run(run_remove_continue_watching_check())


def test_remove_continue_watching_requires_continue_watching_view():
    asyncio.run(run_remove_continue_watching_requires_view_check())


def test_stream_picker_updates_active_playback():
    asyncio.run(run_stream_picker_live_switch_check())


def test_quick_preference_actions_update_config():
    asyncio.run(run_quick_preference_action_check())


def test_mpv_window_size_input_updates_preferences():
    asyncio.run(run_mpv_window_size_input_check())


def test_numeric_settings_input_updates_preferences():
    asyncio.run(run_numeric_settings_input_check())


def test_numeric_settings_adjust_with_left_right():
    asyncio.run(run_numeric_settings_left_right_check())


def test_option_settings_cycle_with_left_right():
    asyncio.run(run_option_settings_left_right_check())


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
        assert not app.query_one("#sidebar").has_class("context-pane")
        library_row = app.query_one("#libraries").highlighted_child
        assert library_row is not None
        assert library_row.has_class("active-row")
        assert not library_row.has_class("context-row")
        assert not app.query_one("#main").has_class("focused-pane")
        assert app.query_one("#libraries-title").content == "Libraries"
        assert app.query_one("#media-title").content == "Movies"

        app.action_focus_media()
        await pilot.pause(0.1)
        assert app.query_one("#main").has_class("focused-pane")
        assert not app.query_one("#sidebar").has_class("focused-pane")
        assert app.query_one("#sidebar").has_class("context-pane")
        assert library_row.has_class("context-row")
        assert not library_row.has_class("active-row")
        assert not app.query_one("#details").has_class("focused-pane")
        assert app.query_one("#media-title").content == "Movies"
        assert app.query_one("#libraries-title").content == "Libraries"

        app.action_focus_details()
        await pilot.pause(0.1)
        assert app.query_one("#details").has_class("focused-pane")
        assert app.query_one("#sidebar").has_class("context-pane")
        assert library_row.has_class("context-row")
        assert not library_row.has_class("active-row")
        assert app.query_one("#details-title").content == "Details"
        assert not app.query_one("#main").has_class("focused-pane")

        app.action_focus_media()
        await pilot.press("d")
        await pilot.pause(0.1)
        assert app.query_one("#details").has_class("focused-pane")
        assert app.query_one("#details-title").content == "Details"
        assert not app.query_one("#main").has_class("focused-pane")


async def run_left_right_focus_ownership_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        app.populate_libraries([
            LibraryItem("Movies", "1", "movie", object()),
            LibraryItem("TV Shows", "2", "show", object()),
        ])
        app.show_media(
            "Movies",
            [
                MediaItem("First", "", "movie", "1", True, Raw()),
                MediaItem("Second", "", "movie", "2", True, Raw()),
            ],
        )
        await pilot.pause(0.2)

        libraries = app.query_one("#libraries", ListView)
        grid = app.query_one("#media-grid", MediaGrid)
        highlighted_library_row = libraries.highlighted_child
        assert grid.selected_media.title == "First"

        app.action_focus_details()
        await pilot.press("right")
        await pilot.pause(0.1)

        assert libraries.highlighted_child is highlighted_library_row
        assert grid.selected_media.title == "First"

        app.action_focus_media()
        await pilot.press("right")
        await pilot.pause(0.1)

        assert grid.selected_media.title == "Second"


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
        assert app.query_one("#media-title").content == "Movies"
        assert app.query_one("#libraries-title").content == "Libraries"

        await pilot.press("tab")
        await pilot.pause(0.2)

        assert app.query_one("#sidebar").has_class("focused-pane")
        assert app.query_one("#libraries-title").content == "Libraries"
        assert not app.query_one("#main").has_class("focused-pane")

        await pilot.press("shift+tab")
        await pilot.pause(0.2)

        assert app.query_one("#main").has_class("focused-pane")
        assert app.query_one("#media-title").content == "Movies"
        assert not app.query_one("#details").has_class("focused-pane")

        await pilot.press("d")
        await pilot.pause(0.2)

        assert app.query_one("#details").has_class("focused-pane")
        assert app.query_one("#details-title").content == "Details"


async def run_library_highlight_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        libraries = [
            LibraryItem("Movies", "1", "movie", object()),
            LibraryItem("TV", "2", "show", object()),
        ]

        app.populate_libraries(libraries)
        app.show_detail_text("Browse Plex-hosted Movies & Shows hubs.")
        libraries_view = app.query_one("#libraries")
        libraries_view.focus()
        await pilot.pause(0.2)
        await pilot.press("down")
        await pilot.press("down")
        await pilot.pause(0.2)

        row = libraries_view.highlighted_child
        assert row is not None
        assert row.has_class("active-row")
        assert row.library.title == "Movies"
        details = app.query_one("#detail-content").content
        assert "Movies" in details
        assert "Default view: Library" in details
        assert "Enter: Open Library view" in details
        assert "Space: Choose browse view" in details
        assert "Browse Plex-hosted Movies & Shows hubs." not in details


async def run_continue_watching_entrypoint_check():
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

        rows = list(libraries_view.children)
        assert isinstance(rows[0], ContinueWatchingRow)
        assert isinstance(rows[1], PlaylistsRow)
        assert [row.library.title for row in rows[2:4]] == ["Movies", "TV"]
        assert isinstance(rows[4], PlexServicesRow)
        assert libraries_view.highlighted_child is rows[0]


async def run_startup_continue_watching_default_check(monkeypatch):
    item = MediaItem("In Progress", "", "movie", "cw-1", True, Raw())
    service = StartupService(MediaPage([item], start=0, total=1))
    monkeypatch.setattr(PlexTuiApp, "load_server", STARTUP_LOAD_SERVER)
    monkeypatch.setattr(app_module, "load_config", lambda: AppConfig("http://plex", "token", "client-id"))
    monkeypatch.setattr(app_module, "PlexService", lambda config: service)
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        for _ in range(80):
            if app.browsing_stack and app.browsing_stack[-1].source == "continue_watching":
                break
            await pilot.pause(0.1)

        libraries_view = app.query_one("#libraries")
        rows = list(libraries_view.children)
        assert isinstance(rows[0], ContinueWatchingRow)
        assert libraries_view.highlighted_child is rows[0]
        assert app.browsing_stack[-1].source == "continue_watching"
        selected = await wait_for_selected_title(app, pilot, "In Progress")
        assert selected is not None
        assert service.continue_watching_calls[-1] == (0, 40)
        assert service.entry_calls == []


async def run_playlists_entrypoint_check():
    service = PlaylistService()
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", show_discover=True)
        app.service = service
        app.populate_libraries([LibraryItem("Movies", "1", "movie", object())])
        await pilot.pause(0.2)

        app.open_playlists()
        for _ in range(80):
            if app.browsing_stack and app.browsing_stack[-1].source == "playlists":
                break
            await pilot.pause(0.1)

        assert app.browsing_stack[-1].title == "Playlists"
        assert [item.title for item in app.browsing_stack[-1].items] == ["Favorites"]
        assert app.query_one("#media-title").content == "Playlists"


async def run_discover_entrypoint_check(monkeypatch):
    opened_urls = []
    monkeypatch.setattr(app_module.webbrowser, "open", opened_urls.append)
    item = MediaItem("The Matrix", "1 provider: Plex · Free", "movie", "discover-1", False, DiscoverRaw())
    service = FakePagedService(MediaPage([item], start=0, total=1))
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", show_discover=True)
        app.service = service
        app.populate_libraries([LibraryItem("Movies", "1", "movie", object())])
        libraries_view = app.query_one("#libraries")
        libraries_view.focus()
        await pilot.pause(0.2)
        await pilot.press("down")
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause(0.2)

        search = app.query_one("#search")
        assert search.display
        assert app.input_mode == "discover_search"
        assert search.placeholder == "Search Plex Discover"

        search.value = "matrix"
        await pilot.press("enter")
        for _ in range(80):
            if app.browsing_stack and app.browsing_stack[-1].source == "discover":
                break
            await pilot.pause(0.1)

        assert service.discover_calls == [("matrix", 0, 40, "movies_shows")]
        assert app.browsing_stack[-1].title == "Discover Movies & Shows: matrix"
        assert app.query_one("#media").highlighted_child.media.title == "The Matrix"

        await pilot.press("enter")
        await pilot.pause(0.5)

        assert opened_urls == ["https://watch.plex.tv/movie"]
        assert app.query_one("#status").content == "Opened: The Matrix - Plex · Free"


async def run_discover_provider_picker_check(monkeypatch):
    opened_urls = []
    monkeypatch.setattr(app_module.webbrowser, "open", opened_urls.append)
    item = MediaItem(
        "The Matrix",
        "2 providers: Plex · Free, Prime · Rent",
        "movie",
        "discover-1",
        False,
        MultiProviderDiscoverRaw(),
    )
    service = FakePagedService(MediaPage([item], start=0, total=1))
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", show_discover=True)
        app.service = service
        app.populate_libraries([LibraryItem("Movies", "1", "movie", object())])
        libraries_view = app.query_one("#libraries")
        libraries_view.focus()
        await pilot.pause(0.2)
        await pilot.press("down")
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause(0.2)

        app.query_one("#search").value = "matrix"
        await pilot.press("enter")
        for _ in range(80):
            if app.browsing_stack and app.browsing_stack[-1].source == "discover":
                break
            await pilot.pause(0.1)

        await pilot.press("enter")

        rows = await wait_for_availability_rows(app, pilot)
        assert app.picker_visible
        assert app.query_one("#media-title").content == "Availability: The Matrix"
        assert [row.label for row in rows] == ["Plex · Free", "Prime · Rent"]

        await pilot.press("down")
        await pilot.press("enter")
        opened = await wait_for_calls(opened_urls, pilot, attempts=80)

        assert opened == ["https://example.com/prime"]
        assert not app.picker_visible
        assert app.query_one("#media").highlighted_child.media.title == "The Matrix"


async def run_discover_without_availability_check(monkeypatch):
    opened_urls = []
    monkeypatch.setattr(app_module.webbrowser, "open", opened_urls.append)
    item = MediaItem("The Matrix", "", "movie", "discover-1", False, NoAvailabilityDiscoverRaw())
    service = FakePagedService(MediaPage([item], start=0, total=1))
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", show_discover=True, show_on_plex=True)
        app.service = service
        app.populate_libraries([LibraryItem("Movies", "1", "movie", object())])
        libraries_view = app.query_one("#libraries")
        libraries_view.focus()
        await pilot.pause(0.2)
        await pilot.press("down")
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause(0.2)

        app.query_one("#search").value = "matrix"
        await pilot.press("enter")
        for _ in range(80):
            if app.browsing_stack and app.browsing_stack[-1].source == "discover":
                break
            await pilot.pause(0.1)

        await pilot.press("enter")
        status = await wait_for_status(app, pilot, "No availability links for The Matrix.")

        assert status == "No availability links for The Matrix."
        assert opened_urls == []
        assert service.children_calls == []
        assert app.browsing_stack[-1].source == "discover"


class SlowDiscoverService:
    def __init__(self, page: MediaPage) -> None:
        self.page = page
        self.discover_calls = []

    def discover_page(self, query: str, start: int, size: int, media_type: str = "movies_shows") -> MediaPage:
        self.discover_calls.append((query, start, size, media_type))
        time.sleep(0.5)
        return self.page


async def run_escape_cancels_slow_discover_search_check():
    original = MediaItem("Existing Movie", "2024", "movie", "movie-1", True, Raw())
    discovered = MediaItem("Slow Result", "Movie", "movie", "discover-1", False, DiscoverRaw())
    service = SlowDiscoverService(MediaPage([discovered], start=0, total=1))
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.service = service
        state = BrowseState("Movies", [original], source="library", total=1)
        app.browsing_stack = [state]
        app.show_browse_state(state)
        app.prompt_discover_search()

        search = app.query_one("#search")
        search.value = "slow"
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert app.focused is not search
        await pilot.press("escape")
        await pilot.pause(0.8)

        assert service.discover_calls == [("slow", 0, 40, "movies_shows")]
        assert app.browsing_stack == [state]
        assert app.query_one("#media-title").content == "Movies"
        assert app.query_one("#media").highlighted_child.media.title == "Existing Movie"
        assert "Slow Result" not in str(app.query_one("#media").render())
        assert not app.query_one("#search").display
        assert app.search_return_state is None


async def run_discover_vod_entrypoint_check():
    hub = MediaItem("Because You Watched Macross Plus", "Hub", "hub", "vod-hub-1", False, Raw())
    service = FakePagedService(MediaPage([hub], start=0, total=1))
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", show_discover=True, show_on_plex=True)
        app.service = service
        app.populate_libraries([LibraryItem("Movies", "1", "movie", object())])
        libraries_view = app.query_one("#libraries")
        libraries_view.focus()
        await pilot.pause(0.2)
        await pilot.press("down")
        await pilot.press("down")
        await pilot.press("down")
        await pilot.press("enter")
        for _ in range(80):
            if app.browsing_stack and app.browsing_stack[-1].source == "vod":
                break
            await pilot.pause(0.1)

        assert service.video_on_demand_calls == [(0, 40)]
        assert app.browsing_stack[-1].title == "Movies & Shows on Plex"
        assert app.query_one("#media").highlighted_child.media.title == "Because You Watched Macross Plus"


async def run_on_plex_live_entrypoint_check():
    channel = MediaItem("Live One", "ONE  HD  HLS", "livetv", "channel-1", True, Raw())
    service = FakePagedService(MediaPage([channel], start=0, total=1))
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig(
            "http://plex",
            "token",
            "client-id",
            media_view="grid",
            show_discover=True,
            show_on_plex=True,
            show_on_plex_live=True,
        )
        app.service = service
        app.populate_libraries([LibraryItem("Movies", "1", "movie", object())])
        libraries_view = app.query_one("#libraries")
        libraries_view.focus()
        await pilot.pause(0.2)
        await pilot.press("down")
        await pilot.press("down")
        await pilot.press("down")
        await pilot.press("down")
        await pilot.press("enter")
        for _ in range(80):
            if app.browsing_stack and app.browsing_stack[-1].source == "livetv":
                break
            await pilot.pause(0.1)

        assert service.hosted_live_tv_calls == [(0, 40)]
        assert app.browsing_stack[-1].title == "Live TV on Plex"
        assert app.query_one("#media").highlighted_child.media.title == "Live One"
        assert app.query_one("#media").display
        assert not app.query_one("#media-grid-scroll").display


async def run_on_plex_live_channel_guide_check():
    channel_raw = SimpleNamespace(TYPE="livetv", title="Live One", grid_key="grid-1")
    channel = MediaItem("Live One", "ONE  HD  HLS", "livetv", "channel-1", True, channel_raw)
    service = FakePagedService(MediaPage([channel], start=0, total=1))
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.service = service
        state = BrowseState("Live TV on Plex", [channel], source="livetv", next_start=1, total=1)
        app.browsing_stack = [state]
        app.show_browse_state(state)
        await pilot.pause(0.2)

        opened = []
        app.open_hosted_live_tv_guide = opened.append
        app.open_media(channel)
        for _ in range(20):
            if opened:
                break
            await asyncio.sleep(0.05)

        assert opened == [channel]
        assert service.children_calls == []


async def run_on_plex_live_guide_list_view_check():
    program = MediaItem("Coda", "2:00 PM-3:00 PM  480", "livetv_program", "program-1", False, Raw(), artwork_path="/thumb")
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        state = BrowseState("Guide: Ion Mystery", [program], source="livetv_guide", next_start=1, total=1)
        app.browsing_stack = [state]

        app.show_browse_state(state)
        await pilot.pause(0.2)

        assert app.query_one("#media").display
        assert not app.query_one("#media-grid-scroll").display
        row = app.query_one("#media").highlighted_child
        assert row is not None
        assert "Coda" in row.label_text
        assert "2:00 PM-3:00 PM" in row.label_text


async def run_unavailable_on_plex_live_channel_check():
    channel = MediaItem("Locked", "HLS", "livetv", "channel-2", False, Raw())
    service = FakePagedService(MediaPage([channel], start=0, total=1))
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.service = service
        state = BrowseState("Live TV on Plex", [channel], source="livetv", next_start=1, total=1)
        app.browsing_stack = [state]
        app.show_browse_state(state)
        await pilot.pause(0.2)

        app.open_media(channel)
        status = await wait_for_status(
            app,
            pilot,
            "Playback unavailable: This Plex Live TV channel is unavailable for external playback.",
        )

        details = app.query_one("#detail-content").content
        assert status == "Playback unavailable: This Plex Live TV channel is unavailable for external playback."
        assert "This Plex Live TV channel is unavailable for external playback." in details
        assert service.children_calls == []


async def run_selected_library_highlight_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        libraries = [
            LibraryItem("Movies", "1", "movie", object()),
            LibraryItem("TV", "2", "show", object()),
        ]

        app.populate_libraries(libraries, selected_library_key="1")
        libraries_view = app.query_one("#libraries")
        libraries_view.focus()
        await pilot.pause(0.2)

        rows = list(libraries_view.children)
        assert isinstance(rows[0], ContinueWatchingRow)
        assert isinstance(rows[1], PlaylistsRow)
        assert libraries_view.highlighted_child is rows[2]
        assert rows[2].library.title == "Movies"


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


async def run_live_tv_guide_load_more_row_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        channel = MediaItem("Ion Mystery", "", "livetv", "channel", True, Raw())
        items = [
            MediaItem("First", "10:00 AM-11:00 AM", "livetv_program", "1", False, Raw()),
            MediaItem("Second", "11:00 AM-12:00 PM", "livetv_program", "2", False, Raw()),
        ]
        state = BrowseState(
            "Guide: Ion Mystery",
            items,
            source="livetv_guide",
            next_start=2,
            total=5,
            context_media=channel,
        )

        app.show_browse_state(state)
        await pilot.pause(0.2)

        rows = list(app.query_one("#media").children)
        assert len(rows) == 3
        assert isinstance(rows[-1], LoadMoreRow)


async def run_empty_browse_state_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        state = BrowseState("Continue Watching", [], source="continue_watching", total=0)

        app.show_browse_state(state)
        await pilot.pause(0.2)

        rows = list(app.query_one("#media").children)
        assert len(rows) == 1
        assert isinstance(rows[0], EmptyStateRow)
        assert rows[0].label_text.strip() == "Nothing in progress"
        details = app.query_one("#detail-content").content
        assert "Empty View" in details
        assert "Start playback from a library item" in details
        assert app.query_one("#status").content == "Continue Watching: 0 items"


class FakePagedService:
    def __init__(self, page: MediaPage) -> None:
        self.page = page
        self.media_by_key: dict[str, object] = {}
        self.calls = []
        self.entry_calls = []
        self.search_calls = []
        self.continue_watching_calls = []
        self.discover_calls = []
        self.video_on_demand_calls = []
        self.hosted_live_tv_calls = []
        self.hosted_live_tv_guide_calls = []
        self.guide_page = MediaPage([], start=0, total=0)
        self.children_calls = []
        self.media_from_key_calls = []
        self.children_by_key: dict[str, list[MediaItem]] = {}

    def library_page(self, library: LibraryItem, start: int, size: int) -> MediaPage:
        self.calls.append((library, start, size))
        return self.page

    def library_entry_page(self, library: LibraryItem, entry: str, start: int, size: int) -> MediaPage:
        self.entry_calls.append((library, entry, start, size))
        return self.page

    def search_page(self, query: str, library: LibraryItem | None, start: int, size: int) -> MediaPage:
        self.search_calls.append((query, library, start, size))
        return self.page

    def continue_watching_page(self, start: int, size: int) -> MediaPage:
        self.continue_watching_calls.append((start, size))
        return self.page

    def media_from_key(self, key: str) -> object | None:
        self.media_from_key_calls.append(key)
        return self.media_by_key.get(key)

    def discover_page(self, query: str, start: int, size: int, media_type: str = "movies_shows") -> MediaPage:
        self.discover_calls.append((query, start, size, media_type))
        return self.page

    def video_on_demand_page(self, start: int, size: int) -> MediaPage:
        self.video_on_demand_calls.append((start, size))
        return self.page

    def hosted_live_tv_page(self, start: int, size: int) -> MediaPage:
        self.hosted_live_tv_calls.append((start, size))
        return self.page

    def hosted_live_tv_guide_page(self, channel: MediaItem, size: int = 40) -> MediaPage:
        self.hosted_live_tv_guide_calls.append((channel.key, size))
        return self.guide_page

    def children(self, item: MediaItem, size: int = 40) -> list[MediaItem]:
        self.children_calls.append((item.key, size))
        return self.children_by_key.get(item.key, [])

    def episode_parent(self, item: MediaItem) -> MediaItem | None:
        raw = self.media_from_key(getattr(item.raw, "parentKey", ""))
        return raw if isinstance(raw, MediaItem) else None

    def episode_show(self, item: MediaItem) -> MediaItem | None:
        raw = self.media_from_key(getattr(item.raw, "grandparentKey", ""))
        return raw if isinstance(raw, MediaItem) else None


class StartupService(FakePagedService):
    friendly_name = "Test Plex"

    def __init__(self, page: MediaPage) -> None:
        super().__init__(page)
        self.entry_calls = []

    def libraries(self) -> list[LibraryItem]:
        return [LibraryItem("Movies", "1", "movie", object())]


class FakeFlowService:
    def __init__(
        self,
        pages: dict[tuple[str, int], MediaPage],
        children: dict[str, list[MediaItem]] | None = None,
    ) -> None:
        self.pages = pages
        self.children_by_key = children or {}
        self.entry_calls = []
        self.children_calls = []

    def library_entry_page(self, library: LibraryItem, entry: str, start: int, size: int) -> MediaPage:
        self.entry_calls.append((library, entry, start, size))
        return self.pages[(entry, start)]

    def children(self, item: MediaItem, size: int = 40) -> list[MediaItem]:
        self.children_calls.append((item.key, size))
        return self.children_by_key.get(item.key, [])


async def run_initial_library_page_size_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        library = LibraryItem("Movies", "1", "movie", object())
        page = MediaPage([MediaItem("First", "", "movie", "1", True, Raw())], start=0, total=1)
        service = FakePagedService(page)
        app.config = AppConfig("http://plex", "token", "client-id", page_size=45)
        app.service = service

        app.open_library_entry(library)
        await pilot.pause(0.5)

        assert service.entry_calls == [(library, "library", 0, 45)]


async def run_library_menu_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        library = LibraryItem("Movies", "1", "movie", object())

        app.open_library_menu(library)
        await pilot.pause(0.2)

        rows = list(app.query_one("#media").children)
        assert [row.label_text for row in rows if isinstance(row, LibraryMenuRow)] == [
            "Library",
            "Recommended",
            "Collections",
            "Playlists",
            "Categories",
        ]
        assert app.selected_library == library
        assert app.browsing_stack == []


async def run_sidebar_library_selection_opens_default_library_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        page = MediaPage([MediaItem("First", "", "movie", "1", True, Raw())], start=0, total=1)
        service = FakePagedService(page)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.service = service
        library = LibraryItem("Movies", "1", "movie", object())
        app.populate_libraries([library])
        libraries_view = app.query_one("#libraries")
        libraries_view.focus()
        await pilot.pause(0.2)
        await pilot.press("down")
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause(0.5)

        assert service.entry_calls == [(library, "library", 0, 40)]
        assert app.browsing_stack[-1].title == "Movies"
        assert app.query_one("#media").highlighted_child.media.title == "First"


async def run_sidebar_library_space_menu_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        library = LibraryItem("Movies", "1", "movie", object())
        app.populate_libraries([library])
        libraries_view = app.query_one("#libraries")
        libraries_view.focus()
        await pilot.pause(0.2)
        await pilot.press("down")
        await pilot.press("down")
        await pilot.press("space")
        await pilot.pause(0.2)

        rows = list(app.query_one("#media").children)
        assert [row.label_text for row in rows if isinstance(row, LibraryMenuRow)] == [
            "Library",
            "Recommended",
            "Collections",
            "Playlists",
            "Categories",
        ]
        assert app.selected_library == library
        assert app.browsing_stack == []


async def run_sidebar_library_selection_menu_default_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", library_enter_action="browse_modes")
        library = LibraryItem("Movies", "1", "movie", object())
        app.populate_libraries([library])
        libraries_view = app.query_one("#libraries")
        libraries_view.focus()
        await pilot.pause(0.2)
        await pilot.press("down")
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause(0.2)

        rows = list(app.query_one("#media").children)
        assert [row.label_text for row in rows if isinstance(row, LibraryMenuRow)] == [
            "Library",
            "Recommended",
            "Collections",
            "Playlists",
            "Categories",
        ]
        assert app.selected_library == library
        assert app.browsing_stack == []


async def run_library_entry_back_to_menu_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        library = LibraryItem("Movies", "1", "movie", object())
        item = MediaItem("First", "", "movie", "1", True, Raw())
        app.selected_library = library
        app.browsing_stack = [
            BrowseState("Movies", [item], library, source="library:library", next_start=1, total=1)
        ]
        app.show_browse_state(app.browsing_stack[-1])
        await pilot.pause(0.2)

        app.action_back_or_clear()
        await pilot.pause(0.2)

        rows = list(app.query_one("#media").children)
        assert [row.label_text for row in rows if isinstance(row, LibraryMenuRow)] == [
            "Library",
            "Recommended",
            "Collections",
            "Playlists",
            "Categories",
        ]
        assert app.browsing_stack == []


async def run_library_submenu_keyboard_flow_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        library = LibraryItem("Movies", "1", "movie", object())
        movie = MediaItem("Blade Runner", "1982", "movie", "movie-1", True, Raw(), artwork_path="/thumb")
        hub = MediaItem("Recently Added", "", "hub", "hub-1", False, object(), artwork_path="")
        service = FakeFlowService(
            {
                ("library", 0): MediaPage([movie], start=0, total=1),
                ("recommended", 0): MediaPage([hub], start=0, total=1),
            },
            {"hub-1": [movie]},
        )
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        app.service = service

        app.populate_libraries([library], selected_library_key="1")
        app.open_library_entry(library)
        await pilot.pause(0.5)

        libraries_view = app.query_one("#libraries")
        rows = list(libraries_view.children)
        assert libraries_view.highlighted_child is rows[2]
        assert rows[2].library.title == "Movies"
        assert app.query_one("#media-grid").selected_media.title == "Blade Runner"

        libraries_view.focus()
        await pilot.press("space")
        await pilot.pause(0.2)
        menu_rows = list(app.query_one("#media").children)
        assert [row.label_text for row in menu_rows if isinstance(row, LibraryMenuRow)] == [
            "Library",
            "Recommended",
            "Collections",
            "Playlists",
            "Categories",
        ]

        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert service.entry_calls[-1] == (library, "recommended", 0, 40)
        assert app.query_one("#media-grid").selected_media.title == "Recently Added"
        assert app.query_one("#media-grid").selected_media.kind == "hub"

        await pilot.press("enter")
        await pilot.pause(0.5)
        assert service.children_calls == [("hub-1", 40)]
        assert app.browsing_stack[-1].title == "Recently Added"
        assert app.query_one("#media-grid").selected_media.title == "Blade Runner"

        await pilot.press("escape")
        await pilot.pause(0.2)
        assert app.browsing_stack[-1].title == "Movies: Recommended"

        await pilot.press("escape")
        await pilot.pause(0.2)
        menu_rows = list(app.query_one("#media").children)
        assert [row.label_text for row in menu_rows if isinstance(row, LibraryMenuRow)] == [
            "Library",
            "Recommended",
            "Collections",
            "Playlists",
            "Categories",
        ]
        assert app.browsing_stack == []


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


async def run_load_more_continue_watching_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", page_size=25)
        first = MediaItem("First", "", "movie", "1", True, Raw())
        second = MediaItem("Second", "", "movie", "2", True, Raw())
        page = MediaPage([second], start=1, total=3)
        service = FakePagedService(page)
        app.service = service
        app.browsing_stack = [
            BrowseState("Continue Watching", [first], source="continue_watching", next_start=1, total=3)
        ]

        app.load_more_media()
        await pilot.pause(0.5)

        state = app.browsing_stack[-1]
        assert service.continue_watching_calls == [(1, 25)]
        assert service.calls == []
        assert [item.title for item in state.items] == ["First", "Second"]
        assert state.next_start == 2
        assert state.has_more


async def run_load_more_ignores_replaced_browse_state_check():
    app = PlexTuiApp()
    started = threading.Event()
    release = threading.Event()

    class BlockingService(FakePagedService):
        def continue_watching_page(self, start: int, size: int) -> MediaPage:
            self.continue_watching_calls.append((start, size))
            started.set()
            release.wait(timeout=5)
            return self.page

    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", page_size=25)
        first = MediaItem("Episode 1", "", "episode", "episode-1", True, Raw())
        second = MediaItem("Episode 2", "", "episode", "episode-2", True, Raw())
        stale_state = BrowseState("Continue Watching", [first], source="continue_watching", next_start=1, total=2)
        service = BlockingService(MediaPage([second], start=1, total=2))
        app.service = service
        app.browsing_stack = [stale_state]

        app.load_more_media()
        for _ in range(50):
            if started.is_set():
                break
            await pilot.pause(0.1)
        app.browsing_stack = [BrowseState("Continue Watching", [second], source="continue_watching", total=1)]
        release.set()
        for _ in range(50):
            if not app.loading_more:
                break
            await pilot.pause(0.1)

        assert service.continue_watching_calls == [(1, 25)]
        assert [item.title for item in app.browsing_stack[-1].items] == ["Episode 2"]
        assert [item.title for item in stale_state.items] == ["Episode 1"]
        assert not app.loading_more


async def run_load_more_library_submenu_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", page_size=30)
        library = LibraryItem("Movies", "1", "movie", object())
        first = MediaItem("First", "", "collection", "1", False, Raw())
        second = MediaItem("Second", "", "collection", "2", False, Raw())
        page = MediaPage([second], start=1, total=3)
        service = FakePagedService(page)
        app.service = service
        app.browsing_stack = [
            BrowseState("Movies: Collections", [first], library, source="library:collections", next_start=1, total=3)
        ]

        app.load_more_media()
        await pilot.pause(0.5)

        state = app.browsing_stack[-1]
        assert service.entry_calls == [(library, "collections", 1, 30)]
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


async def run_alphabet_jump_list_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        items = [
            MediaItem("Alien", "", "movie", "1", True, Raw()),
            MediaItem("Aliens", "", "movie", "2", True, Raw()),
            MediaItem("Casablanca", "", "movie", "3", True, Raw()),
            MediaItem("Blade Runner", "", "movie", "4", True, Raw()),
        ]
        app.browsing_stack = [BrowseState("Movies", items)]
        app.show_browse_state(app.browsing_stack[-1])
        await pilot.pause(0.2)

        app.action_jump_alpha_next()
        selected = await wait_for_selected_title(app, pilot, "Casablanca")
        assert selected is not None
        assert selected.title == "Casablanca"

        app.action_jump_alpha_next()
        selected = await wait_for_selected_title(app, pilot, "Blade Runner")
        assert selected is not None
        assert selected.title == "Blade Runner"

        app.action_jump_alpha_previous()
        selected = await wait_for_selected_title(app, pilot, "Casablanca")
        assert selected is not None
        assert selected.title == "Casablanca"


async def run_alphabet_jump_load_more_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", page_size=2)
        library = LibraryItem("Movies", "1", "movie", object())
        items = [
            MediaItem("*batteries not included", "", "movie", "1", True, Raw()),
            MediaItem("8MM", "", "movie", "2", True, Raw()),
            MediaItem("Abigail", "", "movie", "3", True, Raw()),
            MediaItem("Bad Taste", "", "movie", "4", True, Raw()),
        ]
        page = MediaPage(
            [
                MediaItem("Batman", "", "movie", "5", True, Raw()),
                MediaItem("Children of Men", "", "movie", "6", True, Raw()),
            ],
            start=4,
            total=6,
        )
        service = FakePagedService(page)
        app.service = service
        app.browsing_stack = [BrowseState("Movies", items, library, next_start=4, total=6)]
        app.show_browse_state(app.browsing_stack[-1], selected_key="4")
        selected = await wait_for_selected_title(app, pilot, "Bad Taste")
        assert selected is not None
        assert selected.title == "Bad Taste"

        app.action_jump_alpha_next()
        selected = await wait_for_selected_title(app, pilot, "Children of Men")

        assert service.calls == [(library, 4, 2)]
        assert selected is not None
        assert selected.title == "Children of Men"
        assert [item.title for item in app.browsing_stack[-1].items] == [
            "*batteries not included",
            "8MM",
            "Abigail",
            "Bad Taste",
            "Batman",
            "Children of Men",
        ]


async def run_alphabet_jump_grid_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        items = [
            MediaItem("Alien", "", "movie", "1", True, Raw()),
            MediaItem("Aliens", "", "movie", "2", True, Raw()),
            MediaItem("Casablanca", "", "movie", "3", True, Raw()),
            MediaItem("Blade Runner", "", "movie", "4", True, Raw()),
        ]
        app.browsing_stack = [BrowseState("Movies", items)]
        app.show_browse_state(app.browsing_stack[-1])
        await pilot.pause(0.2)

        app.action_jump_alpha_next()
        await pilot.pause(0.2)
        grid = app.query_one("#media-grid")
        assert grid.selected_media.title == "Casablanca"

        app.action_jump_alpha_previous()
        await pilot.pause(0.2)
        assert grid.selected_media.title == "Alien"


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
            for item in items:
                app.rendered_grid_artwork_cache[grid_artwork_cache_key(item, app.config)] = f"art-{item.key}"
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


async def run_grid_prefetch_pages_ahead_check():
    app = PlexTuiApp()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        items = [
            MediaItem(f"Movie {index}", "", "movie", str(index), True, Raw(), artwork_path=f"/thumb/{index}")
            for index in range(40)
        ]
        scheduled = []

        def capture_prefetch(items, page_key, page_label, delay=0.0):
            scheduled.append((tuple(item.key for item in items), page_label, delay))
            for item in items:
                app.rendered_grid_artwork_cache[grid_artwork_cache_key(item, app.config)] = f"art-{item.key}"
            app.prefetched_grid_pages.add(page_key)
            app.active_grid_prefetch_pages.discard(page_key)

        app.prefetch_grid_items = capture_prefetch
        app.show_browse_state(BrowseState("Movies", items))
        await pilot.pause(0.2)

        assert [entry[1] for entry in scheduled[:4]] == ["current", "next-1", "next-2", "next-3"]
        assert [entry[2] for entry in scheduled[:4]] == [0.0, 0.0, 0.0, 0.0]


async def run_grid_prefetch_disabled_lookahead_check():
    app = PlexTuiApp()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid", grid_prefetch_pages=0)
        items = [
            MediaItem(f"Movie {index}", "", "movie", str(index), True, Raw(), artwork_path=f"/thumb/{index}")
            for index in range(40)
        ]
        scheduled = []

        def capture_prefetch(items, page_key, page_label, delay=0.0):
            scheduled.append((tuple(item.key for item in items), page_label, delay))
            for item in items:
                app.rendered_grid_artwork_cache[grid_artwork_cache_key(item, app.config)] = f"art-{item.key}"
            app.prefetched_grid_pages.add(page_key)
            app.active_grid_prefetch_pages.discard(page_key)

        app.prefetch_grid_items = capture_prefetch
        app.show_browse_state(BrowseState("Movies", items))
        await pilot.pause(0.2)

        assert [entry[1] for entry in scheduled] == ["current"]


async def run_cached_grid_prefetch_hydration_check():
    app = PlexTuiApp()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        items = [
            MediaItem(f"Movie {index}", "", "movie", str(index), True, Raw(), artwork_path=f"/thumb/{index}")
            for index in range(6)
        ]
        page_key = tuple(item.key for item in items)
        app.prefetched_grid_pages.add(page_key)
        app.rendered_grid_artwork_cache = {
            grid_artwork_cache_key(item, app.config): f"art-{item.key}"
            for item in items
        }
        app.show_browse_state(BrowseState("Movies", items))
        await pilot.pause(0.2)

        grid = app.query_one("#media-grid")
        visible_items = grid.visible_page_items()
        for item in visible_items:
            assert grid.artwork[item.key] == f"art-{item.key}"


async def run_stale_cached_grid_prefetch_refetch_check():
    app = PlexTuiApp()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        items = [
            MediaItem(f"Movie {index}", "", "movie", str(index), True, Raw(), artwork_path=f"/thumb/{index}")
            for index in range(2)
        ]
        page_key = tuple(item.key for item in items)
        app.prefetched_grid_pages.add(page_key)
        scheduled = []

        def capture_prefetch(items, page_key, page_label, delay=0.0):
            scheduled.append((tuple(item.key for item in items), page_key, page_label, delay))

        app.prefetch_grid_items = capture_prefetch
        app.show_browse_state(BrowseState("Movies", items))
        await pilot.pause(0.2)

        assert scheduled
        assert scheduled[0][1] == page_key
        assert scheduled[0][2] == "current"
        assert page_key not in app.prefetched_grid_pages


async def run_cold_grid_prefetch_application_check():
    app = PlexTuiApp()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        app.rendered_grid_artwork_cache = {}
        items = [
            MediaItem(f"Movie {index}", "", "movie", str(index), True, Raw(), artwork_path=f"/thumb/{index}")
            for index in range(6)
        ]

        def render_item(item, width, height):
            return item, f"art-{item.key}", 1.0, 1.0

        app.render_grid_prefetch_item = render_item
        app.show_browse_state(BrowseState("Movies", items))
        await pilot.pause(0.5)

        grid = app.query_one("#media-grid")
        for item in grid.visible_page_items():
            assert grid.artwork[item.key] == f"art-{item.key}"


async def run_same_grid_page_missing_artwork_retry_check():
    app = PlexTuiApp()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        items = [
            MediaItem(f"Movie {index}", "", "movie", str(index), True, Raw(), artwork_path=f"/thumb/{index}")
            for index in range(6)
        ]
        scheduled = []

        def capture_prefetch(items, page_key, page_label, delay=0.0):
            scheduled.append((tuple(item.key for item in items), page_key, page_label, delay))

        app.prefetch_grid_items = capture_prefetch
        app.show_browse_state(BrowseState("Movies", items))
        await pilot.pause(0.2)

        grid = app.query_one("#media-grid")
        page_key = grid_page_key(grid.visible_page_items())
        app.last_grid_prefetch_page = page_key
        app.active_grid_prefetch_pages.clear()
        scheduled.clear()

        app.schedule_grid_prefetch(grid)
        await pilot.pause(0.2)

        assert scheduled
        assert scheduled[0][1] == page_key
        assert scheduled[0][2] == "current"


async def run_grid_missing_artwork_render_schedule_check():
    app = PlexTuiApp()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        items = [
            MediaItem(f"Movie {index}", "", "movie", str(index), True, Raw(), artwork_path=f"/thumb/{index}")
            for index in range(6)
        ]
        scheduled = []

        def capture_prefetch(items, page_key, page_label, delay=0.0):
            scheduled.append((tuple(item.key for item in items), page_key, page_label, delay))

        app.prefetch_grid_items = capture_prefetch
        app.show_browse_state(BrowseState("Movies", items))
        await pilot.pause(0.2)
        grid = app.query_one("#media-grid")
        scheduled.clear()
        app.active_grid_prefetch_pages.clear()
        app.last_grid_prefetch_page = grid_page_key(grid.visible_page_items())
        grid.refresh_grid()
        await pilot.pause(0.2)

        assert scheduled
        assert scheduled[0][1] == grid_page_key(grid.visible_page_items())
        assert scheduled[0][2] == "current"


async def run_grid_prefetch_queue_check():
    app = PlexTuiApp()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        current_items = [
            MediaItem(f"Current {index}", "", "movie", f"c{index}", True, Raw(), artwork_path=f"/current/{index}")
            for index in range(3)
        ]
        next_items = [
            MediaItem(f"Next {index}", "", "movie", f"n{index}", True, Raw(), artwork_path=f"/next/{index}")
            for index in range(3)
        ]
        scheduled = []

        def capture_prefetch(items, page_key, page_label, delay=0.0):
            scheduled.append((tuple(item.key for item in items), page_key, page_label, delay))

        app.prefetch_grid_items = capture_prefetch
        app.active_grid_prefetch_pages.add(("active",))

        app.start_grid_prefetch(next_items, "next", delay=0.2)
        app.start_grid_prefetch(current_items, "current")

        assert scheduled == [(tuple(item.key for item in current_items), tuple(item.key for item in current_items), "current", 0.0)]
        assert [pending[2] for pending in app.pending_grid_prefetches] == ["next"]

        app.active_grid_prefetch_pages.clear()
        app.drain_grid_prefetch_queue()

        assert scheduled[1][2] == "next"
        assert scheduled[1][0] == tuple(item.key for item in next_items)


async def run_grid_prefetch_duplicate_pending_check():
    app = PlexTuiApp()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        items = [
            MediaItem(f"Next {index}", "", "movie", f"n{index}", True, Raw(), artwork_path=f"/next/{index}")
            for index in range(3)
        ]

        app.active_grid_prefetch_pages.add(("active",))
        app.start_grid_prefetch(items, "next-1")
        app.start_grid_prefetch(items, "next-1")

        assert [pending[2] for pending in app.pending_grid_prefetches] == ["next-1"]


async def run_grid_prefetch_current_in_flight_check():
    app = PlexTuiApp()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        items = [
            MediaItem(f"Movie {index}", "", "movie", str(index), True, Raw(), artwork_path=f"/thumb/{index}")
            for index in range(24)
        ]
        grid = app.show_media_grid()
        grid.set_items(items, 0, app.config, columns=3, rows=2)
        current_key = grid_page_key(grid.visible_page_items())
        app.active_grid_prefetch_pages.add(current_key)
        app.pending_grid_prefetches = []

        app.schedule_grid_prefetch(grid)

        assert app.pending_grid_prefetches == []


async def run_grid_prefetch_selected_priority_check():
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

        app.prefetch_grid_items = capture_prefetch
        app.show_browse_state(BrowseState("Movies", items), selected_key="2")
        await pilot.pause(0.2)

        grid = app.query_one("#media-grid")
        visible_page = tuple(item.key for item in grid.visible_page_items())

        assert scheduled[0][0][0] == "2"
        assert scheduled[0][1] == visible_page
        assert scheduled[0][2] == "current"


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
        await pilot.pause(0.2)
        assert refreshed == []

        app.show_media_details(items[2])
        await pilot.pause(0.45)
        assert refreshed == ["Movie 2"]


async def run_detail_artwork_idle_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="list")
        app.show_media_list()
        app.detail_refresh_token = 1
        full_item = MediaItem("Movie", "", "movie", "1", True, Raw(), artwork_path="/thumb")
        details = SimpleNamespace(artwork_path="/thumb")
        refreshed = []

        def capture_artwork(item, details, token, detail_size, include_card_artwork):
            refreshed.append((item.title, token, detail_size, include_card_artwork))

        callbacks = []

        def capture_timer(delay, callback, name=""):
            callbacks.append((delay, callback, name))
            return SimpleNamespace(stop=lambda: None)

        app.fetch_media_detail_artwork = capture_artwork
        with patch.object(app, "set_timer", capture_timer):
            app.schedule_media_detail_artwork_refresh(full_item, details, token=1)

        assert refreshed == []
        assert callbacks
        assert callbacks[0][0] > 0
        assert callbacks[0][2] == "detail-artwork-refresh"

        callbacks[0][1]()
        assert refreshed[0][0] == "Movie"
        assert refreshed[0][1] == 1
        assert refreshed[0][2] is not None
        assert not refreshed[0][3]


async def run_grid_detail_artwork_card_fetch_check():
    app = PlexTuiApp()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", media_view="grid")
        app.show_media_grid()
        app.detail_refresh_token = 1
        full_item = MediaItem("Movie", "", "movie", "1", True, Raw(), artwork_path="/thumb")
        details = SimpleNamespace(artwork_path="/thumb")
        refreshed = []
        callbacks = []

        def capture_artwork(item, details, token, detail_size, include_card_artwork):
            refreshed.append((item.title, token, detail_size, include_card_artwork))

        def capture_timer(delay, callback, name=""):
            callbacks.append((delay, callback, name))
            return SimpleNamespace(stop=lambda: None)

        app.fetch_media_detail_artwork = capture_artwork
        with patch.object(app, "set_timer", capture_timer):
            app.schedule_media_detail_artwork_refresh(full_item, details, token=1)

        assert refreshed == []
        assert callbacks == []


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
            playback_mode="transcode",
            transcode_quality="720p_4",
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
            app.run_settings_action("increase_grid_prefetch_pages")
            assert app.config.grid_prefetch_pages == 4
            app.run_settings_action("decrease_grid_prefetch_pages")
            assert app.config.grid_prefetch_pages == 3
            app.run_settings_action("reset_grid_prefetch_pages")
            assert app.config.grid_prefetch_pages == 3
            app.run_settings_action("reset_mpv_window_size")
            assert app.config.mpv_window_size == ""
            app.run_settings_action("cycle_grid_density")
            assert app.config.grid_density == "large"
            app.run_settings_action("cycle_artwork_renderer")
            assert app.config.artwork_renderer == "auto"
            app.run_settings_action("cycle_discover_media_type")
            assert app.config.discover_media_type == "movie"
            app.run_settings_action("toggle_confirm_start_over")
            assert app.config.confirm_start_over is False

        assert save_config.call_count == 17


async def run_stale_profile_load_check(monkeypatch):
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.profile_request_token = 2
        app.call_from_thread = lambda callback, *args: callback(*args)
        monkeypatch.setattr(
            app_module,
            "profile_choices",
            lambda config: [ProfileChoice("Old", "1", False, True)],
        )

        PlexTuiApp.load_profiles.__wrapped__(app, 1)
        await pilot.pause(0.2)

        assert app.query_one("#media-title").content != "Switch Profile"
        assert not any(isinstance(row, ProfileRow) for row in app.query_one("#media").children)


async def run_settings_library_visibility_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        movies = LibraryItem("Movies", "1", "movie", object())
        tv = LibraryItem("TV", "2", "show", object())
        app.config = AppConfig("http://plex", "token", "client-id")
        app.libraries = [movies, tv]
        app.populate_libraries(app.libraries)
        await pilot.pause(0.2)

        with patch("plextui.app.save_config") as save_config:
            app.run_settings_action("toggle_library_visibility:2")
            await pilot.pause(0.2)

        rows = list(app.query_one("#libraries").children)
        assert app.config.hidden_library_keys == ("2",)
        assert save_config.call_count == 1
        assert isinstance(rows[0], ContinueWatchingRow)
        assert isinstance(rows[1], PlaylistsRow)
        assert isinstance(rows[2], LibraryRow)
        assert rows[2].library.title == "Movies"
        assert isinstance(rows[3], PlexServicesRow)


async def run_settings_sidebar_entrypoint_visibility_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        movies = LibraryItem("Movies", "1", "movie", object())
        app.config = AppConfig("http://plex", "token", "client-id")
        app.libraries = [movies]
        app.populate_libraries(app.libraries)
        await pilot.pause(0.2)

        with patch("plextui.app.save_config") as save_config:
            app.run_settings_action("toggle_show_playlists")
            await pilot.pause(0.2)
            app.run_settings_action("toggle_show_discover")
            await pilot.pause(0.2)
            app.run_settings_action("toggle_show_on_plex")
            await pilot.pause(0.2)
            app.run_settings_action("toggle_show_on_plex_live")
            await pilot.pause(0.2)

        rows = list(app.query_one("#libraries").children)
        assert app.config.show_playlists is False
        assert app.config.show_discover is True
        assert app.config.show_on_plex is True
        assert app.config.show_on_plex_live is True
        assert save_config.call_count == 4
        assert isinstance(rows[0], ContinueWatchingRow)
        assert isinstance(rows[1], DiscoverRow)
        assert isinstance(rows[2], OnPlexRow)
        assert isinstance(rows[3], OnPlexLiveRow)
        assert isinstance(rows[4], LibraryRow)
        assert rows[4].library.title == "Movies"
        assert not any(isinstance(row, PlaylistsRow | PlexServicesRow) for row in rows)


async def run_plex_services_sidebar_opens_settings_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.libraries = [LibraryItem("Movies", "1", "movie", object())]
        app.populate_libraries(app.libraries)
        await pilot.pause(0.2)

        services_row = next(row for row in app.query_one("#libraries").children if isinstance(row, PlexServicesRow))
        app.query_one("#libraries").index = list(app.query_one("#libraries").children).index(services_row)
        app.on_list_view_selected(SimpleNamespace(item=services_row))
        await pilot.pause(0.2)

        assert app.settings_visible
        assert app.query_one("#media").highlighted_child is not None
        assert getattr(app.query_one("#media").highlighted_child, "action", "") == "toggle_show_discover"
        assert "Browse Plex Discover content" in app.query_one("#detail-content").content


async def run_settings_library_order_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        movies = LibraryItem("Movies", "1", "movie", object())
        tv = LibraryItem("TV", "2", "show", object())
        music = LibraryItem("Music", "3", "artist", object())
        app.config = AppConfig("http://plex", "token", "client-id")
        app.libraries = [movies, tv, music]
        app.populate_libraries(app.libraries)
        await pilot.pause(0.2)

        with patch("plextui.app.save_config") as save_config:
            app.run_settings_action("move_library_down:1")
            await pilot.pause(0.2)

        rows = list(app.query_one("#libraries").children)
        assert app.config.library_order_keys == ("2", "1", "3")
        assert save_config.call_count == 1
        assert isinstance(rows[0], ContinueWatchingRow)
        assert isinstance(rows[1], PlaylistsRow)
        assert [row.library.title for row in rows[2:5]] == ["TV", "Movies", "Music"]
        assert isinstance(rows[5], PlexServicesRow)

        media_rows = list(app.query_one("#media").children)
        selected = app.query_one("#media").highlighted_child
        selected_index = media_rows.index(selected)
        assert getattr(media_rows[selected_index], "action", "") == "move_library_down:1"


async def run_settings_recent_debug_log_check(tmp_path):
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        log = tmp_path / "debug.log"
        log.write_text("first\nsecond\nthird\n", encoding="utf-8")

        with patch("plextui.app.debug_log_path", return_value=log):
            app.run_settings_action("show_recent_debug_log")
        await pilot.pause(0.2)

        details = app.query_one("#detail-content").content
        assert "Recent Debug Log" in details
        assert f"Path: {log}" in details
        assert "first" in details
        assert "third" in details


async def run_settings_app_diagnostics_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")

        with patch("plextui.app.detect_mpv", return_value=("/usr/bin/mpv", "mpv 0.40.0")):
            app.run_settings_action("show_app_diagnostics")
        await pilot.pause(0.2)

        details = app.query_one("#detail-content").content
        assert "App Diagnostics" in details
        assert "Version:" in details
        assert "Server token: saved" in details
        assert "mpv: /usr/bin/mpv" in details
        assert "mpv version: mpv 0.40.0" in details


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

        assert app.query_one("#media-title").content == "Playback Error"
        details = app.query_one("#detail-content").content
        assert "mpv missing" in details
        assert f"Debug log: {log}" in details
        assert "playback error: mpv missing" in details


async def run_unavailable_vod_stream_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.show_media("Movies", [MediaItem("Special", "", "episode", "1", True, Raw())])
        await pilot.pause(0.2)

        with patch(
            "plextui.app.play_with_mpv",
            side_effect=PlayerError(
                "Plex lists this item, but does not provide a playable stream for external players"
            ),
        ):
            app.action_play_selected()
        await pilot.pause(0.2)

        assert app.query_one("#media-title").content == "Playback Unavailable"
        details = app.query_one("#detail-content").content
        assert "Special" in details
        assert "Plex lists this item, but does not provide a playable stream for external players" in details
        assert "Debug log:" not in details


async def run_playback_footer_check():
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
            playback_mode="transcode",
            transcode_quality="720p_4",
        )
        app.show_media("Movies", [MediaItem("Movie", "", "movie", "1", True, Raw())])
        await pilot.pause(0.2)

        player = SimpleNamespace(
            title="Movie",
            start_offset_ms=65_000,
            stream_mode="transcode",
            subtitle_count=2,
            process=SimpleNamespace(poll=lambda: None),
        )
        with patch("plextui.app.play_with_mpv", return_value=player) as launch:
            app.action_play_selected()
        await pilot.pause(0.2)

        assert launch.call_args.kwargs["window_size"] == "80%"
        assert launch.call_args.kwargs["playback_mode"] == "transcode"
        assert launch.call_args.kwargs["playback_display"] == "external"
        assert launch.call_args.kwargs["terminal_video_profile"] == "smooth"
        assert launch.call_args.kwargs["transcode_quality"] == "720p_4"
        assert launch.call_args.kwargs["resume"] is False
        footer = app.query_one("#playback-footer")
        assert footer.display
        assert footer.content == (
            "Playing Movie / resume 1:05 / mode transcode / quality 720p 4 Mbps / 2 subtitles / "
            "audio jpn not found, Plex/default; "
            "subtitles eng not found, Plex/default"
        )
        assert app.query_one("#status").content != footer.content


async def run_playback_controls_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        player = SimpleNamespace(
            title="Movie",
            process=SimpleNamespace(poll=lambda: None),
            active=True,
        )
        app.player = player

        with (
            patch("plextui.app.toggle_mpv_pause", return_value=True) as pause,
            patch("plextui.app.seek_mpv", return_value=True) as seek,
        ):
            app.action_toggle_playback_pause()
            app.action_seek_playback_backward()
            app.action_seek_playback_forward()

        pause.assert_called_once_with(player)
        assert seek.call_args_list[0].args == (player, -10)
        assert seek.call_args_list[1].args == (player, 30)
        assert app.query_one("#status").content == "Seeked Movie +30s"


async def run_playback_starts_from_beginning_check():
    class ResumableRaw(Raw):
        viewOffset = 65_000

    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", confirm_start_over=False)
        app.show_media("Movies", [MediaItem("Movie", "", "movie", "1", True, ResumableRaw())])
        await pilot.pause(0.2)

        player = SimpleNamespace(
            title="Movie",
            start_offset_ms=0,
            stream_mode="transcode",
            subtitle_count=0,
            process=SimpleNamespace(poll=lambda: None),
        )
        with patch("plextui.app.play_with_mpv", return_value=player) as launch:
            app.action_play_selected()
        await pilot.pause(0.2)

        assert launch.call_args.kwargs["resume"] is False
        assert "resume" not in app.query_one("#playback-footer").content


async def run_playback_start_over_prompt_check():
    class ResumableRaw(Raw):
        viewOffset = 65_000

    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.show_media("Movies", [MediaItem("Movie", "", "movie", "1", True, ResumableRaw())])
        await pilot.pause(0.2)

        player = SimpleNamespace(
            title="Movie",
            start_offset_ms=65_000,
            stream_mode="transcode",
            subtitle_count=0,
            process=SimpleNamespace(poll=lambda: None),
        )
        with patch("plextui.app.play_with_mpv", return_value=player) as launch:
            app.action_play_selected()
            await pilot.pause(0.2)

            assert not launch.called
            assert app.picker_visible
            assert app.query_one("#media-title").content == "Playback: Movie"
            assert [row.label_text for row in app.query_one("#media").children] == ["Resume", "Start over"]

            await pilot.press("enter")
            await pilot.pause(0.2)

        assert launch.call_args.kwargs["resume"] is True
        assert "resume 1:05" in app.query_one("#playback-footer").content


async def run_optimized_playback_action_check():
    class ResumableRaw(Raw):
        viewOffset = 65_000

    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", transcode_quality="720p_4")
        app.show_media("Movies", [MediaItem("Movie", "", "movie", "1", True, ResumableRaw())])
        await pilot.pause(0.2)

        player = SimpleNamespace(
            title="Movie",
            start_offset_ms=65_000,
            stream_mode="transcode",
            subtitle_count=0,
            process=SimpleNamespace(poll=lambda: None),
        )
        with patch("plextui.app.play_with_mpv", return_value=player) as launch:
            app.action_play_optimized()
        await pilot.pause(0.2)

        assert launch.call_args.kwargs["playback_mode"] == "transcode"
        assert launch.call_args.kwargs["transcode_quality"] == "720p_4"
        assert launch.call_args.kwargs["resume"] is True
        assert app.config.playback_mode == "auto"
        assert "mode transcode / quality 720p 4 Mbps" in app.query_one("#playback-footer").content


async def run_resume_action_check():
    class ResumableRaw(Raw):
        viewOffset = 65_000

    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.show_media("Movies", [MediaItem("Movie", "", "movie", "1", True, ResumableRaw())])
        await pilot.pause(0.2)

        player = SimpleNamespace(
            title="Movie",
            start_offset_ms=65_000,
            stream_mode="transcode",
            subtitle_count=0,
            process=SimpleNamespace(poll=lambda: None),
        )
        with patch("plextui.app.play_with_mpv", return_value=player) as launch:
            app.action_resume_selected()
        await pilot.pause(0.2)

        assert launch.call_args.kwargs["resume"] is True
        assert "resume 1:05" in app.query_one("#playback-footer").content


async def run_resume_key_check():
    class ResumableRaw(Raw):
        viewOffset = 65_000

    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.show_media("Movies", [MediaItem("Movie", "", "movie", "1", True, ResumableRaw())])
        await pilot.pause(0.2)

        player = SimpleNamespace(
            title="Movie",
            start_offset_ms=65_000,
            stream_mode="transcode",
            subtitle_count=0,
            process=SimpleNamespace(poll=lambda: None),
        )
        with patch("plextui.app.play_with_mpv", return_value=player) as launch:
            await pilot.press("r")
            await pilot.pause(0.2)

        assert launch.call_args.kwargs["resume"] is True
        assert "resume 1:05" in app.query_one("#playback-footer").content


async def run_resume_requires_position_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.show_media("Movies", [MediaItem("Movie", "", "movie", "1", True, Raw())])
        await pilot.pause(0.2)

        with patch("plextui.app.play_with_mpv") as launch:
            app.action_resume_selected()
        await pilot.pause(0.2)

        assert not launch.called
        assert app.query_one("#status").content == "No resume position for selected media; press p to play from the beginning"


async def run_start_over_picker_launch_check():
    class ResumableRaw(Raw):
        viewOffset = 65_000

    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.show_media("Movies", [MediaItem("Movie", "", "movie", "1", True, ResumableRaw())])
        await pilot.pause(0.2)

        player = SimpleNamespace(
            title="Movie",
            start_offset_ms=0,
            stream_mode="direct",
            subtitle_count=0,
            process=SimpleNamespace(poll=lambda: None),
        )
        with patch("plextui.app.play_with_mpv", return_value=player) as launch:
            app.action_play_selected()
            await pilot.pause(0.2)
            start_over = next(row for row in app.query_one("#media").children if getattr(row, "resume", True) is False)
            app.choose_resume_playback(start_over)
        await pilot.pause(0.2)

        assert launch.call_args.kwargs["resume"] is False
        assert not app.picker_visible


async def run_terminal_playback_low_transcode_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", playback_display="terminal")
        app.show_media("Movies", [MediaItem("Movie", "", "movie", "1", True, Raw())])
        await pilot.pause(0.2)

        player = SimpleNamespace(title="Movie", process=SimpleNamespace(poll=lambda: 0))
        with (
            patch.object(app, "play_terminal_media", return_value=player) as launch,
            patch.object(app, "refresh_current_browse_state"),
            patch.object(app, "show_media_details"),
        ):
            app.action_play_selected()
        await pilot.pause(0.2)

        playback_config = launch.call_args.args[4]
        assert playback_config.playback_mode == "transcode"
        assert playback_config.transcode_quality == "480p_2"


async def run_terminal_playback_online_metadata_direct_check():
    class MetadataServer:
        _baseurl = "https://metadata.provider.plex.tv"

    class OnlineRaw(Raw):
        _server = MetadataServer()

    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", playback_display="terminal")
        app.show_media("Movies", [MediaItem("Online Movie", "", "movie", "1", True, OnlineRaw())])
        await pilot.pause(0.2)

        player = SimpleNamespace(title="Online Movie", process=SimpleNamespace(poll=lambda: 0))
        with (
            patch.object(app, "play_terminal_media", return_value=player) as launch,
            patch.object(app, "refresh_current_browse_state"),
            patch.object(app, "show_media_details"),
        ):
            app.action_play_selected()
        await pilot.pause(0.2)

        playback_config = launch.call_args.args[4]
        assert playback_config.playback_mode == "auto"
        assert playback_config.transcode_quality == "original"


async def run_terminal_playback_exit_invalidates_grid_artwork_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        item = MediaItem("Movie", "", "movie", "1", True, Raw(), artwork_path="/thumb")
        app.config = AppConfig("http://plex", "token", "client-id", playback_display="terminal", media_view="grid")
        app.browsing_stack = [BrowseState("Movies", [item], source="continue_watching", total=1)]
        app.rendered_grid_artwork_cache = {"cached": object()}
        app.show_browse_state(app.browsing_stack[-1])
        grid = app.query_one("#media-grid", MediaGrid)
        grid.artwork = {item.key: object()}
        await pilot.pause(0.2)

        player = SimpleNamespace(title="Movie", process=SimpleNamespace(poll=lambda: 0))
        with (
            patch.object(app, "play_terminal_media", return_value=player),
            patch.object(app, "refresh_current_browse_state"),
            patch.object(app, "show_media_details"),
        ):
            app.action_play_selected()
        await pilot.pause(0.2)

        assert app.rendered_grid_artwork_cache == {}
        assert grid.artwork == {}


class WatchStateRaw(Raw):
    duration = 600000

    def __init__(self, view_count: int = 0, view_offset: int = 0):
        self.viewCount = view_count
        self.viewOffset = view_offset
        self.mark_watched_calls = 0
        self.mark_unwatched_calls = 0

    def markWatched(self):
        self.mark_watched_calls += 1
        self.viewCount = 1
        self.viewOffset = 0
        return self

    def markUnwatched(self):
        self.mark_unwatched_calls += 1
        self.viewCount = 0
        self.viewOffset = 0
        return self

    def isWatched(self):
        return bool(self.viewCount)


class ContinueWatchingRaw(Raw):
    def __init__(self):
        self.remove_calls = 0

    def removeFromContinueWatching(self):
        self.remove_calls += 1


async def run_toggle_watched_marks_unwatched_check():
    raw = WatchStateRaw(view_offset=65_000)
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.show_media("Movies", [MediaItem("Movie", "", "movie", "1", True, raw)])
        await pilot.pause(0.2)

        worker = app.action_toggle_watched()
        assert worker is not None
        row, selected, status = await wait_for_watched_update(
            app,
            pilot,
            raw,
            watched=True,
            expected_status="Marked Movie watched",
        )

        assert raw.mark_watched_calls == 1
        assert raw.mark_unwatched_calls == 0
        assert selected is not None
        assert selected.raw.viewCount == 1
        assert row is not None
        assert "[########] 100%" in row.label_text
        assert status == "Marked Movie watched"


async def run_toggle_watched_continue_watching_refresh_check():
    raw = WatchStateRaw(view_offset=65_000)
    next_raw = WatchStateRaw(view_offset=1)
    current = MediaItem("Episode 1", "", "episode", "episode-1", True, raw)
    next_episode = MediaItem("Episode 2", "", "episode", "episode-2", True, next_raw)
    service = FakePagedService(MediaPage([next_episode], start=0, total=1))
    service.media_by_key = {"episode-1": raw}
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.service = service
        app.browsing_stack = [BrowseState("Continue Watching", [current], source="continue_watching", total=1)]
        app.show_browse_state(app.browsing_stack[-1])
        selected = await wait_for_selected_title(app, pilot, "Episode 1", attempts=80)
        assert selected is not None

        app.action_toggle_watched()

        status = await wait_for_status(app, pilot, "Marked Episode 1 watched", attempts=80)
        titles = await wait_for_browse_titles(app, pilot, ["Episode 2"], attempts=80)

        assert service.continue_watching_calls[-1] == (0, 40)
        assert titles == ["Episode 2"]
        assert status == "Marked Episode 1 watched"


async def run_toggle_watched_continue_watching_refresh_resolves_hub_wrapper_check():
    class WrappedEpisodeRaw:
        TYPE = "episode"
        title = "Episode 1"
        ratingKey = "episode-1"

    class ResolvedEpisodeRaw(WatchStateRaw):
        TYPE = "episode"

    current_raw = WrappedEpisodeRaw()
    current = MediaItem("Episode 1", "", "episode", "episode-1", True, current_raw)
    next_raw = WatchStateRaw(view_offset=1)
    next_episode = MediaItem("Episode 2", "", "episode", "episode-2", True, next_raw)
    resolved_current = ResolvedEpisodeRaw(view_offset=65_000)
    service = FakePagedService(MediaPage([next_episode], start=0, total=1))
    service.media_by_key = {"episode-1": resolved_current}
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.service = service
        app.browsing_stack = [BrowseState("Continue Watching", [current], source="continue_watching", total=1)]
        app.show_browse_state(app.browsing_stack[-1])
        selected = await wait_for_selected_title(app, pilot, "Episode 1", attempts=80)
        assert selected is not None

        app.action_toggle_watched()

        status = str(app.query_one("#status").content)
        selected = app.selected_media()
        titles = [item.title for item in app.browsing_stack[-1].items]
        for _ in range(180):
            status = str(app.query_one("#status").content)
            selected = app.selected_media()
            titles = [item.title for item in app.browsing_stack[-1].items]
            if (
                service.media_from_key_calls == ["episode-1"]
                and resolved_current.mark_watched_calls == 1
                and service.continue_watching_calls[-1:] == [(0, 40)]
                and titles == ["Episode 2"]
                and selected is not None
                and selected.title == "Episode 2"
                and status == "Marked Episode 1 watched"
            ):
                break
            await pilot.pause(0.1)
        else:
            raise AssertionError(
                "Timed out waiting for Continue Watching hub-wrapper refresh: "
                f"media_from_key_calls={service.media_from_key_calls!r}, "
                f"mark_watched_calls={resolved_current.mark_watched_calls!r}, "
                f"continue_watching_calls={service.continue_watching_calls!r}, "
                f"titles={titles!r}, selected={selected!r}, status={status!r}"
            )


async def run_playback_refresh_selects_next_continue_watching_episode_check():
    current_raw = SimpleNamespace(TYPE="episode", grandparentKey="/library/metadata/show-1")
    next_raw = SimpleNamespace(TYPE="episode", grandparentKey="/library/metadata/show-1")
    current = MediaItem("Episode 1", "", "episode", "episode-1", True, current_raw)
    next_episode = MediaItem("Episode 2", "", "episode", "episode-2", True, next_raw)
    service = FakePagedService(MediaPage([next_episode], start=0, total=1))
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.service = service
        app.browsing_stack = [BrowseState("Continue Watching", [current], source="continue_watching", total=1)]
        app.show_browse_state(app.browsing_stack[-1])
        await pilot.pause(0.2)

        worker = app.refresh_current_browse_state(selected_key=current.key, played_media=current)
        assert worker is not None
        await asyncio.wait_for(worker.wait(), timeout=20)

        selected = await wait_for_selected_title(app, pilot, "Episode 2", attempts=80)

        assert service.continue_watching_calls[-1] == (0, 40)
        assert selected is not None
        assert selected.title == "Episode 2"


async def run_open_parent_context_from_continue_watching_episode_check():
    episode_raw = SimpleNamespace(TYPE="episode", parentKey="/library/metadata/season-1", grandparentKey="/library/metadata/show-1")
    episode = MediaItem("Episode 2", "", "episode", "episode-2", True, episode_raw)
    season = MediaItem("Season 1", "10 episodes", "season", "season-1", False, SimpleNamespace(TYPE="season"))
    previous = MediaItem("Episode 1", "", "episode", "episode-1", True, SimpleNamespace(TYPE="episode"))
    service = FakePagedService(MediaPage([episode], start=0, total=1))
    service.media_by_key = {"/library/metadata/season-1": season}
    service.children_by_key = {"season-1": [previous, episode]}
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.service = service
        app.browsing_stack = [BrowseState("Continue Watching", [episode], source="continue_watching", total=1)]
        app.show_browse_state(app.browsing_stack[-1])
        await pilot.pause(0.2)

        await pilot.press("b")
        children_calls = await wait_for_calls(service.children_calls, pilot, attempts=80)
        selected = await wait_for_selected_title(app, pilot, "Episode 1", attempts=80)

        assert service.media_from_key_calls == ["/library/metadata/season-1"]
        assert children_calls == [("season-1", 40)]
        assert app.browsing_stack[-1].title == "Season 1"
        assert selected is not None


async def run_open_show_context_from_continue_watching_episode_check():
    episode_raw = SimpleNamespace(TYPE="episode", parentKey="/library/metadata/season-1", grandparentKey="/library/metadata/show-1")
    episode = MediaItem("Episode 2", "", "episode", "episode-2", True, episode_raw)
    show = MediaItem("Berserk", "TV Show", "show", "show-1", False, SimpleNamespace(TYPE="show"))
    season = MediaItem("Season 1", "10 episodes", "season", "season-1", False, SimpleNamespace(TYPE="season"))
    service = FakePagedService(MediaPage([episode], start=0, total=1))
    service.media_by_key = {"/library/metadata/show-1": show}
    service.children_by_key = {"show-1": [season]}
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.service = service
        app.browsing_stack = [BrowseState("Continue Watching", [episode], source="continue_watching", total=1)]
        app.show_browse_state(app.browsing_stack[-1])
        await pilot.pause(0.2)

        await pilot.press("B")
        children_calls = await wait_for_calls(service.children_calls, pilot, attempts=80)
        selected = await wait_for_selected_title(app, pilot, "Season 1", attempts=80)

        assert service.media_from_key_calls == ["/library/metadata/show-1"]
        assert children_calls == [("show-1", 40)]
        assert app.browsing_stack[-1].title == "Berserk"
        assert selected is not None


async def run_toggle_watched_marks_watched_check():
    raw = WatchStateRaw(view_count=1)
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.show_media("Movies", [MediaItem("Movie", "", "movie", "1", True, raw)])
        await pilot.pause(0.2)

        app.action_toggle_watched()
        row, selected, status = await wait_for_watched_update(
            app,
            pilot,
            raw,
            watched=False,
            expected_status="Marked Movie unwatched",
        )

        assert raw.mark_watched_calls == 0
        assert raw.mark_unwatched_calls == 1
        assert selected is not None
        assert selected.raw.viewCount == 0
        assert row is not None
        assert "[########] 100%" not in row.label_text
        assert status == "Marked Movie unwatched"


async def run_toggle_watched_unsupported_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.show_media("Movies", [MediaItem("Movie", "", "movie", "1", True, Raw())])
        await pilot.pause(0.2)

        app.action_toggle_watched()
        status = await wait_for_status(
            app,
            pilot,
            "Selected item does not support watched state changes",
            attempts=80,
        )

        assert status == "Selected item does not support watched state changes"


class PlaylistService:
    def __init__(self) -> None:
        self.playlist = MediaItem("Favorites", "", "playlist", "playlist-1", False, Raw())
        self.add_calls = []
        self.create_calls = []
        self.remove_calls = []
        self.rename_calls = []
        self.delete_calls = []

    def playlists(self):
        return [self.playlist]

    def add_to_playlist(self, playlist, item):
        return self.add_items_to_playlist(playlist, [item])

    def add_items_to_playlist(self, playlist, items):
        self.add_calls.append((playlist.title, [item.title for item in items]))
        return playlist

    def create_playlist(self, title, item):
        return self.create_playlist_from_items(title, [item])

    def create_playlist_from_items(self, title, items):
        self.create_calls.append((title, [item.title for item in items]))
        return MediaItem(title, "", "playlist", "playlist-new", False, Raw())

    def remove_from_playlist(self, playlist, item):
        return self.remove_items_from_playlist(playlist, [item])

    def remove_items_from_playlist(self, playlist, items):
        self.remove_calls.append((playlist.title, [item.title for item in items]))
        return playlist

    def rename_playlist(self, playlist, title):
        self.rename_calls.append((playlist.title, title))
        self.playlist = MediaItem(title, "", "playlist", playlist.key, False, playlist.raw)
        return self.playlist

    def delete_playlist(self, playlist):
        self.delete_calls.append(playlist.title)


async def run_add_to_playlist_existing_check():
    service = PlaylistService()
    item = MediaItem("Movie", "", "movie", "1", True, Raw())
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.service = service
        app.show_media("Movies", [item])
        selected = await wait_for_selected_title(app, pilot, "Movie")
        assert selected is item

        worker = app.action_add_to_playlist()
        assert worker is not None
        await asyncio.wait_for(worker.wait(), timeout=20)
        rows = await wait_for_playlist_target_rows(app, pilot)
        target = next(row for row in rows if isinstance(row, PlaylistTargetRow))
        worker = app.choose_playlist_target(target.playlist)
        assert worker is not None
        await asyncio.wait_for(worker.wait(), timeout=20)
        add_calls, status = await wait_for_playlist_result(
            app,
            pilot,
            service.add_calls,
            expected_calls=[("Favorites", ["Movie"])],
            expected_status="Added Movie to Favorites",
        )

        assert add_calls == [("Favorites", ["Movie"])]
        assert status == "Added Movie to Favorites"
        assert not app.picker_visible


async def run_add_to_playlist_create_check():
    service = PlaylistService()
    item = MediaItem("Movie", "", "movie", "1", True, Raw())
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.service = service
        app.show_media("Movies", [item])
        await pilot.pause(0.2)

        worker = app.action_add_to_playlist()
        assert worker is not None
        await asyncio.wait_for(worker.wait(), timeout=20)
        rows = await wait_for_playlist_rows(app, pilot)
        assert any(isinstance(row, PlaylistCreateRow) for row in rows)
        worker = app.save_playlist_name_input("Weekend")
        assert worker is not None
        await asyncio.wait_for(worker.wait(), timeout=20)
        create_calls, status = await wait_for_playlist_result(
            app,
            pilot,
            service.create_calls,
            expected_calls=[("Weekend", ["Movie"])],
            expected_status="Created playlist Weekend with Movie",
        )

        assert create_calls == [("Weekend", ["Movie"])]
        assert status == "Created playlist Weekend with Movie"
        assert not app.picker_visible


async def run_remove_playlist_item_check():
    service = PlaylistService()
    playlist = service.playlist
    first = MediaItem("Movie", "", "movie", "1", True, Raw())
    second = MediaItem("Second", "", "movie", "2", True, Raw())
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.service = service
        app.browsing_stack = [BrowseState("Favorites", [first, second], source="playlist", context_media=playlist, total=2)]
        app.show_browse_state(app.browsing_stack[-1])
        await pilot.pause(0.2)

        app.action_remove_continue_watching()
        status = await wait_for_status(app, pilot, "Removed Movie from Favorites")

        assert service.remove_calls == [("Favorites", ["Movie"])]
        assert [item.title for item in app.browsing_stack[-1].items] == ["Second"]
        assert app.selected_media() is not None
        assert app.selected_media().title == "Second"
        assert status == "Removed Movie from Favorites"


async def run_playlist_browse_remove_hint_check():
    playlist = MediaItem("Favorites", "", "playlist", "playlist-1", False, Raw())
    item = MediaItem("Movie", "", "movie", "1", True, Raw())
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.browsing_stack = [BrowseState("Favorites", [item], source="playlist", context_media=playlist, total=1)]
        app.show_browse_state(app.browsing_stack[-1])
        await pilot.pause(0.2)

        assert "Playlist: Backspace/Delete removes from this playlist" in app.query_one("#detail-content").content
        assert "Backspace/Delete remove from playlist" in app.query_one("#status").content


async def run_bulk_add_to_playlist_check():
    service = PlaylistService()
    first = MediaItem("Movie", "", "movie", "1", True, Raw())
    second = MediaItem("Second", "", "movie", "2", True, Raw())
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.service = service
        app.browsing_stack = [BrowseState("Movies", [first, second], total=2)]
        app.show_browse_state(app.browsing_stack[-1])
        await pilot.pause(0.2)

        app.action_toggle_bulk_selection()
        await pilot.pause(0.2)
        app.query_one("#media").index = 1
        selected = await wait_for_selected_title(app, pilot, "Second")
        assert selected is not None
        app.action_toggle_bulk_selection()
        await pilot.pause(0.2)
        worker = app.action_add_to_playlist()
        assert worker is not None
        await asyncio.wait_for(worker.wait(), timeout=20)
        rows = await wait_for_playlist_target_rows(app, pilot)
        target = next(row for row in rows if isinstance(row, PlaylistTargetRow))
        worker = app.choose_playlist_target(target.playlist)
        assert worker is not None
        await asyncio.wait_for(worker.wait(), timeout=20)
        add_calls, status = await wait_for_playlist_result(
            app,
            pilot,
            service.add_calls,
            expected_calls=[("Favorites", ["Movie", "Second"])],
            expected_status="Added 2 selected items to Favorites",
        )

        assert add_calls == [("Favorites", ["Movie", "Second"])]
        assert status == "Added 2 selected items to Favorites"
        assert not app.bulk_selected_keys


async def run_bulk_remove_from_playlist_check():
    service = PlaylistService()
    playlist = service.playlist
    first = MediaItem("Movie", "", "movie", "1", True, Raw())
    second = MediaItem("Second", "", "movie", "2", True, Raw())
    third = MediaItem("Third", "", "movie", "3", True, Raw())
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.service = service
        app.browsing_stack = [BrowseState("Favorites", [first, second, third], source="playlist", context_media=playlist, total=3)]
        app.show_browse_state(app.browsing_stack[-1])
        await pilot.pause(0.2)

        app.action_toggle_bulk_selection()
        await pilot.pause(0.2)
        app.query_one("#media").index = 1
        selected = await wait_for_selected_title(app, pilot, "Second")
        assert selected is not None
        app.action_toggle_bulk_selection()
        await pilot.pause(0.2)
        app.action_remove_continue_watching()
        for _ in range(80):
            if service.remove_calls == [("Favorites", ["Movie", "Second"])] and [item.title for item in app.browsing_stack[-1].items] == ["Third"]:
                break
            await pilot.pause(0.1)

        assert service.remove_calls == [("Favorites", ["Movie", "Second"])]
        assert [item.title for item in app.browsing_stack[-1].items] == ["Third"]
        assert not app.bulk_selected_keys


async def run_rename_playlist_check():
    service = PlaylistService()
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.service = service
        app.browsing_stack = [BrowseState("Playlists", [service.playlist], source="playlists", total=1)]
        app.show_browse_state(app.browsing_stack[-1])
        await pilot.pause(0.2)

        app.action_rename_playlist()
        worker = app.save_playlist_rename_input("Road Trip")
        assert worker is not None
        await asyncio.wait_for(worker.wait(), timeout=20)

        assert service.rename_calls == [("Favorites", "Road Trip")]
        assert [item.title for item in app.browsing_stack[-1].items] == ["Road Trip"]
        status = await wait_for_status(app, pilot, "Renamed playlist to Road Trip")
        assert status == "Renamed playlist to Road Trip"


async def run_delete_playlist_check():
    service = PlaylistService()
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.service = service
        app.browsing_stack = [BrowseState("Playlists", [service.playlist], source="playlists", total=1)]
        app.show_browse_state(app.browsing_stack[-1])
        await pilot.pause(0.2)

        app.action_delete_playlist()
        assert app.pending_confirmation_action == "delete_playlist:playlist-1"
        worker = app.action_delete_playlist()
        assert worker is not None
        await asyncio.wait_for(worker.wait(), timeout=20)

        assert service.delete_calls == ["Favorites"]
        assert app.browsing_stack[-1].items == []
        status = await wait_for_status(app, pilot, "Deleted playlist Favorites")
        assert status == "Deleted playlist Favorites"


async def run_remove_continue_watching_check():
    raw = ContinueWatchingRaw()
    removed = MediaItem("Movie", "", "movie", "1", True, raw)
    remaining = MediaItem("Second", "", "movie", "2", True, Raw())
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.browsing_stack = [
            BrowseState("Continue Watching", [removed, remaining], source="continue_watching", next_start=2, total=2)
        ]
        app.show_browse_state(app.browsing_stack[-1])
        await pilot.pause(0.2)

        app.action_remove_continue_watching()
        for _ in range(80):
            if raw.remove_calls == 1 and [item.title for item in app.browsing_stack[-1].items] == ["Second"]:
                break
            await pilot.pause(0.1)

        assert raw.remove_calls == 1
        assert [item.title for item in app.browsing_stack[-1].items] == ["Second"]
        assert app.selected_media() is not None
        assert app.selected_media().title == "Second"


async def run_remove_continue_watching_requires_view_check():
    raw = ContinueWatchingRaw()
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id")
        app.browsing_stack = [BrowseState("Movies", [MediaItem("Movie", "", "movie", "1", True, raw)])]
        app.show_browse_state(app.browsing_stack[-1])
        await pilot.pause(0.2)

        app.action_remove_continue_watching()
        await pilot.pause(0.2)

        assert raw.remove_calls == 0
        assert app.query_one("#status").content == "Open Continue Watching or a playlist before removing an item"


async def run_stream_picker_live_switch_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        item = MediaItem("Movie", "", "movie", "1", True, Raw())
        choice = StreamChoice(0, "None (disable subtitles)")
        app.config = AppConfig("http://plex", "token", "client-id")
        app.browsing_stack = [BrowseState("Movies", [item])]
        app.show_browse_state(app.browsing_stack[-1])
        app.player = SimpleNamespace(active=True, title="Movie")
        app.picker_media_key = "1"
        app.picker_visible = True
        await pilot.pause(0.2)

        with (
            patch("plextui.app.save_config"),
            patch("plextui.app.switch_mpv_stream", return_value=True) as switch,
        ):
            app.choose_stream(choice, "subtitle")

        expected_status = "Subtitle preference: None (disable subtitles) / active playback updated"
        status = await wait_for_status(app, pilot, expected_status)
        switch.assert_called_once_with(app.player, item.raw, choice, "subtitle")
        assert status == expected_status
        assert app.query_one("#playback-footer").content == (
            "Movie: subtitle None (disable subtitles)"
        )


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
            assert app.config.mpv_window_size == "80%"
            app.config = replace(app.config, mpv_window_size="1280x720")
            app.action_cycle_mpv_window_size()
            assert app.config.mpv_window_size == ""

        assert save_config.call_count == 5


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
        app.config = AppConfig("http://plex", "token", "client-id", page_size=40, auto_load_threshold=10, grid_prefetch_pages=3)

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
            app.save_numeric_setting_input("grid_prefetch_pages", "Grid prefetch pages", "5", 0, 5, 3)
            assert app.config.grid_prefetch_pages == 5
            app.save_numeric_setting_input("grid_prefetch_pages", "Grid prefetch pages", "", 0, 5, 3)
            assert app.config.grid_prefetch_pages == 3

        assert save_config.call_count == 6


async def run_numeric_settings_left_right_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", page_size=80)
        app.action_show_settings(selected_action="set_page_size")
        await pilot.pause(0.2)

        with patch("plextui.app.save_config") as save_config:
            app.action_grid_right()
            assert app.config.page_size == 90
            app.action_grid_left()
            assert app.config.page_size == 80

        await pilot.pause(0.2)
        assert save_config.call_count == 2
        assert app.settings_visible
        assert app.query_one("#media-title").content == "Settings"


async def run_option_settings_left_right_check():
    app = PlexTuiApp()
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
        app.config = AppConfig("http://plex", "token", "client-id", grid_density="comfortable")
        app.action_show_settings(selected_action="cycle_grid_density")
        await pilot.pause(0.2)

        with patch("plextui.app.save_config") as save_config:
            app.action_grid_right()
            assert app.config.grid_density == "large"
            app.action_grid_left()
            assert app.config.grid_density == "compact"

        await pilot.pause(0.2)
        assert save_config.call_count == 2
        assert app.settings_visible
        assert app.query_one("#media-title").content == "Settings"


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
        assert getattr(row, "label_text") == "Account"
        assert "Settings Section" in app.query_one("#detail-content").content

        option_actions = [
            "cycle_subtitle_mode",
            "cycle_playback_mode",
            "cycle_terminal_video_profile",
            "cycle_transcode_quality",
            "cycle_mpv_window_size",
            "toggle_artwork",
            "cycle_detail_artwork",
            "cycle_artwork_renderer",
            "toggle_media_view",
            "cycle_grid_density",
        ]
        for action in option_actions:
            with patch("plextui.app.save_config"):
                app.run_settings_action(action)
            await pilot.pause(0.2)

            row = media.highlighted_child
            assert row is not None
            assert row.has_class("active-row")
            assert getattr(row, "action") == action


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
        app.set_playback_footer("Playing Movie")

        app.check_player_status()
        await pilot.pause(0.1)

        assert app.player is None
        assert app.query_one("#status").content == "Playback ended: Movie"
        assert not app.query_one("#playback-footer").display
        assert app.query_one("#playback-footer").content == ""
        assert refreshed == [item]
