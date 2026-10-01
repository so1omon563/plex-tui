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
