from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from plextui.app import BrowseState, PlexTuiApp
from plextui.config import AppConfig
from plextui.models import LibraryItem, MediaItem
from plextui.plex_service import MediaPage


def media(key, kind="movie"):
    return MediaItem(key, "", kind, key, kind == "movie", SimpleNamespace(TYPE=kind))


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr("plextui.config.debug_log_path", lambda: tmp_path / "debug.log")
    app = PlexTuiApp()
    app.config = AppConfig("http://plex", "token", "client-id")
    app.browsing_stack = []
    app.bulk_selected_keys = set()
    app.detail_cache = {}
    app.help_visible = app.settings_visible = app.picker_visible = app.playlist_picker_visible = False
    app.input_mode = ""
    app.playlist_picker_item = None
    app.search_token = 0
    app.navigation_token = 0
    app.navigation_worker = None
    app.loading_more = False
    app.call_from_thread = lambda callback, *args: callback(*args)
    for name in ("show_browse_state", "focus_media_browser", "set_status", "set_timer",
                 "show_error", "show_detail_text", "show_load_more_feedback", "post_message"):
        monkeypatch.setattr(app, name, Mock())
    app.selected_media = lambda: app.current_browse_state().items[0] if app.current_browse_state().items else None
    return app


def delayed_result(app, method, service_method, result, navigate, *args, error=False):
    started, release = Event(), Event()

    def request(*_args, **_kwargs):
        started.set()
        assert release.wait(5)
        if error:
            raise RuntimeError("delayed failure")
        return result

    app.service = SimpleNamespace(**{service_method: request})
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(method.__wrapped__, app, *args)
        try:
            assert started.wait(3)
            navigate()
        finally:
            release.set()
        future.result(timeout=5)


@pytest.mark.parametrize("overlay", ["settings_visible", "help_visible", "picker_visible", "playlist_picker_visible"])
@pytest.mark.parametrize("error", [False, True])
def test_playback_refresh_preserves_open_overlay(app, overlay, error):
    old, fresh = media("old"), media("fresh")
    library = LibraryItem("Movies", "movies", "movie", object())
    state = BrowseState("Movies", [old], library, source="library:library", next_start=1, total=1)
    app.browsing_stack = [state]
    delayed_result(app, PlexTuiApp.refresh_current_browse_state, "library_entry_page",
                   MediaPage([fresh], start=0, total=1), lambda: setattr(app, overlay, True), error=error)
    assert app.current_browse_state() is state
    assert state.items == ([old] if error else [fresh])
    app.show_browse_state.assert_not_called()
    app.focus_media_browser.assert_not_called()
    app.show_error.assert_not_called()


def test_playback_refresh_still_repaints_current_browse_view(app):
    fresh = media("fresh")
    state = BrowseState("Continue Watching", [media("old")], source="continue_watching", next_start=1, total=1)
    app.browsing_stack = [state]
    delayed_result(app, PlexTuiApp.refresh_current_browse_state, "continue_watching_page",
                   MediaPage([fresh], start=0, total=1), lambda: None)
    assert state.items == [fresh]
    app.show_browse_state.assert_called_once_with(state, selected_key=None)
    app.focus_media_browser.assert_called_once()


@pytest.mark.parametrize("destination", ["other_playlist", "settings", "new_rename"])
def test_delayed_playlist_rename_preserves_current_context(app, destination):
    a, b = media("Playlist A", "playlist"), media("Playlist B", "playlist")
    shared = media("shared")
    parent = BrowseState("Playlists", [a, b], source="playlists", total=2)
    original = BrowseState(a.title, [shared], source="playlist", context_media=a, total=1)
    newer = BrowseState(b.title, [shared, media("b-only")], source="playlist", context_media=b, total=2)
    app.browsing_stack = [parent, original]
    app.playlist_picker_item = a
    renamed = replace(a, title="Renamed A")

    def navigate():
        if destination == "other_playlist":
            app.browsing_stack.append(newer)
        else:
            app.settings_visible = destination == "settings"
            if destination == "new_rename":
                app.playlist_picker_item = b
                app.input_mode = "playlist_rename"

    delayed_result(app, PlexTuiApp.rename_playlist, "rename_playlist", renamed, navigate, a, renamed.title)
    assert parent.items == [renamed, b]
    assert original.context_media is renamed
    assert original.title == renamed.title
    if destination == "other_playlist":
        assert app.playlist_action_target() is b
        assert newer.title == b.title
        assert newer.items == [shared, media("b-only")]
    elif destination == "new_rename":
        assert app.playlist_picker_item is b
    app.show_browse_state.assert_not_called()
    app.focus_media_browser.assert_not_called()


def test_current_playlist_rename_preserves_selected_media(app):
    playlist = media("Playlist", "playlist")
    selected = media("selected")
    state = BrowseState(playlist.title, [selected], source="playlist", context_media=playlist, total=1)
    app.browsing_stack = [state]
    renamed = replace(playlist, title="Renamed")
    app.apply_playlist_rename(playlist, renamed)
    assert app.playlist_action_target() is renamed
    assert state.title == renamed.title
    app.show_browse_state.assert_called_once_with(
        state, selected_key=selected.key, status_after_refresh="Renamed playlist to Renamed",
    )


@pytest.mark.parametrize("destination", ["other_playlist", "settings"])
def test_delayed_playlist_removal_updates_only_its_playlist(app, destination):
    a, b = media("Playlist A", "playlist"), media("Playlist B", "playlist")
    shared, remaining = media("shared"), media("remaining")
    original = BrowseState(a.title, [shared, remaining], source="playlist", context_media=a, total=2)
    newer = BrowseState(b.title, [shared, remaining], source="playlist", context_media=b, total=2)
    app.browsing_stack = [original]

    def navigate():
        if destination == "other_playlist":
            app.browsing_stack.append(newer)
        else:
            app.settings_visible = True

    delayed_result(app, PlexTuiApp.remove_playlist_items, "remove_items_from_playlist",
                   None, navigate, a, [shared])
    assert original.items == [remaining]
    assert original.total == 1
    assert newer.items == [shared, remaining]
    assert newer.total == 2
    app.show_browse_state.assert_not_called()
    app.focus_media_browser.assert_not_called()


def test_playlist_removal_does_not_decrement_twice(app):
    playlist = media("Playlist", "playlist")
    removed, remaining = media("removed"), media("remaining")
    state = BrowseState(playlist.title, [removed, remaining], source="playlist", context_media=playlist, total=2)
    app.browsing_stack = [state]
    app.apply_playlist_removal(playlist, [removed])
    app.apply_playlist_removal(playlist, [removed])
    assert state.items == [remaining]
    assert state.total == 1


@pytest.mark.parametrize("destination", ["library", "new_continue_watching", "settings", "back", "unchanged"])
@pytest.mark.parametrize("error", [False, True])
def test_watched_refresh_respects_navigation_identity(app, destination, error):
    watched, fresh = media("watched"), media("fresh")
    original = BrowseState("Continue Watching", [watched], source="continue_watching", next_start=1, total=1)
    app.browsing_stack = [original]
    newer = BrowseState("New view", [media("other")], source=(
        "continue_watching" if destination == "new_continue_watching" else "library:library"
    ))

    def navigate():
        if destination == "unchanged":
            return
        app.invalidate_navigation_results()
        if destination in {"library", "new_continue_watching"}:
            app.browsing_stack = [newer]
        elif destination == "settings":
            app.settings_visible = True
        # Back can return to the identical state object; its older result is stale.

    delayed_result(app, PlexTuiApp.refresh_continue_watching_after_watched, "continue_watching_page",
                   MediaPage([fresh], start=0, total=1), navigate, watched, original, app.navigation_token, error=error)
    if destination == "unchanged":
        if error:
            app.show_error.assert_called_once()
        else:
            assert app.current_browse_state().items == [fresh]
            app.show_browse_state.assert_called_once()
    else:
        assert app.current_browse_state() is (newer if destination in {"library", "new_continue_watching"} else original)
        app.show_browse_state.assert_not_called()
        app.focus_media_browser.assert_not_called()
        app.show_error.assert_not_called()


def test_delayed_watched_mutation_does_not_refresh_a_new_view(app, monkeypatch):
    watched = media("watched")
    watched.raw.markWatched = lambda: app.service.mark_watched()
    original = BrowseState("Continue Watching", [watched], source="continue_watching")
    newer = BrowseState("Continue Watching", [media("other")], source="continue_watching")
    app.browsing_stack = [original]
    refresh = Mock()
    monkeypatch.setattr(app, "refresh_continue_watching_after_watched", refresh)

    def navigate():
        app.invalidate_navigation_results()
        app.browsing_stack = [newer]

    delayed_result(app, PlexTuiApp.toggle_watched_state, "mark_watched", watched.raw,
                   navigate, watched, original, app.navigation_token)
    assert app.current_browse_state() is newer
    refresh.assert_not_called()
    app.show_browse_state.assert_not_called()


@pytest.mark.parametrize("loaded", [1, 3])
@pytest.mark.parametrize("known_total", [True, False])
def test_continue_watching_removal_keeps_pagination_contiguous(app, loaded, known_total):
    all_items = [media(str(index)) for index in range(6)]
    state = BrowseState("Continue Watching", all_items[:loaded], source="continue_watching",
                        next_start=loaded, total=6 if known_total else None)
    app.browsing_stack = [state]
    app.config = replace(app.config, page_size=3)
    app.service = SimpleNamespace(continue_watching_page=lambda start, size: MediaPage(
        all_items[start:start + size], start=start, total=len(all_items),
    ))
    removed = all_items.pop(0)
    app.apply_continue_watching_removal(removed)
    assert state.next_start == loaded - 1
    assert state.total == (5 if known_total else None)
    app.apply_continue_watching_removal(removed)
    assert state.next_start == loaded - 1
    assert state.total == (5 if known_total else None)
    if known_total:
        PlexTuiApp.load_more_media.__wrapped__(app)
        assert state.items == all_items[:loaded - 1 + 3]
    else:
        assert state.items == all_items[:loaded - 1]


def test_repeated_continue_watching_removals_adjust_offset(app):
    items = [media(str(index)) for index in range(3)]
    state = BrowseState("Continue Watching", list(items), source="continue_watching", next_start=3, total=6)
    app.browsing_stack = [state]
    app.apply_continue_watching_removal(items[0])
    app.apply_continue_watching_removal(items[1])
    assert state.items == [items[2]]
    assert state.next_start == 1
    assert state.total == 4


@pytest.mark.parametrize("playing_selected", [False, True])
def test_live_stream_picker_scopes_choices_to_active_version(app, monkeypatch, playing_selected):
    selected = media("selected")
    app.browsing_stack = [BrowseState("Movies", [selected])]
    app.player = SimpleNamespace(active=True, version_part_id="part-2")
    app.active_playback_media = selected if playing_selected else media("other")
    app.call_navigation_from_thread = Mock()
    choices = Mock(return_value=[])
    monkeypatch.setattr("plextui.app.audio_choices", choices)
    PlexTuiApp.open_stream_picker.__wrapped__(app, selected, "audio")
    if playing_selected:
        choices.assert_called_once_with(selected.raw, version_part_id="part-2")
    else:
        choices.assert_called_once_with(selected.raw)
