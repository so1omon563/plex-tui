from __future__ import annotations

import os
import re
import shutil
import subprocess
import textwrap
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from rich.align import Align
from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult, ScreenStackError, SuspendNotSupported
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual import events
from textual.message import Message
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static

from . import __version__
from .artwork import (
    KittyImage,
    artwork_is_cached,
    fetch_artwork,
    kitty_pixel_size,
    protocol_renderer_status,
    render_artwork,
    render_protocol_artwork,
    resolve_protocol_renderer,
)
from .auth import LoginSession, ProfileChoice, ServerChoice, profile_choices, save_server_choice, switch_profile
from .config import (
    DEFAULT_AUTO_LOAD_THRESHOLD,
    DEFAULT_GRID_PREFETCH_PAGES,
    DEFAULT_MPV_WINDOW_SIZE,
    DEFAULT_PAGE_SIZE,
    MAX_AUTO_LOAD_THRESHOLD,
    MAX_GRID_PREFETCH_PAGES,
    MAX_PAGE_SIZE,
    MIN_AUTO_LOAD_THRESHOLD,
    MIN_GRID_PREFETCH_PAGES,
    MIN_PAGE_SIZE,
    AppConfig,
    cache_path,
    config_path,
    debug_log_path,
    load_config,
    save_config,
    valid_mpv_window_size,
    write_debug_log,
)
from .models import LibraryItem, MediaItem
from .player import (
    PlayerError,
    PlayerHandle,
    StreamChoice,
    audio_choices,
    play_with_mpv,
    preferred_audio_choice,
    preferred_subtitle_choice,
    resume_offset_ms,
    same_stream,
    seek_mpv,
    stop_mpv,
    stream_language_key,
    stream_language_label,
    switch_mpv_stream,
    subtitle_choices,
    toggle_mpv_pause,
    transcode_quality_label,
)
from .plex_service import (
    PlexService,
    availability_urls,
    is_online_metadata,
    kind_label,
    media_details,
    progress_bar,
    row_progress_marker,
    watched_state,
)
GRID_CARD_GAP = 2
GRID_COLLECTION_CARD_EXTRA_WIDTH = 8
GRID_DENSITY_SPECS = {
    "compact": {"width": 18, "content_width": 15, "art_width": 14, "art_height": 7, "height": 10, "max_columns": 6},
    "comfortable": {"width": 22, "content_width": 19, "art_width": 18, "art_height": 9, "height": 12, "max_columns": 5},
    "large": {"width": 28, "content_width": 25, "art_width": 24, "art_height": 12, "height": 15, "max_columns": 4},
}
GRID_DETAIL_REFRESH_DELAY = 0.65
LIST_DETAIL_REFRESH_DELAY = 0.35
DETAIL_ARTWORK_REFRESH_DELAY = 0.55
PLAYBACK_CONTROL_HINT = "controls c pause, z -10s, f +30s, x stop"
PLAYLIST_REMOVE_HINT = "Playlist: Backspace/Delete removes from this playlist"
GRID_PREFETCH_WORKERS = 3
DETAIL_SUMMARY_WIDTH = 38
DETAIL_LABEL_WIDTH = 20
DETAIL_STREAM_LIMIT = 5


@dataclass
class BrowseState:
    title: str
    items: list[MediaItem]
    selected_library: LibraryItem | None = None
    search: bool = False
    search_query: str = ""
    global_search: bool = False
    source: str = "library"
    next_start: int = 0
    total: int | None = None
    context_media: MediaItem | None = None
    discover_media_type: str = "movies_shows"

    @property
    def has_more(self) -> bool:
        if self.total is None or self.next_start >= self.total:
            return False
        if self.source in {"continue_watching", "vod"}:
            return True
        if self.source == "discover":
            return bool(self.search_query)
        if self.search:
            return bool(self.search_query and self.selected_library is not None and not self.global_search)
        return self.selected_library is not None


class LibraryRow(ListItem):
    def __init__(self, library: LibraryItem) -> None:
        super().__init__(Label(library.title))
        self.library = library


class ContinueWatchingRow(ListItem):
    def __init__(self) -> None:
        self.label_text = "Continue Watching"
        super().__init__(Label(self.label_text))


class PlaylistsRow(ListItem):
    def __init__(self) -> None:
        self.label_text = "Playlists"
        super().__init__(Label(self.label_text))


class DiscoverRow(ListItem):
    def __init__(self) -> None:
        self.label_text = "Discover"
        super().__init__(Label(self.label_text))


class OnPlexRow(ListItem):
    def __init__(self) -> None:
        self.label_text = "On Plex"
        super().__init__(Label(self.label_text))


class AvailabilityRow(ListItem):
    def __init__(self, media_title: str, label: str, url: str) -> None:
        self.media_title = media_title
        self.label = label
        self.url = url
        self.label_text = label
        super().__init__(Label(f"› {label}"))


class ResumeChoiceRow(ListItem):
    def __init__(self, media: MediaItem, resume: bool) -> None:
        self.media = media
        self.resume = resume
        self.label_text = "Resume" if resume else "Start over"
        super().__init__(Label(f"› {self.label_text}"))


class LibraryMenuRow(ListItem):
    def __init__(self, library: LibraryItem, entry: str, label: str, description: str) -> None:
        self.library = library
        self.entry = entry
        self.label_text = label
        self.description = description
        self.display_text = f"{library_entry_glyph(entry)} {label}"
        super().__init__(Label(self.display_text))


class MediaRow(ListItem):
    def __init__(self, media: MediaItem, bulk_selected: bool = False) -> None:
        marker = "▶" if media.playable else "›"
        if bulk_selected:
            marker = "✓"
        metadata = media_metadata_label(media, include_kind=True)
        subtitle = f" · {metadata}" if metadata else ""
        progress = row_progress_marker(media.raw)
        progress_text = f" {progress}" if progress else ""
        self.label_text = f"{marker} {media.title}{subtitle}{progress_text}"
        super().__init__(Label(self.label_text))
        self.media = media


class MediaGrid(Static):
    can_focus = True

    class Highlighted(Message):
        def __init__(self, media: MediaItem) -> None:
            self.media = media
            super().__init__()

    class Selected(Message):
        def __init__(self, media: MediaItem) -> None:
            self.media = media
            super().__init__()

    class NeedsArtwork(Message):
        def __init__(self) -> None:
            super().__init__()

    def __init__(self) -> None:
        super().__init__("", id="media-grid")
        self.items: list[MediaItem] = []
        self.selected_index = 0
        self.columns = 1
        self.rows = 1
        self.config: AppConfig | None = None
        self.artwork: dict[str, object] = {}
        self.bulk_selected_keys: set[str] = set()

    @property
    def selected_media(self) -> MediaItem | None:
        if not self.items:
            return None
        return self.items[min(self.selected_index, len(self.items) - 1)]

    def set_items(
        self,
        items: list[MediaItem],
        selected_index: int,
        config: AppConfig,
        columns: int,
        rows: int = 1,
        bulk_selected_keys: set[str] | None = None,
    ) -> None:
        self.items = items
        self.selected_index = min(max(0, selected_index), max(0, len(items) - 1))
        self.columns = max(1, columns)
        self.rows = max(1, rows)
        self.config = config
        self.bulk_selected_keys = set(bulk_selected_keys or set())
        self.artwork = {key: value for key, value in self.artwork.items() if key in {item.key for item in items}}
        self.refresh_grid()
        self.scroll_selected_visible()
        selected = self.selected_media
        if selected is not None:
            self.post_message(self.Highlighted(selected))

    def set_selected_key(self, selected_key: str) -> None:
        for index, item in enumerate(self.items):
            if item.key == selected_key:
                self.set_selected_index(index)
                return

    def set_selected_index(self, selected_index: int) -> None:
        if not self.items:
            return
        next_index = min(max(0, selected_index), len(self.items) - 1)
        if next_index == self.selected_index:
            return
        self.selected_index = next_index
        self.refresh_grid()
        self.scroll_selected_visible()
        selected = self.selected_media
        if selected is not None:
            self.post_message(self.Highlighted(selected))

    def move_selection(self, offset: int) -> None:
        self.set_selected_index(self.selected_index + offset)

    def set_artwork(self, media_key: str, artwork: object) -> None:
        self.artwork[media_key] = artwork
        self.refresh_grid()

    @property
    def page_size(self) -> int:
        return max(1, self.columns * self.rows)

    @property
    def page_start(self) -> int:
        return (self.selected_index // self.page_size) * self.page_size

    def visible_page_items(self, rows: int | None = None, page_offset: int = 0) -> list[MediaItem]:
        page_size = max(1, self.columns * (rows or self.rows))
        start = ((self.selected_index // page_size) + page_offset) * page_size
        return self.items[start:start + page_size]

    def refresh_grid(self) -> None:
        if self.config is None or not self.items:
            self.update("")
            return
        selected = self.selected_media
        selected_key = selected.key if selected is not None else self.items[0].key
        visible_items = self.visible_page_items()
        visible_keys = {item.key for item in visible_items}
        loaded_count = len(visible_keys.intersection(self.artwork))
        poster_count = sum(1 for item in visible_items if item.artwork_path)
        started = time.perf_counter()
        self.update(render_media_grid(visible_items, selected_key, self.config, self.columns, self.artwork, self.bulk_selected_keys))
        write_artwork_performance_log(
            "grid_render",
            started,
            f"items={len(visible_items)} posters={poster_count} loaded={loaded_count} columns={self.columns} page={','.join(item.key for item in visible_items)}",
        )
        if poster_count and loaded_count < poster_count:
            self.post_message(self.NeedsArtwork())

    def scroll_selected_visible(self) -> None:
        if not self.is_mounted:
            return
        row = (self.selected_index - self.page_start) // max(1, self.columns)
        row_height = grid_card_height(
            self.config,
            collection_card=grid_items_are_collection_cards(self.visible_page_items()),
        )
        if self.parent is not None:
            self.parent.scroll_to(y=max(0, row * row_height), animate=False)

    def on_key(self, event) -> None:
        if not self.items:
            return
        if event.key == "left":
            self.move_selection(-1)
            event.stop()
        elif event.key == "right":
            self.move_selection(1)
            event.stop()
        elif event.key == "up":
            self.move_selection(-self.columns)
            event.stop()
        elif event.key == "down":
            self.move_selection(self.columns)
            event.stop()
        elif event.key in {"pageup", "page_up"}:
            self.move_selection(-self.page_size)
            event.stop()
        elif event.key in {"pagedown", "page_down"}:
            self.move_selection(self.page_size)
            event.stop()
        elif event.key == "enter":
            selected = self.selected_media
            if selected is not None:
                self.post_message(self.Selected(selected))
            event.stop()


class LoadMoreRow(ListItem):
    def __init__(self, loaded: int, total: int | None) -> None:
        total_text = str(total) if total is not None else "?"
        super().__init__(Label(f"  Load more... ({loaded} of {total_text})"))


class EmptyStateRow(ListItem):
    def __init__(self, title: str, action: str = "") -> None:
        self.label_text = f"  {title}"
        self.action_text = action
        super().__init__(Label(self.label_text))


class ServerRow(ListItem):
    def __init__(self, choice: ServerChoice, is_recommended: bool = False) -> None:
        marker = "* " if is_recommended else "  "
        suffix = " (recommended)" if is_recommended else ""
        super().__init__(Label(f"{marker}{choice.name}  {choice.uri}  [{choice.row_label}]{suffix}"))
        self.choice = choice


class ProfileRow(ListItem):
    def __init__(self, choice: ProfileChoice) -> None:
        self.choice = choice
        marker = "* " if choice.current else "  "
        suffix = " (current)" if choice.current else ""
        locked = " [PIN]" if choice.protected else ""
        self.label_text = f"{marker}{choice.title}{locked}{suffix}"
        super().__init__(Label(self.label_text))


class StreamRow(ListItem):
    def __init__(self, choice: StreamChoice, stream_type: str, current: bool = False) -> None:
        marker = "* " if current else "  "
        suffix = " (current)" if current else ""
        super().__init__(Label(f"{marker}{choice.label}{suffix}"))
        self.choice = choice
        self.stream_type = stream_type


class PlaylistCreateRow(ListItem):
    def __init__(self) -> None:
        self.label_text = "New playlist..."
        super().__init__(Label(f"+ {self.label_text}"))


class PlaylistTargetRow(ListItem):
    def __init__(self, playlist: MediaItem) -> None:
        self.playlist = playlist
        self.label_text = playlist.title
        super().__init__(Label(f"› {playlist.title}"))


class SettingsActionRow(ListItem):
    def __init__(self, label: str, action: str) -> None:
        self.action = action
        self.action_kind = settings_action_kind(action)
        self.label_text = f"› {label}  ({settings_action_badge(self.action_kind)})"
        super().__init__(Label(self.label_text))


class SettingsNumericRow(SettingsActionRow):
    def __init__(self, label: str, action: str, setting_name: str) -> None:
        self.setting_name = setting_name
        super().__init__(label, action)


class SettingsHeaderRow(ListItem):
    def __init__(self, label: str) -> None:
        self.label_text = label
        super().__init__(Label(self.label_text))


class SettingsValueRow(ListItem):
    def __init__(self, label: str) -> None:
        self.label_text = f"  {label}"
        super().__init__(Label(self.label_text))


class StatusChanged(Message):
    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()


FOCUS_TITLE_PREFIX = "▶ "
UI_SELECTED_ACCENT = "#e5a00d"
UI_GRID_TITLE = "#d8dee9"
UI_GRID_MUTED = "#9aa3b8"
UI_GRID_DIM = "#778196"


class PlexTuiApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }

    #body {
        height: 1fr;
    }

    #sidebar {
        width: 30;
        border: solid $panel;
    }

    #sidebar.focused-pane {
        border: heavy $primary;
        background: $boost;
    }

    #main {
        width: 1fr;
        border: solid $panel;
    }

    #main.focused-pane {
        border: heavy $primary;
        background: $boost;
    }

    #details {
        width: 42;
        border: solid $panel;
    }

    #details.focused-pane {
        border: heavy $primary;
        background: $boost;
    }

    #search {
        margin: 0 1;
    }

    #status {
        height: 1;
        padding: 0 1;
        background: $panel;
    }

    #playback-footer {
        height: 1;
        padding: 0 1;
        background: $panel;
        color: $text;
    }

    .pane-title {
        text-style: bold;
        padding: 0 1;
        background: $panel;
    }

    .focused-pane > .pane-title {
        background: $primary;
        color: $text;
    }

    #detail-content {
        padding: 0 1;
        width: 1fr;
        height: auto;
    }

    #detail-scroll {
        height: 1fr;
    }

    .active-row {
        background: $accent;
        color: $text;
        text-style: bold;
    }

    #media-grid-scroll {
        height: 1fr;
        overflow-y: auto;
    }

    #media-grid {
        padding: 0 1;
    }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+r", "reload", "Reload", show=False),
        Binding("/", "focus_search", "Search"),
        Binding("g", "focus_global_search", "Global"),
        Binding("tab", "focus_next", "Next", show=False),
        Binding("shift+tab", "focus_previous", "Prev", show=False),
        Binding("space", "alternate_library_action", "Library modes", show=False),
        Binding("question_mark", "show_help", "Help"),
        Binding("l", "focus_libraries", "Focus libraries", show=False),
        Binding("m", "focus_media", "Focus media list", show=False),
        Binding("d", "focus_details", "Focus details", show=False),
        Binding("v", "toggle_media_view", "View"),
        Binding(
            "left_square_bracket",
            "jump_alpha_previous",
            "Prev letter",
            show=False,
        ),
        Binding(
            "right_square_bracket",
            "jump_alpha_next",
            "Next letter",
            show=False,
        ),
        Binding("left", "grid_left", "Left", show=False),
        Binding("right", "grid_right", "Right", show=False),
        Binding("comma", "show_settings", "Settings"),
        Binding("escape", "back_or_clear", "Back"),
        Binding("p", "play_selected", "Play from start"),
        Binding("P", "add_to_playlist", "Playlist", show=False),
        Binding("u", "toggle_bulk_selection", "Select", show=False),
        Binding("e", "rename_playlist", "Rename playlist", show=False),
        Binding("D", "delete_playlist", "Delete playlist", show=False),
        Binding("r", "resume_selected", "Resume"),
        Binding("w", "toggle_watched", "Watched", show=False),
        Binding("backspace", "remove_continue_watching", "Remove continue", show=False),
        Binding("delete", "remove_continue_watching", "Remove continue", show=False),
        Binding("a", "audio_picker", "Audio", show=False),
        Binding("s", "subtitle_picker", "Subtitles", show=False),
        Binding("A", "clear_audio_preference", "Clear audio", show=False),
        Binding("S", "cycle_subtitle_mode", "Sub mode", show=False),
        Binding("c", "toggle_playback_pause", "Pause", show=False),
        Binding("z", "seek_playback_backward", "-10s", show=False),
        Binding("f", "seek_playback_forward", "+30s", show=False),
        Binding("x", "stop_playback", "Stop", show=False),
    ]

    service: reactive[PlexService | None] = reactive(None)
    selected_library: reactive[LibraryItem | None] = reactive(None)
    browsing_stack: list[BrowseState]
    config: AppConfig
    login_session: LoginSession | None
    pending_account_token: str
    search_global: bool
    input_mode: str
    pending_confirmation_action: str
    pending_profile_choice: ProfileChoice | None
    help_visible: bool
    settings_visible: bool
    picker_visible: bool
    selected_subtitle: StreamChoice | None
    selected_audio: StreamChoice | None
    picker_media_key: str | None
    bulk_selected_keys: set[str]
    playlist_picker_items: list[MediaItem]
    loading_more: bool
    suppress_auto_load: bool
    player: PlayerHandle | None
    prefetched_grid_pages: set[tuple[str, ...]]
    active_grid_prefetch_pages: set[tuple[str, ...]]
    pending_grid_prefetches: list[tuple[list[MediaItem], tuple[str, ...], str, float]]
    rendered_grid_artwork_cache: dict[tuple[str, str], object]
    last_grid_prefetch_page: tuple[str, ...]
    applying_config_theme: bool
    detail_refresh_token: int
    detail_refresh_timer: Timer | None
    detail_artwork_timer: Timer | None
    detail_cache: dict[str, MediaItem]
    libraries: list[LibraryItem]

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("Libraries", id="libraries-title", classes="pane-title")
                yield ListView(id="libraries")
            with Vertical(id="main"):
                yield Static("Media", id="media-title", classes="pane-title")
                yield Input(placeholder="Fuzzy search loaded items", id="search")
                yield ListView(id="media")
                with VerticalScroll(id="media-grid-scroll"):
                    yield MediaGrid()
            with Vertical(id="details"):
                yield Static("Details", id="details-title", classes="pane-title")
                with VerticalScroll(id="detail-scroll"):
                    yield Static("Select an item", id="detail-content")
        yield Static("", id="playback-footer")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.browsing_stack = []
        self.login_session = None
        self.pending_account_token = ""
        self.search_global = False
        self.input_mode = ""
        self.pending_confirmation_action = ""
        self.pending_profile_choice = None
        self.help_visible = False
        self.settings_visible = False
        self.picker_visible = False
        self.playlist_picker_visible = False
        self.selected_subtitle = None
        self.selected_audio = None
        self.picker_media_key = None
        self.playlist_picker_item = None
        self.playlist_picker_items = []
        self.bulk_selected_keys = set()
        self.loading_more = False
        self.suppress_auto_load = False
        self.player = None
        self.prefetched_grid_pages = set()
        self.active_grid_prefetch_pages = set()
        self.pending_grid_prefetches = []
        self.rendered_grid_artwork_cache = {}
        self.last_grid_prefetch_page = ()
        self.applying_config_theme = False
        self.detail_refresh_token = 0
        self.detail_refresh_timer = None
        self.detail_artwork_timer = None
        self.detail_cache = {}
        self.libraries = []
        try:
            self.config = load_config()
            self.apply_config_theme()
        except Exception:
            pass
        self.query_one("#search", Input).display = False
        self.query_one("#media-grid-scroll", VerticalScroll).display = False
        self.clear_playback_footer()
        self.set_interval(1.0, self.check_player_status)
        self.load_server()

    def on_focus(self, event: events.Focus) -> None:
        self.update_focus_pane()

    def on_blur(self, event: events.Blur) -> None:
        self.update_focus_pane()

    def update_focus_pane(self) -> None:
        focused_id = getattr(self.focused, "id", "")
        self.set_focus_pane(
            sidebar=focused_id == "libraries",
            main=focused_id in {"media", "media-grid", "search"},
            details=focused_id == "detail-scroll",
        )

    def set_focus_pane(self, *, sidebar: bool = False, main: bool = False, details: bool = False) -> None:
        self.query_one("#sidebar").set_class(sidebar, "focused-pane")
        self.query_one("#main").set_class(main, "focused-pane")
        self.query_one("#details").set_class(details, "focused-pane")
        self.update_pane_title("#libraries-title", "Libraries", sidebar)
        self.update_pane_title("#media-title", self.media_title_text(), main)
        self.update_pane_title("#details-title", "Details", details)

    def update_pane_title(self, selector: str, text: str, focused: bool) -> None:
        title = f"{FOCUS_TITLE_PREFIX}{text}" if focused else text
        self.query_one(selector, Static).update(title)

    def media_title_text(self) -> str:
        title = str(self.query_one("#media-title", Static).content)
        return title.removeprefix(FOCUS_TITLE_PREFIX)

    def set_media_title(self, text: str) -> None:
        focused = self.query_one("#main").has_class("focused-pane")
        self.update_pane_title("#media-title", text, focused)

    def apply_config_theme(self) -> None:
        if self.config.theme not in self.available_themes:
            write_debug_log(f"invalid theme {self.config.theme!r}; using current theme")
            return
        if self.theme == self.config.theme:
            return
        self.applying_config_theme = True
        try:
            self.theme = self.config.theme
        finally:
            self.applying_config_theme = False

    def _watch_theme(self, theme_name: str) -> None:
        super()._watch_theme(theme_name)
        if getattr(self, "applying_config_theme", False) or not hasattr(self, "config"):
            return
        if getattr(self.config, "theme", "") == theme_name:
            return
        self.config = replace(self.config, theme=theme_name)
        try:
            save_config(self.config)
        except OSError as exc:
            self.set_status(f"Error: failed to save theme: {exc}")

    @work(thread=True)
    def load_server(self) -> None:
        self.post_message(StatusChanged("Connecting to Plex..."))
        try:
            self.config = load_config()
            if not self.config.base_url or not self.config.token:
                self.call_from_thread(self.begin_login)
                return
            service = PlexService(self.config)
            libraries = service.libraries()
        except Exception as exc:
            self.call_from_thread(self.show_error, str(exc))
            return

        def update() -> None:
            self.service = service
            self.detail_cache = {}
            self.libraries = libraries
            self.rendered_grid_artwork_cache = {}
            self.apply_config_theme()
            self.title = f"plex-tui - {service.friendly_name}"
            self.set_status(f"Connected to {service.friendly_name}")
            visible = visible_libraries(libraries, self.config)
            self.populate_libraries(visible)
            self.open_continue_watching()

        self.call_from_thread(update)

    @work(thread=True)
    def begin_login(self) -> None:
        self.config = load_config()
        self.post_message(StatusChanged("Starting Plex login..."))
        try:
            session = LoginSession(self.config)
            self.login_session = session
            url = session.start()
        except Exception as exc:
            self.call_from_thread(self.show_error, str(exc))
            return

        def show_url() -> None:
            self.set_media_title("Plex Login")
            view = self.show_media_list()
            view.clear()
            view.append(ListItem(Label("A Plex login page was opened in your browser.")))
            view.append(ListItem(Label("If it did not open, use this URL:")))
            view.append(ListItem(Label(url)))
            self.show_detail_text("Complete login in your browser.")
            self.set_status("Waiting for Plex login...")

        self.call_from_thread(show_url)

        try:
            account_token, choices = session.wait()
        except Exception as exc:
            self.call_from_thread(self.show_error, str(exc))
            return

        def show_choices() -> None:
            self.pending_account_token = account_token
            if len(choices) == 1:
                self.choose_server(choices[0])
                return
            self.set_media_title("Select Server")
            view = self.show_media_list()
            view.clear()
            for index, choice in enumerate(choices):
                view.append(ServerRow(choice, is_recommended=index == 0))
            view.focus()
            self.show_detail_text("Choose the reachable connection you want this app to use. The first option is the recommended starting point.")
            self.set_status("Select a reachable Plex server connection and press Enter")

        self.call_from_thread(show_choices)

    def populate_libraries(self, libraries: list[LibraryItem], selected_library_key: str | None = None) -> None:
        selected_index = 0
        rows = sidebar_rows(self.config, libraries)
        if selected_library_key is not None:
            for index, row in enumerate(rows):
                if isinstance(row, LibraryRow) and row.library.key == selected_library_key:
                    selected_index = index
                    break
        self.replace_list_rows_async(
            "#libraries",
            rows,
            selected_index,
            "library-list",
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        row = event.item
        if isinstance(row, ContinueWatchingRow):
            self.open_continue_watching()
        elif isinstance(row, PlaylistsRow):
            self.open_playlists()
        elif isinstance(row, DiscoverRow):
            self.prompt_discover_search()
        elif isinstance(row, OnPlexRow):
            self.open_video_on_demand()
        elif isinstance(row, AvailabilityRow):
            self.open_availability_url(row)
        elif isinstance(row, ResumeChoiceRow):
            self.choose_resume_playback(row)
        elif isinstance(row, LibraryRow):
            self.open_library_primary(row.library)
        elif isinstance(row, LibraryMenuRow):
            self.open_library_entry(row.library, row.entry, row.label_text)
        elif isinstance(row, MediaRow):
            self.open_media(row.media)
        elif isinstance(row, LoadMoreRow):
            self.load_more_media()
        elif isinstance(row, ServerRow):
            self.choose_server(row.choice)
        elif isinstance(row, ProfileRow):
            self.choose_profile(row.choice)
        elif isinstance(row, StreamRow):
            self.choose_stream(row.choice, row.stream_type)
        elif isinstance(row, PlaylistCreateRow):
            self.prompt_playlist_name()
        elif isinstance(row, PlaylistTargetRow):
            self.choose_playlist_target(row.playlist)
        elif isinstance(row, SettingsActionRow):
            self.run_settings_action(row.action)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id not in {"libraries", "media"}:
            return
        row = event.item
        if row is not None and row not in list(event.list_view.children):
            return
        if row is not None and event.list_view.highlighted_child is not row:
            return
        if isinstance(row, ContinueWatchingRow):
            mark_active_row(event.list_view, row)
            self.show_detail_text("Resume movies and episodes Plex reports as ready to continue.")
            self.set_status(context_hint(row))
        elif isinstance(row, PlaylistsRow):
            mark_active_row(event.list_view, row)
            self.show_detail_text("Browse all Plex playlists. Open a playlist to remove items, or select a playlist here to rename or delete it.")
            self.set_status(context_hint(row))
        elif isinstance(row, DiscoverRow):
            mark_active_row(event.list_view, row)
            self.show_detail_text("Search Plex Discover for movie/show availability.")
            self.set_status(context_hint(row))
        elif isinstance(row, OnPlexRow):
            mark_active_row(event.list_view, row)
            self.show_detail_text("Browse Plex-hosted Movies & Shows hubs.")
            self.set_status(context_hint(row))
        elif isinstance(row, AvailabilityRow):
            mark_active_row(event.list_view, row)
            self.show_detail_text(f"{row.media_title}\n\n{row.label}\n{row.url}")
            self.set_status(context_hint(row))
        elif isinstance(row, ResumeChoiceRow):
            mark_active_row(event.list_view, row)
            self.show_detail_text(f"{row.media.title}\n\n{row.label_text}")
            self.set_status(context_hint(row))
        elif isinstance(row, LibraryRow):
            mark_active_row(event.list_view, row)
            self.set_status(context_hint(row))
        elif isinstance(row, LibraryMenuRow):
            mark_active_row(event.list_view, row)
            self.show_detail_text(row.description)
            self.set_status(context_hint(row))
        elif isinstance(row, MediaRow):
            mark_active_row(event.list_view, row)
            self.show_media_details(row.media)
            self.set_status(media_row_status(row, self.browsing_stack[-1] if self.browsing_stack else None))
            self.maybe_auto_load_more(row.media)
        elif isinstance(row, LoadMoreRow):
            mark_active_row(event.list_view, row)
            self.show_detail_text("Load the next page of items.")
            self.set_status(context_hint(row))
        elif isinstance(row, ServerRow):
            mark_active_row(event.list_view, row)
            self.show_detail_text(
                "\n".join(
                    [
                        row.choice.name,
                        "",
                        row.choice.uri,
                        f"Type: {row.choice.connection_label}",
                        f"Source: {row.choice.source}",
                    ]
                )
            )
            self.set_status(context_hint(row))
        elif isinstance(row, ProfileRow):
            mark_active_row(event.list_view, row)
            protected = "PIN required" if row.choice.protected else "No PIN required"
            current = "\n\nCurrent profile" if row.choice.current else ""
            self.show_detail_text(f"{row.choice.title}\n\n{protected}{current}")
            self.set_status(context_hint(row))
        elif isinstance(row, StreamRow):
            mark_active_row(event.list_view, row)
            self.set_status(context_hint(row))
        elif isinstance(row, PlaylistCreateRow):
            mark_active_row(event.list_view, row)
            self.show_detail_text(render_playlist_create_details(self.playlist_picker_items or self.playlist_picker_item))
            self.set_status(context_hint(row))
        elif isinstance(row, PlaylistTargetRow):
            mark_active_row(event.list_view, row)
            self.show_detail_text(render_playlist_target_details(row.playlist, self.playlist_picker_items or self.playlist_picker_item))
            self.set_status(context_hint(row))
        elif isinstance(row, (SettingsActionRow, SettingsHeaderRow, SettingsValueRow)):
            mark_active_row(event.list_view, row)
            self.show_detail_text(render_settings_row_details(row, self.config, self.pending_confirmation_action))
            self.set_status(context_hint(row))
        elif row is None and not list(event.list_view.children):
            self.show_detail_text("Select an item")

    def on_media_grid_highlighted(self, event: MediaGrid.Highlighted) -> None:
        self.show_media_details(event.media)
        if isinstance(event.control, MediaGrid):
            self.schedule_grid_prefetch(event.control)
            self.set_status(grid_status(event.control, self.browsing_stack[-1] if self.browsing_stack else None))
        self.maybe_auto_load_more(event.media)

    def on_media_grid_needs_artwork(self, event: MediaGrid.NeedsArtwork) -> None:
        grid = event.control if isinstance(event.control, MediaGrid) else None
        if grid is None:
            try:
                grid = self.query_one("#media-grid", MediaGrid)
            except NoMatches:
                return
        self.schedule_grid_prefetch(grid)

    def on_media_grid_selected(self, event: MediaGrid.Selected) -> None:
        self.open_media(event.media)

    def choose_server(self, choice: ServerChoice) -> None:
        try:
            self.config = save_server_choice(self.config, self.pending_account_token, choice)
        except Exception as exc:
            self.show_error(f"failed to save config: {exc}")
            return
        self.set_status(f"Saved server {choice.name}. Connecting...")
        self.load_server()

    @work(thread=True)
    def load_profiles(self) -> None:
        self.post_message(StatusChanged("Loading Plex profiles..."))
        try:
            choices = profile_choices(self.config)
        except Exception as exc:
            self.call_from_thread(self.show_error, str(exc))
            return

        def show_choices() -> None:
            self.settings_visible = False
            self.set_media_title("Switch Profile")
            view = self.show_media_list()
            view.clear()
            for choice in choices:
                view.append(ProfileRow(choice))
            view.focus()
            self.show_detail_text("Choose a Plex Home profile. PIN-protected profiles will ask for a PIN before switching.")
            self.set_status("Select a Plex profile and press Enter")

        self.call_from_thread(show_choices)

    def choose_profile(self, choice: ProfileChoice) -> None:
        if choice.current:
            self.set_status(f"{choice.title} is already active")
            return
        if choice.protected:
            self.prompt_profile_pin(choice)
            return
        self.switch_to_profile(choice)

    def prompt_profile_pin(self, choice: ProfileChoice) -> None:
        self.pending_profile_choice = choice
        self.input_mode = "profile_pin"
        search = self.query_one("#search", Input)
        search.placeholder = f"PIN for {choice.title}"
        search.value = ""
        search.password = True
        search.display = True
        search.focus()
        self.set_focus_pane(main=True)
        self.set_status(f"Enter PIN for {choice.title}")

    @work(thread=True)
    def switch_to_profile(self, choice: ProfileChoice, pin: str = "") -> None:
        self.post_message(StatusChanged(f"Switching to {choice.title}..."))
        try:
            self.config = switch_profile(self.config, choice, pin)
        except Exception as exc:
            self.call_from_thread(self.show_error, f"Profile switch failed: {exc}")
            return

        def reconnect() -> None:
            self.pending_profile_choice = None
            self.settings_visible = False
            self.selected_audio = None
            self.selected_subtitle = None
            self.detail_cache = {}
            self.set_status(f"Switched to {choice.title}. Reconnecting...")
            self.load_server()

        self.call_from_thread(reconnect)

    def open_library_menu(self, library: LibraryItem) -> None:
        self.selected_library = library
        self.browsing_stack = []
        self.set_media_title(library.title)
        self.show_media_list()
        self.replace_media_rows(library_menu_rows(library), 0)
        self.show_detail_text(library_menu_description(library))
        self.focus_media_browser()
        self.set_status(f"{library.title}: choose a browse mode")

    def open_library_primary(self, library: LibraryItem) -> None:
        if self.config.library_enter_action == "browse_modes":
            self.open_library_menu(library)
            return
        self.open_library_entry(library)

    def open_library_alternate(self, library: LibraryItem) -> None:
        if self.config.library_enter_action == "browse_modes":
            self.open_library_entry(library)
            return
        self.open_library_menu(library)

    def action_alternate_library_action(self) -> None:
        row = self.query_one("#libraries", ListView).highlighted_child
        if isinstance(row, LibraryRow):
            self.open_library_alternate(row.library)
            return
        if isinstance(row, ContinueWatchingRow):
            self.set_status("Continue Watching opens directly with Enter")
            return
        if isinstance(row, PlaylistsRow):
            self.set_status("Playlists opens directly with Enter")
            return
        if isinstance(row, DiscoverRow):
            self.open_video_on_demand()
            return
        self.set_status("Select a library first")

    @work(thread=True)
    def open_video_on_demand(self) -> None:
        if self.service is None:
            self.call_from_thread(self.set_status, "Connect to Plex before browsing On Plex")
            return
        self.post_message(StatusChanged("Loading Movies & Shows on Plex..."))
        started = time.perf_counter()
        try:
            page = self.service.video_on_demand_page(0, self.config.page_size)
        except Exception as exc:
            self.call_from_thread(self.show_error, str(exc))
            return
        write_performance_log(
            "video_on_demand_page",
            started,
            f"items={len(page.items)} total={page.total}",
        )

        def update() -> None:
            state = BrowseState(
                "Movies & Shows on Plex",
                page.items,
                source="vod",
                next_start=page.next_start,
                total=page.total,
            )
            self.browsing_stack = [state]
            self.show_browse_state(state)
            self.focus_media_browser()
            self.set_status(render_browse_status(state))

        self.call_from_thread(update)

    def prompt_discover_search(self) -> None:
        if self.service is None:
            self.set_status("Connect to Plex before searching Discover")
            return
        self.search_global = False
        self.input_mode = "discover_search"
        search = self.query_one("#search", Input)
        search.placeholder = "Search Plex Discover"
        search.value = ""
        search.password = False
        search.display = True
        search.focus()
        self.set_focus_pane(main=True)
        self.set_status("Discover: enter a search query")

    @work(thread=True)
    def open_library_entry(self, library: LibraryItem, entry: str = "library", label: str | None = None) -> None:
        if self.service is None:
            return
        title = library.title if entry == "library" else f"{library.title}: {label or library_entry_label(entry)}"
        self.post_message(StatusChanged(f"Loading {title}..."))
        self.call_from_thread(self.show_loading_state, title, "Loading library items from Plex.")
        started = time.perf_counter()
        try:
            page = self.service.library_entry_page(library, entry, 0, self.config.page_size)
        except Exception as exc:
            self.call_from_thread(self.show_error, str(exc))
            return
        write_performance_log(
            "library_page",
            started,
            f"title={title!r} entry={entry!r} start=0 size={self.config.page_size} items={len(page.items)} total={page.total}",
        )

        def update() -> None:
            self.selected_library = library
            state = BrowseState(
                title,
                page.items,
                library,
                source=f"library:{entry}",
                next_start=page.next_start,
                total=page.total,
            )
            self.browsing_stack = [state]
            self.show_browse_state(state)
            self.focus_media_browser()
            self.set_status(render_loaded_status(title, len(page.items), page.total, page.has_more, page.items))

        self.call_from_thread(update)

    @work(thread=True)
    def open_continue_watching(self) -> None:
        if self.service is None:
            return
        title = "Continue Watching"
        self.post_message(StatusChanged(f"Loading {title}..."))
        self.call_from_thread(self.show_loading_state, title, "Loading in-progress items from Plex.")
        started = time.perf_counter()
        try:
            page = self.service.continue_watching_page(0, self.config.page_size)
        except Exception as exc:
            self.call_from_thread(self.show_error, str(exc))
            return
        write_performance_log(
            "continue_watching_page",
            started,
            f"start=0 size={self.config.page_size} items={len(page.items)} total={page.total}",
        )

        def update() -> None:
            state = BrowseState(
                title,
                page.items,
                source="continue_watching",
                next_start=page.next_start,
                total=page.total,
            )
            self.browsing_stack = [state]
            self.show_browse_state(state)
            self.focus_media_browser()
            self.set_status(render_loaded_status(title, len(page.items), page.total, page.has_more, page.items))

        self.call_from_thread(update)

    @work(thread=True)
    def open_playlists(self) -> None:
        if self.service is None:
            return
        title = "Playlists"
        self.post_message(StatusChanged(f"Loading {title}..."))
        self.call_from_thread(self.show_loading_state, title, "Loading Plex playlists.")
        started = time.perf_counter()
        try:
            playlists = self.service.playlists()
        except Exception as exc:
            self.call_from_thread(self.show_error, f"failed to load playlists: {exc}")
            return
        write_performance_log(
            "playlists_page",
            started,
            f"items={len(playlists)}",
        )

        def update() -> None:
            state = BrowseState(
                title,
                playlists,
                source="playlists",
                next_start=len(playlists),
                total=len(playlists),
            )
            self.browsing_stack = [state]
            self.show_browse_state(state)
            self.focus_media_browser()
            self.set_status(render_browse_status(state))

        self.call_from_thread(update)

    def maybe_auto_load_more(self, media: MediaItem) -> None:
        if self.suppress_auto_load:
            self.suppress_auto_load = False
            return
        if self.settings_visible or self.picker_visible or self.loading_more or not self.browsing_stack:
            return
        state = self.browsing_stack[-1]
        if should_auto_load_more(state, media.key, self.config.auto_load_threshold):
            self.load_more_media(selected_key=media.key)

    def selected_media(self) -> MediaItem | None:
        if self.media_grid_visible():
            return self.query_one("#media-grid", MediaGrid).selected_media
        return selected_media_from_row(self.query_one("#media", ListView).highlighted_child)

    def current_browse_state(self) -> BrowseState | None:
        return self.browsing_stack[-1] if self.browsing_stack else None

    def current_browse_state_source(self) -> str:
        state = self.current_browse_state()
        return state.source if state is not None else ""

    def selected_bulk_items(self) -> list[MediaItem]:
        state = self.current_browse_state()
        if state is None or not self.bulk_selected_keys:
            return []
        return [item for item in state.items if item.key in self.bulk_selected_keys]

    def playlist_action_items(self) -> list[MediaItem]:
        selected = self.selected_bulk_items()
        if selected:
            return selected
        media = self.selected_media()
        return [media] if media is not None else []

    def prune_bulk_selection(self, state: BrowseState) -> None:
        valid_keys = {item.key for item in state.items}
        self.bulk_selected_keys.intersection_update(valid_keys)

    def action_toggle_bulk_selection(self) -> None:
        media = self.selected_media()
        state = self.current_browse_state()
        if media is None or state is None:
            self.set_status("No media selected")
            return
        if media.key in self.bulk_selected_keys:
            self.bulk_selected_keys.remove(media.key)
            status = f"Removed {media.title} from bulk selection"
        else:
            self.bulk_selected_keys.add(media.key)
            status = f"Selected {media.title} for bulk actions"
        self.show_browse_state(state, selected_key=media.key)
        self.focus_media_browser()
        count = len(self.selected_bulk_items())
        label = "item" if count == 1 else "items"
        self.set_status(f"{status} / {count} selected {label}")

    def focus_media_browser(self) -> None:
        if self.media_grid_visible():
            self.query_one("#media-grid", MediaGrid).focus()
            self.set_focus_pane(main=True)
            return
        self.query_one("#media", ListView).focus()
        self.set_focus_pane(main=True)

    def media_grid_visible(self) -> bool:
        try:
            return bool(self.query_one("#media-grid-scroll", VerticalScroll).display)
        except (NoMatches, ScreenStackError):
            return False

    def show_media_list(self) -> ListView:
        media = self.query_one("#media", ListView)
        grid_scroll = self.query_one("#media-grid-scroll", VerticalScroll)
        media.display = True
        grid_scroll.display = False
        return media

    def show_media_grid(self) -> MediaGrid:
        media = self.query_one("#media", ListView)
        grid_scroll = self.query_one("#media-grid-scroll", VerticalScroll)
        grid = self.query_one("#media-grid", MediaGrid)
        media.display = False
        grid_scroll.display = True
        return grid

    @work(thread=True, exclusive=True)
    def load_more_media(self, selected_key: str | None = None, alphabet_direction: int = 0) -> None:
        if self.service is None or not self.browsing_stack:
            return
        state = self.browsing_stack[-1]
        if self.loading_more:
            return
        if not state.has_more:
            self.call_from_thread(self.set_status, "No more items to load")
            return
        self.loading_more = True
        self.post_message(StatusChanged(f"Loading more {state.title}..."))
        started = time.perf_counter()
        try:
            if state.source == "discover":
                page = self.service.discover_page(
                    state.search_query,
                    state.next_start,
                    self.config.page_size,
                    state.discover_media_type,
                )
            elif state.source == "vod":
                page = self.service.video_on_demand_page(state.next_start, self.config.page_size)
            elif state.search:
                page = self.service.search_page(state.search_query, state.selected_library, state.next_start, self.config.page_size)
            elif state.source == "continue_watching":
                page = self.service.continue_watching_page(state.next_start, self.config.page_size)
            elif state.source.startswith("library:"):
                page = self.service.library_entry_page(
                    state.selected_library,
                    state.source.removeprefix("library:"),
                    state.next_start,
                    self.config.page_size,
                )
            else:
                page = self.service.library_page(state.selected_library, state.next_start, self.config.page_size)
        except Exception as exc:
            self.loading_more = False
            self.call_from_thread(self.show_error, str(exc))
            return
        write_performance_log(
            "load_more_page",
            started,
            f"title={state.title!r} start={state.next_start} size={self.config.page_size} items={len(page.items)} total={page.total}",
        )

        def update() -> None:
            first_new_key = page.items[0].key if page.items else None
            state.items.extend(page.items)
            state.next_start = page.next_start
            state.total = page.total
            self.loading_more = False
            self.suppress_auto_load = True
            target_key = selected_key or first_new_key
            status = render_browse_status(state)
            if alphabet_direction and selected_key:
                current_index = selected_media_index(state.items, selected_key)
                next_index = alphabet_jump_index(state.items, current_index, alphabet_direction)
                write_alphabet_jump_log(state.items, current_index, alphabet_direction, next_index)
                if next_index is not None:
                    item = state.items[next_index]
                    target_key = item.key
                    status = f"Jumped to {alphabet_group_label(item)}: {item.title}"
            self.show_browse_state(state, selected_key=target_key)
            self.focus_media_browser()
            self.set_status(status)

        self.call_from_thread(update)

    @work(thread=True)
    def open_media(self, media: MediaItem) -> None:
        if self.service is None:
            return
        if self.current_browse_state_source() == "discover":
            urls = availability_urls(media.raw)
            if not urls:
                self.call_from_thread(self.set_status, f"No availability links for {media.title}.")
                return
            if len(urls) > 1:
                self.call_from_thread(self.show_availability_picker, media, urls)
                return
            label, url = urls[0]
            webbrowser.open(url)
            self.call_from_thread(self.set_status, f"Opened: {media.title} - {label}")
            return
        if media.playable:
            self.call_from_thread(self.set_status, f"Selected {media.title}. Press p to play.")
            return
        else:
            self.post_message(StatusChanged(f"Opening {media.title}..."))
            self.call_from_thread(self.show_loading_state, media.title, "Loading child items from Plex.")
            started = time.perf_counter()
            try:
                children = self.service.children(media, self.config.page_size)
            except Exception as exc:
                self.call_from_thread(self.show_error, str(exc))
                return
            write_performance_log(
                "children_load",
                started,
                f"title={media.title!r} kind={media.kind!r} key={media.key!r} items={len(children)} playable=0",
            )
        if not children:
            self.call_from_thread(self.show_empty_state, media.title, "No child items", "Go back and choose another item.")
            return

        def update() -> None:
            source = "playlist" if media.kind == "playlist" else "library"
            context_media = media if media.kind == "playlist" else None
            state = BrowseState(media.title, children, self.selected_library, context_media=context_media, source=source)
            self.browsing_stack.append(state)
            self.show_browse_state(state)
            self.focus_media_browser()
            self.set_status(render_browse_status(state))

        self.call_from_thread(update)

    def show_availability_picker(self, media: MediaItem, urls: list[tuple[str, str]]) -> None:
        self.picker_visible = True
        self.settings_visible = False
        self.picker_media_key = media.key
        self.set_media_title(f"Availability: {media.title}")
        rows = [AvailabilityRow(media.title, label, url) for label, url in urls]
        self.show_media_list()
        self.replace_media_rows(rows, 0)
        self.query_one("#media", ListView).focus()
        self.show_detail_text(f"{media.title}\n\nChoose where to open this title.")
        self.set_status("Choose availability provider")

    def open_availability_url(self, row: AvailabilityRow) -> None:
        webbrowser.open(row.url)
        self.picker_visible = False
        if self.browsing_stack:
            self.show_browse_state(self.browsing_stack[-1], selected_key=self.picker_media_key)
        self.picker_media_key = None
        self.focus_media_browser()
        status = f"Opened: {row.media_title} - {row.label}"
        self.set_status(status)
        self.set_timer(0.05, lambda: self.set_status(status), name="availability-choice-status")

    def show_media(self, title: str, items: list[MediaItem], selected_key: str | None = None) -> None:
        self.set_media_title(title)
        state = BrowseState(title, items)
        self.show_browse_state(state, selected_key=selected_key)

    def show_browse_state(self, state: BrowseState, selected_key: str | None = None) -> None:
        self.set_media_title(state.title)
        self.prune_bulk_selection(state)
        if state.items:
            started = time.perf_counter()
            selected_index = selected_media_index(state.items, selected_key)
            if self.config.media_view == "grid":
                grid = self.show_media_grid()
                columns, rows = self.media_grid_geometry(
                    collection_cards=grid_items_are_collection_cards(state.items),
                )
                grid.set_items(state.items, selected_index, self.config, columns, rows, self.bulk_selected_keys)
                self.schedule_grid_prefetch(grid)
            else:
                self.show_media_list()
                rows, selected_row_index = media_rows(state.items, self.config, selected_index, self.bulk_selected_keys)
                if state.has_more:
                    rows.append(LoadMoreRow(len(state.items), state.total))
                self.replace_media_rows(rows, selected_row_index)
            self.show_media_details(state.items[selected_index])
            write_performance_log(
                "browse_render",
                started,
                f"title={state.title!r} view={self.config.media_view} items={len(state.items)} selected={selected_index}",
            )
        else:
            self.show_empty_state(
                state.title,
                empty_state_message(state),
                empty_state_action(state),
                status=render_browse_status(state),
            )

    def show_loading_state(self, title: str, message: str = "Loading from Plex.") -> None:
        self.set_media_title(title)
        self.show_media_list()
        self.replace_media_rows([EmptyStateRow("Loading...", message)], selected_index=0)
        self.show_detail_text(render_loading_state_details(title, message))

    def show_empty_state(self, title: str, message: str, action: str = "", status: str | None = None) -> None:
        self.set_media_title(title)
        self.show_media_list()
        self.replace_media_rows([EmptyStateRow(message, action)], selected_index=0)
        self.show_detail_text(render_empty_state_details(title, message, action))
        if status is not None:
            self.set_status(status)

    def replace_media_rows(self, rows: list[ListItem], selected_index: int | None = None) -> None:
        self.replace_list_rows_async("#media", rows, selected_index, "media-list")

    def replace_list_rows_async(
        self,
        selector: str,
        rows: list[ListItem],
        selected_index: int | None,
        group: str,
    ) -> None:
        self.run_worker(
            self.replace_list_rows(selector, rows, selected_index),
            group=group,
            exclusive=True,
        )

    async def replace_list_rows(self, selector: str, rows: list[ListItem], selected_index: int | None = None) -> None:
        view = self.query_one(selector, ListView)
        await view.clear()
        if rows:
            await view.extend(rows)
        if selected_index is not None and rows:
            set_list_index(view, selected_index)

    def show_media_details(self, item: MediaItem) -> None:
        self.detail_refresh_token += 1
        token = self.detail_refresh_token
        details = media_details(item)
        self.show_detail_text(render_detail_content(
            details,
            self.config,
            raw=item.raw,
            context_actions=current_detail_actions(self.browsing_stack[-1] if self.browsing_stack else None, item),
        ))
        delay = GRID_DETAIL_REFRESH_DELAY if self.media_grid_visible() else LIST_DETAIL_REFRESH_DELAY
        self.schedule_media_detail_refresh(item, token, delay)

    def schedule_media_detail_refresh(self, item: MediaItem, token: int, delay: float = 0.0) -> None:
        self.cancel_media_detail_refresh()
        if delay:
            self.detail_refresh_timer = self.set_timer(
                delay,
                lambda: self.start_media_detail_refresh(item, token),
                name="detail-refresh",
            )
            return
        self.start_media_detail_refresh(item, token)

    def cancel_media_detail_refresh(self) -> None:
        if self.detail_refresh_timer is not None:
            self.detail_refresh_timer.stop()
            self.detail_refresh_timer = None
        self.cancel_media_detail_artwork_refresh()

    def cancel_media_detail_artwork_refresh(self) -> None:
        if self.detail_artwork_timer is not None:
            self.detail_artwork_timer.stop()
            self.detail_artwork_timer = None

    def start_media_detail_refresh(self, item: MediaItem, token: int) -> None:
        self.detail_refresh_timer = None
        if token != self.detail_refresh_token:
            write_performance_log("detail_refresh_skipped", time.perf_counter(), f"title={item.title!r} reason=stale")
            return
        self.refresh_media_details(item, token)

    @work(thread=True, exclusive=True)
    def refresh_media_details(self, item: MediaItem, token: int) -> None:
        started = time.perf_counter()
        if token != self.detail_refresh_token:
            write_performance_log("detail_refresh_skipped", started, f"title={item.title!r} reason=stale")
            return
        cached_item = self.detail_cache.get(item.key)
        if cached_item is not None:
            write_performance_log("detail_cache_hit", started, f"title={item.title!r}")
            self.call_from_thread(self.apply_media_details, cached_item, token)
            return
        if not hasattr(item.raw, "reload"):
            return
        try:
            full_item = MediaItem(
                title=item.title,
                subtitle=item.subtitle,
                kind=item.kind,
                key=item.key,
                playable=item.playable,
                raw=item.raw.reload(),
                artwork_path=item.artwork_path,
            )
        except Exception:
            return
        self.detail_cache[item.key] = full_item
        write_performance_log("detail_reload", started, f"title={item.title!r}")

        self.call_from_thread(self.apply_media_details, full_item, token)

    def apply_media_details(self, full_item: MediaItem, token: int) -> None:
        details = media_details(full_item)
        if token != self.detail_refresh_token:
            return
        selected = self.selected_media()
        if selected is not None and selected.key == full_item.key:
            self.show_detail_text(render_detail_content(
                details,
                self.config,
                raw=full_item.raw,
                context_actions=current_detail_actions(self.browsing_stack[-1] if self.browsing_stack else None, full_item),
            ))
            self.schedule_media_detail_artwork_refresh(full_item, details, token)

    def schedule_media_detail_artwork_refresh(self, full_item: MediaItem, details: object, token: int) -> None:
        self.cancel_media_detail_artwork_refresh()
        if token != self.detail_refresh_token:
            return
        if not artwork_enabled(self.config) or not getattr(details, "artwork_path", ""):
            return
        detail_size = self.detail_artwork_size() if detail_artwork_enabled(self.config) else None
        include_card_artwork = False
        if detail_size is None and not include_card_artwork:
            return
        self.detail_artwork_timer = self.set_timer(
            DETAIL_ARTWORK_REFRESH_DELAY,
            lambda: self.start_media_detail_artwork_refresh(full_item, details, token, detail_size, include_card_artwork),
            name="detail-artwork-refresh",
        )

    def start_media_detail_artwork_refresh(
        self,
        full_item: MediaItem,
        details: object,
        token: int,
        detail_size: tuple[int, int] | None,
        include_card_artwork: bool,
    ) -> None:
        self.detail_artwork_timer = None
        if token != self.detail_refresh_token:
            write_performance_log("detail_artwork_skipped", time.perf_counter(), f"title={full_item.title!r} reason=stale")
            return
        self.fetch_media_detail_artwork(full_item, details, token, detail_size, include_card_artwork)

    @work(thread=True, exclusive=True)
    def fetch_media_detail_artwork(
        self,
        full_item: MediaItem,
        details: object,
        token: int,
        detail_size: tuple[int, int] | None,
        include_card_artwork: bool,
    ) -> None:
        artwork = None
        card_artwork = None
        artwork_started = time.perf_counter()
        detail_fetch_ms = 0.0
        detail_render_ms = 0.0
        card_fetch_ms = 0.0
        card_render_ms = 0.0
        card_cache_hit = False
        if token != self.detail_refresh_token:
            write_performance_log("detail_artwork_skipped", artwork_started, f"title={full_item.title!r} reason=stale")
            return
        try:
            artwork_path = getattr(details, "artwork_path")
            if detail_size is not None:
                width, height = detail_size
                fetch_width, fetch_height = artwork_fetch_pixel_size(self.config, width, height)
                detail_fetch_started = time.perf_counter()
                data = fetch_artwork(full_item.raw, artwork_path, self.config, width=fetch_width, height=fetch_height)
                detail_fetch_ms = (time.perf_counter() - detail_fetch_started) * 1000
                detail_render_started = time.perf_counter()
                artwork = (
                    render_protocol_artwork(data, self.config.artwork_renderer, width=width, max_height=height)
                    or render_artwork(data, width=width, max_height=height)
                )
                detail_render_ms = (time.perf_counter() - detail_render_started) * 1000
            if include_card_artwork:
                card_cache_key = grid_artwork_cache_key(full_item, self.config)
                card_artwork = self.rendered_grid_artwork_cache.get(card_cache_key)
                if card_artwork is not None:
                    card_cache_hit = True
                else:
                    card_width, card_height = card_artwork_fetch_size(self.config)
                    card_fetch_started = time.perf_counter()
                    card_data = fetch_artwork(
                        full_item.raw,
                        artwork_path,
                        self.config,
                        width=card_width,
                        height=card_height,
                    )
                    card_fetch_ms = (time.perf_counter() - card_fetch_started) * 1000
                    card_render_started = time.perf_counter()
                    card_artwork = render_card_artwork(card_data, self.config)
                    card_render_ms = (time.perf_counter() - card_render_started) * 1000
                    self.rendered_grid_artwork_cache[card_cache_key] = card_artwork
        except Exception:
            artwork = None
            card_artwork = None
        write_performance_log(
            "detail_artwork",
            artwork_started,
            f"title={full_item.title!r} path={getattr(details, 'artwork_path', '')!r} detail_fetch={detail_fetch_ms:.1f}ms detail_render={detail_render_ms:.1f}ms card_fetch={card_fetch_ms:.1f}ms card_render={card_render_ms:.1f}ms card_cached={int(card_cache_hit)}",
        )
        if not artwork and not card_artwork:
            return

        def update_artwork() -> None:
            if token != self.detail_refresh_token:
                return
            selected = self.selected_media()
            if selected is not None and selected.key == full_item.key:
                if artwork is not None:
                    self.show_detail_text(render_detail_content(details, self.config, artwork, raw=full_item.raw))
                grid = self.query_one("#media-grid", MediaGrid)
                if self.media_grid_visible() and card_artwork is not None:
                    grid.set_artwork(full_item.key, card_artwork)

        self.call_from_thread(update_artwork)

    def show_detail_text(self, content: Any) -> None:
        try:
            self.query_one("#detail-content", Static).update(content)
            self.query_one("#detail-scroll", VerticalScroll).scroll_home(animate=False)
        except NoMatches:
            return

    def detail_artwork_size(self) -> tuple[int, int]:
        pane_width = self.query_one("#details").size.width
        width = min(36, max(14, pane_width - 6))
        return width, 22

    def media_grid_geometry(self, collection_cards: bool = False) -> tuple[int, int]:
        media_size = self.query_one("#main").size
        return grid_geometry_for_size(media_size.width, media_size.height, self.config, collection_cards=collection_cards)

    def action_focus_search(self) -> None:
        self.search_global = False
        self.input_mode = "search"
        search = self.query_one("#search", Input)
        search.placeholder = "Fuzzy search loaded items"
        search.value = ""
        search.password = False
        search.display = True
        search.focus()
        self.set_focus_pane(main=True)

    def action_focus_global_search(self) -> None:
        self.search_global = True
        self.input_mode = "search"
        search = self.query_one("#search", Input)
        search.placeholder = "Search all libraries through Plex"
        search.value = ""
        search.password = False
        search.display = True
        search.focus()
        self.set_focus_pane(main=True)

    def action_focus_libraries(self) -> None:
        self.query_one("#libraries", ListView).focus()
        self.set_focus_pane(sidebar=True)
        self.set_status("Focus moved to libraries")

    def action_focus_media(self) -> None:
        self.focus_media_browser()
        self.set_status("Focus moved to media list")

    def action_focus_details(self) -> None:
        self.query_one("#detail-scroll", VerticalScroll).focus()
        self.set_focus_pane(details=True)
        self.set_status("Focus moved to details")

    def action_focus_next(self) -> None:
        focused_id = getattr(self.focused, "id", "")
        if focused_id == "libraries":
            self.action_focus_media()
        elif focused_id in {"media", "media-grid", "search"}:
            self.action_focus_details()
        else:
            self.action_focus_libraries()

    def action_focus_previous(self) -> None:
        focused_id = getattr(self.focused, "id", "")
        if focused_id == "libraries":
            self.action_focus_details()
        elif focused_id == "detail-scroll":
            self.action_focus_media()
        else:
            self.action_focus_libraries()

    def action_toggle_media_view(self) -> None:
        next_view = next_media_view(self.config.media_view)
        if not self.update_preferences(media_view=next_view):
            return
        if self.settings_visible:
            self.refresh_settings_after_change(
                "toggle_media_view",
                "Media view",
                media_view_value(self.config),
            )
            return
        if self.browsing_stack:
            selected = self.selected_media()
            selected_key = selected.key if selected is not None else None
            self.show_browse_state(self.browsing_stack[-1], selected_key=selected_key)
            self.focus_media_browser()
        self.set_status(f"Media view: {media_view_value(self.config)}")

    def action_grid_left(self) -> None:
        if self.adjust_highlighted_setting(-1):
            return
        self.move_grid_selection(-1)

    def action_grid_right(self) -> None:
        if self.adjust_highlighted_setting(1):
            return
        self.move_grid_selection(1)

    def action_jump_alpha_previous(self) -> None:
        self.jump_alphabet(-1)

    def action_jump_alpha_next(self) -> None:
        self.jump_alphabet(1)

    def jump_alphabet(self, direction: int) -> None:
        if self.settings_visible or self.picker_visible or not self.browsing_stack:
            self.set_status("Alphabet jump is available while browsing media")
            return
        state = self.browsing_stack[-1]
        if not state.items:
            self.set_status("No media items to jump")
            return
        current_index = self.current_media_index(state)
        next_index = alphabet_jump_index(state.items, current_index, direction)
        write_alphabet_jump_log(state.items, current_index, direction, next_index)
        if next_index is None:
            if direction > 0 and state.has_more:
                selected = self.selected_media()
                self.set_status(f"Loading more {state.title} for alphabet jump...")
                self.load_more_media(selected_key=selected.key if selected is not None else None, alphabet_direction=direction)
                return
            self.set_status("No more alphabet sections")
            return
        item = state.items[next_index]
        self.show_browse_state(state, selected_key=item.key)
        self.focus_media_browser()
        self.set_status(f"Jumped to {alphabet_group_label(item)}: {item.title}")

    def current_media_index(self, state: BrowseState) -> int:
        selected = self.selected_media()
        if selected is None:
            return 0
        return selected_media_index(state.items, selected.key)

    def adjust_highlighted_setting(self, direction: int) -> bool:
        if not self.settings_visible:
            return False
        row = self.query_one("#media", ListView).highlighted_child
        if isinstance(row, SettingsNumericRow):
            spec = numeric_setting_spec(row.setting_name)
            step = int(spec["step"]) * direction
            self.update_numeric_preference(
                row.setting_name,
                step,
                int(spec["minimum"]),
                int(spec["maximum"]),
            )
            return True
        if isinstance(row, SettingsActionRow) and row.action_kind in {"toggle", "cycle"}:
            self.run_settings_action(row.action)
            return True
        return False

    def move_grid_selection(self, direction: int) -> None:
        grid = self.query_one("#media-grid", MediaGrid)
        if self.media_grid_visible():
            grid.move_selection(direction)

    def schedule_grid_prefetch(self, grid: MediaGrid) -> None:
        if not artwork_enabled(self.config):
            return
        current_items = grid.visible_page_items()
        self.hydrate_grid_artwork_from_cache(grid, current_items)
        current_key = grid_page_key(current_items)
        missing_current_artwork = [
            item
            for item in current_items
            if item.artwork_path and item.key not in grid.artwork
        ]
        selected = grid.selected_media
        if selected is not None:
            current_items = sorted(current_items, key=lambda item: item.key != selected.key)
        if current_key != self.last_grid_prefetch_page or missing_current_artwork:
            self.last_grid_prefetch_page = current_key
            self.start_grid_prefetch(current_items, "current", page_key=current_key)
        else:
            write_artwork_performance_log("grid_prefetch_skipped", time.perf_counter(), "page=current reason=same-page-loaded")

        if current_key in self.active_grid_prefetch_pages:
            return

        for page_offset in range(1, self.config.grid_prefetch_pages + 1):
            next_items = grid.visible_page_items(page_offset=page_offset)
            if not next_items:
                break
            self.start_grid_prefetch(next_items, f"next-{page_offset}")

    def start_grid_prefetch(
        self,
        items: list[MediaItem],
        page_label: str,
        delay: float = 0.0,
        page_key: tuple[str, ...] | None = None,
    ) -> None:
        started = time.perf_counter()
        page_key = page_key or grid_page_key(items)
        if not page_key:
            return
        if page_key in self.active_grid_prefetch_pages:
            write_artwork_performance_log("grid_prefetch_skipped", started, f"page={page_label} reason=in-flight items={len(items)}")
            return
        if page_key in self.prefetched_grid_pages:
            self.apply_cached_grid_artwork(items)
            write_artwork_performance_log("grid_prefetch_skipped", started, f"page={page_label} reason=cached items={len(items)}")
            return
        if self.active_grid_prefetch_pages and page_label != "current":
            if self.queue_grid_prefetch(items, page_key, page_label, delay):
                write_artwork_performance_log("grid_prefetch_queued", started, f"page={page_label} items={len(items)}")
            return
        self.active_grid_prefetch_pages.add(page_key)
        self.prefetch_grid_items(items, page_key, page_label, delay)

    def queue_grid_prefetch(
        self,
        items: list[MediaItem],
        page_key: tuple[str, ...],
        page_label: str,
        delay: float = 0.0,
    ) -> bool:
        pending = (items, page_key, page_label, delay)
        if pending in self.pending_grid_prefetches:
            return False
        self.pending_grid_prefetches = [
            queued
            for queued in self.pending_grid_prefetches
            if queued[1] != page_key and queued[2] != page_label
        ]
        if page_label == "current":
            self.pending_grid_prefetches.insert(0, pending)
        else:
            self.pending_grid_prefetches.append(pending)
        return True

    def drain_grid_prefetch_queue(self) -> None:
        if self.active_grid_prefetch_pages:
            return
        while self.pending_grid_prefetches:
            items, page_key, page_label, delay = self.pending_grid_prefetches.pop(0)
            if page_key in self.prefetched_grid_pages:
                self.apply_cached_grid_artwork(items)
                write_artwork_performance_log("grid_prefetch_skipped", time.perf_counter(), f"page={page_label} reason=cached items={len(items)}")
                continue
            self.active_grid_prefetch_pages.add(page_key)
            self.prefetch_grid_items(items, page_key, page_label, delay)
            return

    @work(thread=True)
    def prefetch_grid_items(
        self,
        items: list[MediaItem],
        page_key: tuple[str, ...],
        page_label: str,
        delay: float = 0.0,
    ) -> None:
        if not artwork_enabled(self.config):
            self.active_grid_prefetch_pages.discard(page_key)
            self.call_from_thread(self.drain_grid_prefetch_queue)
            return
        started = time.perf_counter()
        if delay:
            time.sleep(delay)

        rendered: dict[str, object] = {}
        fetch_ms = 0.0
        render_ms = 0.0
        cached_count = 0
        rendered_cache_hits = 0
        failed_count = 0
        try:
            prefetch_items = [item for item in items if item.artwork_path]
            width, height = card_artwork_fetch_size(self.config)
            cached_count = sum(
                1 for item in prefetch_items if artwork_is_cached(item.artwork_path, self.config, width=width, height=height)
            )
            pending_items = []
            for item in prefetch_items:
                cache_key = grid_artwork_cache_key(item, self.config)
                artwork = self.rendered_grid_artwork_cache.get(cache_key)
                if artwork is None:
                    pending_items.append(item)
                    continue
                rendered_cache_hits += 1
                rendered[item.key] = artwork
            if page_label == "current" and rendered:
                self.call_from_thread(self.apply_grid_artworks, dict(rendered))
            if pending_items:
                with ThreadPoolExecutor(max_workers=min(GRID_PREFETCH_WORKERS, len(pending_items))) as executor:
                    futures = [
                        executor.submit(self.render_grid_prefetch_item, item, width, height)
                        for item in pending_items
                    ]
                    for future in as_completed(futures):
                        try:
                            item, artwork, item_fetch_ms, item_render_ms = future.result()
                        except Exception as error:
                            failed_count += 1
                            write_performance_log(
                                "grid_prefetch_item_failed",
                                started,
                                f"page={page_label} error={type(error).__name__}: {error}",
                            )
                            continue
                        fetch_ms += item_fetch_ms
                        render_ms += item_render_ms
                        self.rendered_grid_artwork_cache[grid_artwork_cache_key(item, self.config)] = artwork
                        rendered[item.key] = artwork
                        if page_label == "current":
                            self.call_from_thread(self.apply_grid_artwork, item.key, artwork)
            if rendered and (page_label != "current" or pending_items):
                self.call_from_thread(self.apply_grid_artworks, rendered)

            expected_count = len(prefetch_items)
            if len(rendered) == expected_count:
                self.prefetched_grid_pages.add(page_key)
            write_performance_log(
                "grid_prefetch",
                started,
                f"page={page_label} items={len(items)} expected={expected_count} rendered={len(rendered)} failed={failed_count} cached={cached_count} rendered_cached={rendered_cache_hits} fetch={fetch_ms:.1f}ms render={render_ms:.1f}ms workers={GRID_PREFETCH_WORKERS}",
            )
        finally:
            self.active_grid_prefetch_pages.discard(page_key)
            self.call_from_thread(self.drain_grid_prefetch_queue)

    def render_grid_prefetch_item(self, item: MediaItem, width: int, height: int) -> tuple[MediaItem, object, float, float]:
        fetch_started = time.perf_counter()
        data = fetch_artwork(item.raw, item.artwork_path, self.config, width=width, height=height)
        fetch_ms = (time.perf_counter() - fetch_started) * 1000
        render_started = time.perf_counter()
        artwork = render_card_artwork(data, self.config)
        render_ms = (time.perf_counter() - render_started) * 1000
        return item, artwork, fetch_ms, render_ms

    def apply_grid_artwork(self, media_key: str, artwork: object) -> None:
        self.apply_grid_artworks({media_key: artwork})

    def apply_cached_grid_artwork(self, items: list[MediaItem]) -> None:
        try:
            grid = self.query_one("#media-grid", MediaGrid)
        except NoMatches:
            return
        self.hydrate_grid_artwork_from_cache(grid, items)

    def hydrate_grid_artwork_from_cache(self, grid: MediaGrid, items: list[MediaItem]) -> None:
        if not artwork_enabled(self.config):
            return
        artwork_by_key = {}
        for item in items:
            if not item.artwork_path or item.key in grid.artwork:
                continue
            artwork = self.rendered_grid_artwork_cache.get(grid_artwork_cache_key(item, self.config))
            if artwork is not None:
                artwork_by_key[item.key] = artwork
        if artwork_by_key:
            grid.artwork.update(artwork_by_key)
            visible_keys = {item.key for item in grid.visible_page_items()}
            if visible_keys.intersection(artwork_by_key):
                grid.refresh_grid()
            write_artwork_performance_log("grid_artwork_hydrated", time.perf_counter(), f"items={len(artwork_by_key)}")

    def apply_grid_artworks(self, artwork_by_key: dict[str, object]) -> None:
        try:
            grid = self.query_one("#media-grid", MediaGrid)
        except NoMatches:
            return
        if not grid.is_mounted:
            return
        grid.artwork.update(artwork_by_key)
        visible_keys = {item.key for item in grid.visible_page_items()}
        visible_applied = visible_keys.intersection(artwork_by_key)
        write_artwork_performance_log(
            "grid_artwork_applied",
            time.perf_counter(),
            f"items={len(artwork_by_key)} visible={len(visible_applied)}",
        )
        if visible_applied:
            grid.refresh_grid()

    def action_show_settings(self, selected_action: str | None = None) -> None:
        self.help_visible = False
        self.picker_visible = False
        self.settings_visible = True
        self.set_media_title("Settings")
        view = self.show_media_list()
        view.clear()
        selected_index = 0
        rows = settings_rows(self.config, self.libraries)
        for index, row in enumerate(rows):
            if selected_action and isinstance(row, SettingsActionRow) and row.action == selected_action:
                selected_index = index
                break
        for row in rows:
            view.append(row)
        self.show_detail_text(render_settings(self.config))
        view.focus()
        set_list_index(view, selected_index)
        view.call_after_refresh(set_list_index, view, selected_index)
        self.set_status("Settings")

    def refresh_settings_after_change(self, action: str, label: str, value: str) -> None:
        self.action_show_settings(selected_action=action)
        self.show_settings_action_details(render_settings_change_details(action, label, value, self.config))
        self.set_status(f"{label}: {value}")

    def show_settings_action_details(self, content: str) -> None:
        self.show_detail_text(content)
        try:
            self.query_one("#media", ListView).call_after_refresh(self.show_detail_text, content)
        except NoMatches:
            return

    def action_show_help(self) -> None:
        self.help_visible = True
        self.settings_visible = False
        self.picker_visible = False
        self.set_media_title("Help")
        rows = [ListItem(Label(line)) for line in render_help().splitlines()]
        self.show_media_list()
        self.replace_media_rows(rows, 0 if rows else None)
        self.show_detail_text("Keyboard reference. Press escape to return.")
        self.query_one("#media", ListView).focus()
        self.set_status("Help")

    def run_settings_action(self, action: str) -> None:
        if confirmation_required(action) and self.pending_confirmation_action != action:
            self.pending_confirmation_action = action
            self.show_detail_text(f"Confirm Action\n\n{settings_action_label(action)}\n\nPress Enter on the same row again to confirm.")
            self.set_status(f"Press Enter again to confirm: {settings_action_label(action)}")
            return
        if action != self.pending_confirmation_action:
            self.pending_confirmation_action = ""
        if action == "reload":
            self.settings_visible = False
            self.load_server()
            return
        if action == "relogin":
            self.settings_visible = False
            self.selected_audio = None
            self.selected_subtitle = None
            self.begin_login()
            return
        if action == "switch_profile":
            self.load_profiles()
            return
        if action == "clear_tracks":
            self.pending_confirmation_action = ""
            self.selected_audio = None
            self.selected_subtitle = None
            if not self.update_preferences(
                preferred_audio_language="",
                preferred_subtitle_language="",
                subtitle_mode="auto",
            ):
                return
            self.refresh_settings_after_change(action, "Audio/subtitle preferences", "Plex/default")
            return
        if action == "clear_audio":
            self.pending_confirmation_action = ""
            if self.update_preferences(preferred_audio_language=""):
                self.refresh_settings_after_change(action, "Audio preference", "Plex/default")
            return
        if action == "subtitle_auto":
            if self.update_preferences(preferred_subtitle_language="", subtitle_mode="auto"):
                self.refresh_settings_after_change(action, "Subtitle preference", "Auto")
            return
        if action == "subtitle_none":
            if self.update_preferences(preferred_subtitle_language="", subtitle_mode="none"):
                self.refresh_settings_after_change(action, "Subtitle preference", "None")
            return
        if action == "clear_subtitle":
            self.pending_confirmation_action = ""
            if self.update_preferences(preferred_subtitle_language="", subtitle_mode="auto"):
                self.refresh_settings_after_change(action, "Subtitle preference", "Auto")
            return
        if action == "cycle_subtitle_mode":
            self.action_cycle_subtitle_mode()
            if self.settings_visible:
                self.refresh_settings_after_change(action, "Subtitle mode", subtitle_mode_value(self.config))
            return
        if action == "toggle_artwork":
            next_mode = "off" if self.config.artwork_mode == "on" else "on"
            if self.update_preferences(artwork_mode=next_mode):
                self.refresh_settings_after_change(action, "Artwork", artwork_mode_value(self.config))
            return
        if action == "cycle_detail_artwork":
            next_mode = next_detail_artwork_mode(self.config.detail_artwork_mode)
            if self.update_preferences(detail_artwork_mode=next_mode):
                self.refresh_settings_after_change(action, "Details artwork", detail_artwork_mode_value(self.config))
            return
        if action == "toggle_media_view":
            self.action_toggle_media_view()
            return
        if action == "toggle_show_playlists":
            if self.update_preferences(show_playlists=not self.config.show_playlists):
                self.populate_libraries(visible_libraries(self.libraries, self.config))
                self.refresh_settings_after_change(action, "Playlists Sidebar", show_setting_value(self.config.show_playlists))
            return
        if action == "toggle_show_discover":
            if self.update_preferences(show_discover=not self.config.show_discover):
                self.populate_libraries(visible_libraries(self.libraries, self.config))
                self.refresh_settings_after_change(action, "Discover Sidebar", show_setting_value(self.config.show_discover))
            return
        if action == "toggle_show_on_plex":
            if self.update_preferences(show_on_plex=not self.config.show_on_plex):
                self.populate_libraries(visible_libraries(self.libraries, self.config))
                self.refresh_settings_after_change(action, "On Plex Sidebar", show_setting_value(self.config.show_on_plex))
            return
        if action == "cycle_discover_media_type":
            next_media_type = next_discover_media_type(self.config.discover_media_type)
            if self.update_preferences(discover_media_type=next_media_type):
                self.refresh_settings_after_change(action, "Discover Type", discover_media_type_value(self.config))
            return
        if action == "toggle_confirm_start_over":
            if self.update_preferences(confirm_start_over=not self.config.confirm_start_over):
                self.refresh_settings_after_change(action, "Start Over Prompt", show_setting_value(self.config.confirm_start_over))
            return
        if action == "cycle_library_enter_action":
            next_action = next_library_enter_action(self.config.library_enter_action)
            if self.update_preferences(library_enter_action=next_action):
                self.refresh_settings_after_change(action, "Library Enter", library_enter_action_value(self.config))
            return
        if action.startswith("toggle_library_visibility:"):
            self.toggle_library_visibility(action.removeprefix("toggle_library_visibility:"))
            return
        if action.startswith("move_library_up:"):
            self.move_library(action.removeprefix("move_library_up:"), -1)
            return
        if action.startswith("move_library_down:"):
            self.move_library(action.removeprefix("move_library_down:"), 1)
            return
        if action == "cycle_grid_density":
            next_density = next_grid_density(self.config.grid_density)
            if self.update_preferences(grid_density=next_density):
                self.refresh_settings_after_change(action, "Grid density", grid_density_value(self.config))
            return
        if action == "cycle_mpv_window_size":
            self.action_cycle_mpv_window_size()
            return
        if action == "cycle_playback_mode":
            next_mode = next_playback_mode(self.config.playback_mode)
            if self.update_preferences(playback_mode=next_mode):
                self.refresh_settings_after_change(action, "Playback mode", playback_mode_value(self.config))
            return
        if action == "cycle_playback_display":
            next_display = next_playback_display(self.config.playback_display)
            if self.update_preferences(playback_display=next_display):
                self.refresh_settings_after_change(action, "Playback display", playback_display_value(self.config))
            return
        if action == "cycle_terminal_video_profile":
            next_profile = next_terminal_video_profile(self.config.terminal_video_profile)
            if self.update_preferences(terminal_video_profile=next_profile):
                self.refresh_settings_after_change(action, "Terminal video", terminal_video_profile_value(self.config))
            return
        if action == "cycle_transcode_quality":
            next_quality = next_transcode_quality(self.config.transcode_quality)
            if self.update_preferences(transcode_quality=next_quality):
                self.refresh_settings_after_change(action, "Transcode quality", transcode_quality_value(self.config))
            return
        if action == "set_mpv_window_size":
            self.prompt_mpv_window_size()
            return
        if action == "reset_mpv_window_size":
            if self.update_preferences(mpv_window_size=""):
                self.refresh_settings_after_change(action, "mpv window size", mpv_window_size_value(self.config))
            return
        if action == "increase_page_size":
            if self.update_numeric_preference("page_size", 10, MIN_PAGE_SIZE, MAX_PAGE_SIZE):
                self.set_status(f"Page size: {self.config.page_size}")
            return
        if action == "decrease_page_size":
            if self.update_numeric_preference("page_size", -10, MIN_PAGE_SIZE, MAX_PAGE_SIZE):
                self.set_status(f"Page size: {self.config.page_size}")
            return
        if action == "reset_page_size":
            if self.update_preferences(page_size=DEFAULT_PAGE_SIZE):
                self.refresh_settings_after_change(action, "Page size", str(self.config.page_size))
            return
        if action == "set_page_size":
            self.prompt_numeric_setting(
                "page_size",
                "Page size",
                self.config.page_size,
                MIN_PAGE_SIZE,
                MAX_PAGE_SIZE,
                DEFAULT_PAGE_SIZE,
            )
            return
        if action == "increase_auto_load_threshold":
            if self.update_numeric_preference("auto_load_threshold", 5, MIN_AUTO_LOAD_THRESHOLD, MAX_AUTO_LOAD_THRESHOLD):
                self.set_status(f"Auto-load threshold: {self.config.auto_load_threshold}")
            return
        if action == "decrease_auto_load_threshold":
            if self.update_numeric_preference("auto_load_threshold", -5, MIN_AUTO_LOAD_THRESHOLD, MAX_AUTO_LOAD_THRESHOLD):
                self.set_status(f"Auto-load threshold: {self.config.auto_load_threshold}")
            return
        if action == "reset_auto_load_threshold":
            if self.update_preferences(auto_load_threshold=DEFAULT_AUTO_LOAD_THRESHOLD):
                self.refresh_settings_after_change(action, "Auto-load threshold", str(self.config.auto_load_threshold))
            return
        if action == "set_auto_load_threshold":
            self.prompt_numeric_setting(
                "auto_load_threshold",
                "Auto-load threshold",
                self.config.auto_load_threshold,
                MIN_AUTO_LOAD_THRESHOLD,
                MAX_AUTO_LOAD_THRESHOLD,
                DEFAULT_AUTO_LOAD_THRESHOLD,
            )
            return
        if action == "increase_grid_prefetch_pages":
            if self.update_numeric_preference("grid_prefetch_pages", 1, MIN_GRID_PREFETCH_PAGES, MAX_GRID_PREFETCH_PAGES):
                self.set_status(f"Grid prefetch pages: {self.config.grid_prefetch_pages}")
            return
        if action == "decrease_grid_prefetch_pages":
            if self.update_numeric_preference("grid_prefetch_pages", -1, MIN_GRID_PREFETCH_PAGES, MAX_GRID_PREFETCH_PAGES):
                self.set_status(f"Grid prefetch pages: {self.config.grid_prefetch_pages}")
            return
        if action == "reset_grid_prefetch_pages":
            if self.update_preferences(grid_prefetch_pages=DEFAULT_GRID_PREFETCH_PAGES):
                self.refresh_settings_after_change(action, "Grid prefetch pages", str(self.config.grid_prefetch_pages))
            return
        if action == "set_grid_prefetch_pages":
            self.prompt_numeric_setting(
                "grid_prefetch_pages",
                "Grid prefetch pages",
                self.config.grid_prefetch_pages,
                MIN_GRID_PREFETCH_PAGES,
                MAX_GRID_PREFETCH_PAGES,
                DEFAULT_GRID_PREFETCH_PAGES,
            )
            return
        if action == "show_debug_log":
            path = debug_log_path()
            self.show_settings_action_details(
                f"Debug log\n\n{path}\n\n"
                "Set PLEX_TUI_PERF_LOG=1 before launch to include browsing performance timings.\n"
                "Set PLEX_TUI_ARTWORK_LOG=1 as well to include verbose grid artwork internals."
            )
            self.set_status(f"Debug log: {path}")
            return
        if action == "show_recent_debug_log":
            path = debug_log_path()
            self.show_settings_action_details(render_debug_log_details(path))
            self.set_status(f"Recent debug log: {path}")
            return
        if action == "show_app_diagnostics":
            self.show_settings_action_details(render_app_diagnostics(self.config, detect_mpv()))
            self.set_status("App diagnostics")
            return
        if action == "artwork_renderer_block":
            if self.update_preferences(artwork_renderer="block"):
                self.refresh_settings_after_change(action, "Artwork renderer", "Block")
            return
        if action == "artwork_renderer_auto":
            if self.update_preferences(artwork_renderer="auto"):
                self.refresh_settings_after_change(action, "Artwork renderer", "Auto")
            return
        if action == "artwork_renderer_kitty":
            if self.update_preferences(artwork_renderer="kitty"):
                self.refresh_settings_after_change(action, "Artwork renderer", "Kitty")
            return
        if action == "cycle_artwork_renderer":
            next_renderer = next_artwork_renderer(self.config.artwork_renderer)
            if self.update_preferences(artwork_renderer=next_renderer):
                self.refresh_settings_after_change(action, "Artwork renderer", artwork_renderer_value(self.config))
            return
        self.set_status(f"Unknown settings action: {action}")

    def toggle_library_visibility(self, library_key: str) -> None:
        hidden = set(self.config.hidden_library_keys)
        if library_key in hidden:
            hidden.remove(library_key)
        else:
            hidden.add(library_key)
        next_hidden = tuple(key for key in self.config.hidden_library_keys if key in hidden)
        if library_key in hidden and library_key not in next_hidden:
            next_hidden = (*next_hidden, library_key)
        if not self.update_preferences(hidden_library_keys=next_hidden):
            return
        visible = visible_libraries(self.libraries, self.config)
        self.populate_libraries(visible)
        library = library_by_key(self.libraries, library_key)
        label = library.title if library is not None else library_key
        value = "Hidden" if library_key in self.config.hidden_library_keys else "Visible"
        self.refresh_settings_after_change(f"toggle_library_visibility:{library_key}", f"Library: {label}", value)

    def move_library(self, library_key: str, direction: int) -> None:
        current = ordered_libraries(self.libraries, self.config)
        keys = [library.key for library in current]
        try:
            index = keys.index(library_key)
        except ValueError:
            self.set_status("Library is no longer available")
            return
        target = index + direction
        if target < 0 or target >= len(keys):
            library = current[index]
            self.refresh_settings_after_change(
                f"move_library_{'up' if direction < 0 else 'down'}:{library_key}",
                f"Library order: {library.title}",
                "No change",
            )
            return
        keys[index], keys[target] = keys[target], keys[index]
        if not self.update_preferences(library_order_keys=tuple(keys)):
            return
        visible = visible_libraries(self.libraries, self.config)
        self.populate_libraries(visible, selected_library_key=library_key)
        library = library_by_key(self.libraries, library_key)
        label = library.title if library is not None else library_key
        position = target + 1
        self.refresh_settings_after_change(
            f"move_library_{'up' if direction < 0 else 'down'}:{library_key}",
            f"Library order: {label}",
            f"Position {position}",
        )

    def action_subtitle_picker(self) -> None:
        media = self.selected_media()
        if media is None or not media.playable:
            self.set_status("Select playable media before choosing subtitles")
            return
        self.open_stream_picker(media, "subtitle")

    def action_audio_picker(self) -> None:
        media = self.selected_media()
        if media is None or not media.playable:
            self.set_status("Select playable media before choosing audio")
            return
        self.open_stream_picker(media, "audio")

    def action_clear_audio_preference(self) -> None:
        if self.update_preferences(preferred_audio_language=""):
            self.set_status("Cleared audio preference")

    def action_cycle_subtitle_mode(self) -> None:
        if self.config.subtitle_mode == "auto":
            changes = {"preferred_subtitle_language": "", "subtitle_mode": "none"}
        else:
            changes = {"preferred_subtitle_language": "", "subtitle_mode": "auto"}
        if self.update_preferences(**changes):
            self.set_status(f"Subtitle preference: {subtitle_preference_value(self.config)}")

    def action_cycle_mpv_window_size(self) -> None:
        next_size = next_mpv_window_size(self.config.mpv_window_size)
        if self.update_preferences(mpv_window_size=next_size):
            if self.settings_visible:
                self.refresh_settings_after_change(
                    "cycle_mpv_window_size",
                    "mpv window size",
                    mpv_window_size_value(self.config),
                )
                return
            self.set_status(f"mpv window size: {mpv_window_size_value(self.config)}")

    @work(thread=True)
    def open_stream_picker(self, media: MediaItem, stream_type: str) -> None:
        self.post_message(StatusChanged(f"Loading {stream_type} tracks..."))
        try:
            choices = subtitle_choices(media.raw) if stream_type == "subtitle" else audio_choices(media.raw)
        except Exception as exc:
            self.call_from_thread(self.show_error, str(exc))
            return

        def update() -> None:
            current_choice = self.current_stream_choice(media.raw, choices, stream_type)
            current_index = selected_stream_index(choices, current_choice)
            self.picker_visible = True
            self.settings_visible = False
            self.picker_media_key = media.key
            picker_title = "Subtitle Tracks" if stream_type == "subtitle" else "Audio Tracks"
            self.set_media_title(f"{picker_title}: {media.title}")
            rows = [
                StreamRow(choice, stream_type, stream_choice_matches(choice, current_choice))
                for choice in choices
            ]
            self.show_media_list()
            self.replace_media_rows(rows, current_index if choices else None)
            view = self.query_one("#media", ListView)
            view.focus()
            self.show_detail_text(render_picker_details(stream_type, current_choice, self.config))
            self.set_status(f"Choose {stream_type} track")

        self.call_from_thread(update)

    def choose_stream(self, choice: StreamChoice, stream_type: str) -> None:
        try:
            self.save_stream_preference(choice, stream_type)
        except OSError as exc:
            self.show_error(f"failed to save preference: {exc}")
            return
        live_updated = self.apply_live_stream_choice(choice, stream_type)
        active_unchanged = bool(self.player is not None and self.player.active and not live_updated)
        if stream_type == "subtitle":
            self.selected_subtitle = None
            status = f"Subtitle preference: {choice.label}"
        elif stream_type == "audio":
            self.selected_audio = None
            status = f"Audio preference: {choice.label}"
        else:
            status = f"Stream preference: {choice.label}"
        if live_updated:
            status += " / active playback updated"
        elif active_unchanged:
            status += " / active playback unchanged"
        self.picker_visible = False
        if self.browsing_stack:
            state = self.browsing_stack[-1]
            self.show_browse_state(state, selected_key=self.picker_media_key)
        self.picker_media_key = None
        self.focus_media_browser()
        self.set_status(status)
        self.set_timer(0.05, lambda: self.set_status(status), name="stream-choice-status")

    def action_add_to_playlist(self) -> None:
        items = self.playlist_action_items()
        if not items:
            self.set_status("No media selected")
            return
        unplayable = [item for item in items if not item.playable]
        if unplayable:
            self.set_status("Select playable media before adding to a playlist")
            return
        if self.service is None:
            self.set_status("Connect to Plex before managing playlists")
            return
        self.open_playlist_picker(items)

    @work(thread=True)
    def open_playlist_picker(self, items: list[MediaItem]) -> None:
        if self.service is None:
            return
        media = items[0]
        self.post_message(StatusChanged("Loading playlists..."))
        try:
            playlists = self.service.playlists()
        except Exception as exc:
            self.call_from_thread(self.show_error, f"failed to load playlists: {exc}")
            return

        def update() -> None:
            self.picker_visible = True
            self.playlist_picker_visible = True
            self.settings_visible = False
            self.picker_media_key = media.key
            self.playlist_picker_item = media
            self.playlist_picker_items = items
            self.set_media_title(f"Add to Playlist: {media.title}")
            rows: list[ListItem] = [PlaylistCreateRow()]
            rows.extend(PlaylistTargetRow(playlist) for playlist in playlists)
            self.show_media_list()
            self.replace_media_rows(rows, 0)
            view = self.query_one("#media", ListView)
            view.focus()
            self.show_detail_text(render_playlist_picker_details(items, len(playlists)))
            self.set_status("Choose playlist target")

        self.call_from_thread(update)

    def choose_playlist_target(self, playlist: MediaItem) -> object | None:
        items = self.playlist_picker_items or ([self.playlist_picker_item] if self.playlist_picker_item is not None else [])
        if not items:
            self.set_status("No media selected for playlist")
            return None
        self.set_status(f"Adding {playlist_items_label(items)} to {playlist.title}...")
        return self.add_items_to_playlist(playlist, items)

    @work(thread=True, exclusive=True, group="playlist")
    def add_items_to_playlist(self, playlist: MediaItem, items: list[MediaItem]) -> None:
        if self.service is None:
            return
        try:
            updated_playlist = self.service.add_items_to_playlist(playlist, items)
        except Exception as exc:
            self.call_from_thread(self.show_error, f"failed to add to playlist: {exc}")
            return
        self.call_from_thread(self.finish_playlist_add, updated_playlist, items)

    def add_item_to_playlist(self, playlist: MediaItem, item: MediaItem) -> object | None:
        return self.add_items_to_playlist(playlist, [item])

    def prompt_playlist_name(self) -> None:
        items = self.playlist_picker_items or ([self.playlist_picker_item] if self.playlist_picker_item is not None else [])
        if not items:
            self.set_status("No media selected for playlist")
            return
        self.input_mode = "playlist_name"
        search = self.query_one("#search", Input)
        search.placeholder = f"New playlist name for {playlist_items_label(items)}"
        search.value = ""
        search.password = False
        search.display = True
        search.focus()
        self.show_detail_text(f"Enter a name for a new playlist containing {playlist_items_label(items)}.")
        self.set_status("Enter new playlist name")

    def save_playlist_name_input(self, value: str) -> object | None:
        title = value.strip()
        if not title:
            self.prompt_playlist_name()
            self.set_status("Playlist name is required")
            return None
        items = self.playlist_picker_items or ([self.playlist_picker_item] if self.playlist_picker_item is not None else [])
        if not items:
            self.input_mode = ""
            self.set_status("No media selected for playlist")
            return None
        self.input_mode = ""
        self.set_status(f"Creating playlist {title}...")
        return self.create_playlist_from_items(title, items)

    def playlist_action_target(self) -> MediaItem | None:
        media = self.selected_media()
        if media is not None and media.kind == "playlist":
            return media
        state = self.current_browse_state()
        if is_playlist_browse_state(state):
            return state.context_media
        return None

    def action_rename_playlist(self) -> None:
        playlist = self.playlist_action_target()
        if playlist is None:
            self.set_status("Select or open a playlist before renaming")
            return
        self.prompt_playlist_rename(playlist)

    def prompt_playlist_rename(self, playlist: MediaItem) -> None:
        self.playlist_picker_item = playlist
        self.input_mode = "playlist_rename"
        search = self.query_one("#search", Input)
        search.placeholder = f"Rename playlist: {playlist.title}"
        search.value = playlist.title
        search.password = False
        search.display = True
        search.focus()
        self.show_detail_text(f"Enter a new name for playlist {playlist.title}.")
        self.set_status("Enter playlist name")

    def save_playlist_rename_input(self, value: str) -> object | None:
        title = value.strip()
        playlist = self.playlist_picker_item
        if playlist is None:
            self.input_mode = ""
            self.set_status("No playlist selected")
            return None
        if not title:
            self.prompt_playlist_rename(playlist)
            self.set_status("Playlist name is required")
            return None
        self.input_mode = ""
        self.set_status(f"Renaming playlist {playlist.title}...")
        return self.rename_playlist(playlist, title)

    @work(thread=True, exclusive=True, group="playlist")
    def rename_playlist(self, playlist: MediaItem, title: str) -> None:
        if self.service is None:
            return
        try:
            renamed = self.service.rename_playlist(playlist, title)
        except Exception as exc:
            self.call_from_thread(self.show_error, f"failed to rename playlist: {exc}")
            return
        self.call_from_thread(self.apply_playlist_rename, playlist, renamed)

    def apply_playlist_rename(self, old_playlist: MediaItem, renamed: MediaItem) -> None:
        self.playlist_picker_item = None
        self.replace_playlist_reference(old_playlist.key, renamed)
        status = f"Renamed playlist to {renamed.title}"
        state = self.current_browse_state()
        selected_key = renamed.key
        if state is not None:
            if is_playlist_browse_state(state):
                state.title = renamed.title
                state.context_media = renamed
            self.show_browse_state(state, selected_key=selected_key)
            self.focus_media_browser()
        self.set_status(status)
        self.set_timer(0.2, lambda: self.set_status(status), name="playlist-rename-status")

    def action_delete_playlist(self) -> None:
        playlist = self.playlist_action_target()
        if playlist is None:
            self.set_status("Select or open a playlist before deleting")
            return
        action = f"delete_playlist:{playlist.key}"
        if self.pending_confirmation_action != action:
            self.pending_confirmation_action = action
            self.playlist_picker_item = playlist
            self.show_detail_text(f"Delete Playlist\n\n{playlist.title}\n\nPress D again to confirm.")
            self.set_status(f"Press D again to delete playlist {playlist.title}")
            return
        self.pending_confirmation_action = ""
        self.set_status(f"Deleting playlist {playlist.title}...")
        return self.delete_playlist(playlist)

    @work(thread=True, exclusive=True, group="playlist")
    def delete_playlist(self, playlist: MediaItem) -> None:
        if self.service is None:
            return
        try:
            self.service.delete_playlist(playlist)
        except Exception as exc:
            self.call_from_thread(self.show_error, f"failed to delete playlist: {exc}")
            return
        self.call_from_thread(self.apply_playlist_delete, playlist)

    def apply_playlist_delete(self, playlist: MediaItem) -> None:
        self.playlist_picker_item = None
        self.pending_confirmation_action = ""
        status = f"Deleted playlist {playlist.title}"
        state = self.current_browse_state()
        if state is not None:
            if is_playlist_browse_state(state) and state.context_media is not None and state.context_media.key == playlist.key:
                self.browsing_stack.pop()
                state = self.current_browse_state()
            if state is not None:
                state.items = [item for item in state.items if item.key != playlist.key]
                state.total = max(0, state.total - 1) if state.total else len(state.items)
                self.show_browse_state(state)
                self.focus_media_browser()
        self.set_status(status)
        self.set_timer(0.2, lambda: self.set_status(status), name="playlist-delete-status")

    def replace_playlist_reference(self, playlist_key: str, playlist: MediaItem) -> None:
        for state in self.browsing_stack:
            state.items = [playlist if item.key == playlist_key else item for item in state.items]
            if state.context_media is not None and state.context_media.key == playlist_key:
                state.context_media = playlist

    @work(thread=True, exclusive=True, group="playlist")
    def create_playlist_from_items(self, title: str, items: list[MediaItem]) -> None:
        if self.service is None:
            return
        try:
            playlist = self.service.create_playlist_from_items(title, items)
        except Exception as exc:
            self.call_from_thread(self.show_error, f"failed to create playlist: {exc}")
            return
        self.call_from_thread(self.finish_playlist_add, playlist, items, created=True)

    def create_playlist_from_item(self, title: str, item: MediaItem) -> object | None:
        return self.create_playlist_from_items(title, [item])

    def finish_playlist_add(self, playlist: MediaItem, items: list[MediaItem], created: bool = False) -> None:
        item_label = playlist_items_label(items)
        status = f"Created playlist {playlist.title} with {item_label}" if created else f"Added {item_label} to {playlist.title}"
        self.picker_visible = False
        self.playlist_picker_visible = False
        self.playlist_picker_item = None
        self.playlist_picker_items = []
        self.bulk_selected_keys.clear()
        if self.browsing_stack:
            state = self.browsing_stack[-1]
            self.show_browse_state(state, selected_key=self.picker_media_key)
        self.picker_media_key = None
        self.focus_media_browser()
        self.set_status(status)
        self.set_timer(0.2, lambda: self.set_status(status), name="playlist-add-status")

    def apply_live_stream_choice(self, choice: StreamChoice, stream_type: str) -> bool:
        if self.player is None or not self.player.active or not self.picker_media_key:
            return False
        media = self.media_by_key(self.picker_media_key)
        if media is None:
            return False
        try:
            updated = switch_mpv_stream(self.player, media.raw, choice, stream_type)
        except Exception:
            return False
        if updated:
            self.set_playback_footer(f"{self.player.title}: {stream_type} {choice.label} / {PLAYBACK_CONTROL_HINT}")
        return updated

    def media_by_key(self, media_key: str) -> MediaItem | None:
        for state in reversed(self.browsing_stack):
            for item in state.items:
                if item.key == media_key:
                    return item
        return None

    def save_stream_preference(self, choice: StreamChoice, stream_type: str) -> None:
        if stream_type == "audio":
            self.config = replace(self.config, preferred_audio_language=stream_preference_key(choice))
        elif choice.stream_id is None:
            self.config = replace(self.config, preferred_subtitle_language="", subtitle_mode="auto")
        elif choice.stream_id == 0:
            self.config = replace(self.config, preferred_subtitle_language="", subtitle_mode="none")
        else:
            self.config = replace(
                self.config,
                preferred_subtitle_language=stream_preference_key(choice),
                subtitle_mode="preferred",
            )
        save_config(self.config)

    def update_preferences(self, **changes: object) -> bool:
        self.config = replace(self.config, **changes)
        try:
            save_config(self.config)
        except OSError as exc:
            self.show_error(f"failed to save preference: {exc}")
            return False
        return True

    def update_numeric_preference(self, name: str, step: int, minimum: int, maximum: int) -> bool:
        current = int(getattr(self.config, name))
        value = min(maximum, max(minimum, current + step))
        if value == current:
            self.action_show_settings()
            return True
        if not self.update_preferences(**{name: value}):
            return False
        label = numeric_setting_label(name)
        self.refresh_settings_after_change(f"set_{name}", label, str(value))
        return True

    def prompt_mpv_window_size(self) -> None:
        self.input_mode = "mpv_window_size"
        search = self.query_one("#search", Input)
        search.placeholder = f'mpv window size: 80%, 90%, 1280x720, or empty for default {DEFAULT_MPV_WINDOW_SIZE}'
        search.value = self.config.mpv_window_size
        search.password = False
        search.display = True
        search.focus()
        self.show_detail_text(
            f"Enter an mpv --autofit value. Examples: 80%, 90%, 1280x720, 80%x80%. "
            f"Submit empty to use Default ({DEFAULT_MPV_WINDOW_SIZE})."
        )
        self.set_status("Enter custom mpv window size")

    def save_mpv_window_size_input(self, value: str) -> None:
        size = value.strip()
        if size and not valid_mpv_window_size(size):
            self.prompt_mpv_window_size()
            self.set_status("Invalid mpv window size. Use 80%, 90%, 1280x720, or 80%x80%.")
            return
        if not self.update_preferences(mpv_window_size=size):
            return
        self.input_mode = ""
        self.refresh_settings_after_change("set_mpv_window_size", "mpv window size", mpv_window_size_value(self.config))

    def prompt_numeric_setting(
        self,
        name: str,
        label: str,
        current: int,
        minimum: int,
        maximum: int,
        default: int,
    ) -> None:
        self.input_mode = name
        search = self.query_one("#search", Input)
        search.placeholder = f"{label}: {minimum}-{maximum}, or empty for default {default}"
        search.value = str(current)
        search.password = False
        search.display = True
        search.focus()
        self.show_detail_text(f"Enter {label.lower()} as a whole number from {minimum} to {maximum}. Submit empty to reset to {default}.")
        self.set_status(f"Enter custom {label.lower()}")

    def save_numeric_setting_input(
        self,
        name: str,
        label: str,
        value: str,
        minimum: int,
        maximum: int,
        default: int,
    ) -> None:
        text = value.strip()
        if not text:
            parsed = default
        else:
            try:
                parsed = int(text)
            except ValueError:
                self.prompt_numeric_setting(name, label, int(getattr(self.config, name)), minimum, maximum, default)
                self.set_status(f"Invalid {label.lower()}. Use a whole number from {minimum} to {maximum}.")
                return
            if parsed < minimum or parsed > maximum:
                self.prompt_numeric_setting(name, label, int(getattr(self.config, name)), minimum, maximum, default)
                self.set_status(f"Invalid {label.lower()}. Use a whole number from {minimum} to {maximum}.")
                return
        if not self.update_preferences(**{name: parsed}):
            return
        self.input_mode = ""
        self.refresh_settings_after_change(f"set_{name}", label, str(parsed))

    def current_stream_choice(
        self,
        item: object,
        choices: list[StreamChoice],
        stream_type: str,
    ) -> StreamChoice | None:
        if stream_type == "subtitle":
            choice = preferred_subtitle_choice(
                item,
                self.config.preferred_subtitle_language,
                self.config.subtitle_mode,
            )
            if choice is not None:
                return choice
            return choices[0] if choices else None
        choice = preferred_audio_choice(item, self.config.preferred_audio_language)
        if choice is not None:
            return choice
        for candidate in choices:
            if getattr(candidate.stream, "selected", False):
                return candidate
        return choices[0] if choices else None

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            query = event.value.strip()
            event.input.display = False
            event.input.value = ""
            event.input.password = False
            if self.input_mode == "profile_pin":
                choice = self.pending_profile_choice
                self.input_mode = ""
                if choice is not None:
                    self.switch_to_profile(choice, query)
                return
            if self.input_mode == "mpv_window_size":
                self.save_mpv_window_size_input(query)
                return
            if self.input_mode == "page_size":
                self.save_numeric_setting_input("page_size", "Page size", query, MIN_PAGE_SIZE, MAX_PAGE_SIZE, DEFAULT_PAGE_SIZE)
                return
            if self.input_mode == "auto_load_threshold":
                self.save_numeric_setting_input(
                    "auto_load_threshold",
                    "Auto-load threshold",
                    query,
                    MIN_AUTO_LOAD_THRESHOLD,
                    MAX_AUTO_LOAD_THRESHOLD,
                    DEFAULT_AUTO_LOAD_THRESHOLD,
                )
                return
            if self.input_mode == "grid_prefetch_pages":
                self.save_numeric_setting_input(
                    "grid_prefetch_pages",
                    "Grid prefetch pages",
                    query,
                    MIN_GRID_PREFETCH_PAGES,
                    MAX_GRID_PREFETCH_PAGES,
                    DEFAULT_GRID_PREFETCH_PAGES,
                )
                return
            if self.input_mode == "playlist_name":
                self.save_playlist_name_input(query)
                return
            if self.input_mode == "playlist_rename":
                self.save_playlist_rename_input(query)
                return
            if self.input_mode == "discover_search":
                self.input_mode = ""
                self.run_discover_search(query)
                return
            search_global = self.search_global
            self.input_mode = ""
            if not search_global and self.apply_fuzzy_search(query, focus=True):
                return
            self.run_search(query, search_global)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "search":
            return
        if self.input_mode != "search" or self.search_global:
            return
        query = event.value.strip()
        if query:
            self.apply_fuzzy_search(query)
        else:
            self.restore_fuzzy_search_source()

    @work(thread=True, exclusive=True, group="search")
    def run_search(self, query: str, global_search: bool = False) -> None:
        if not query:
            return
        local_source = None if global_search else self.fuzzy_search_source()
        if local_source is not None:
            matches = fuzzy_match_media(query, local_source.items)
            title = f"Fuzzy search: {query}"
            self.post_message(StatusChanged(f"Fuzzy searching {local_source.title} for {query}..."))
            self.call_from_thread(self.show_loading_state, title, f"Matching loaded items from {local_source.title}.")

            def update_fuzzy() -> None:
                self.show_fuzzy_search_results(query, local_source, matches, focus=True)

            self.call_from_thread(update_fuzzy)
            return

        if self.service is None:
            return
        scope = "all libraries" if global_search else "current library"
        self.post_message(StatusChanged(f"Searching {scope} for {query}..."))
        title = f"Global search: {query}" if global_search else f"Search: {query}"
        self.call_from_thread(self.show_loading_state, title, f"Searching {scope}.")
        started = time.perf_counter()
        try:
            library = None if global_search else self.selected_library
            page = self.service.search_page(query, library, 0, self.config.page_size)
        except Exception as exc:
            self.call_from_thread(self.show_error, str(exc))
            return
        write_performance_log(
            "search_page",
            started,
            f"query={query!r} global={global_search} size={self.config.page_size} items={len(page.items)} total={page.total}",
        )

        def update() -> None:
            if self.browsing_stack and self.browsing_stack[-1].search:
                self.browsing_stack.pop()
            state = BrowseState(
                title,
                page.items,
                None if global_search else self.selected_library,
                search=True,
                search_query=query,
                global_search=global_search,
                next_start=page.next_start,
                total=page.total,
            )
            self.browsing_stack.append(state)
            self.show_browse_state(state)
            self.focus_media_browser()
            self.set_status(render_loaded_status(title, len(page.items), page.total, page.has_more, page.items))

        self.call_from_thread(update)

    @work(thread=True, exclusive=True, group="search")
    def run_discover_search(self, query: str) -> None:
        if not query or self.service is None:
            return
        media_type = self.config.discover_media_type
        type_label = discover_media_type_value(self.config)
        title = f"Discover {type_label}: {query}"
        self.post_message(StatusChanged(f"Searching Plex Discover for {query}..."))
        self.call_from_thread(
            self.show_loading_state,
            title,
            f"Searching Plex Discover {type_label.lower()} availability.",
        )
        started = time.perf_counter()
        try:
            page = self.service.discover_page(query, 0, self.config.page_size, media_type)
        except Exception as exc:
            self.call_from_thread(self.show_error, str(exc))
            return
        write_performance_log(
            "discover_page",
            started,
            f"query={query!r} media_type={media_type!r} size={self.config.page_size} items={len(page.items)} total={page.total}",
        )

        def update() -> None:
            state = BrowseState(
                title,
                page.items,
                search_query=query,
                source="discover",
                next_start=page.next_start,
                total=page.total,
                discover_media_type=media_type,
            )
            self.browsing_stack = [state]
            self.show_browse_state(state)
            self.focus_media_browser()
            self.set_status(render_loaded_status(title, len(page.items), page.total, page.has_more, page.items))

        self.call_from_thread(update)

    def fuzzy_search_source(self) -> BrowseState | None:
        for state in reversed(self.browsing_stack):
            if not state.search and state.items:
                return state
        return None

    def apply_fuzzy_search(self, query: str, focus: bool = False) -> bool:
        if not query:
            self.restore_fuzzy_search_source()
            return True
        local_source = self.fuzzy_search_source()
        if local_source is None:
            return False
        matches = fuzzy_match_media(query, local_source.items)
        self.show_fuzzy_search_results(query, local_source, matches, focus=focus)
        return True

    def show_fuzzy_search_results(
        self,
        query: str,
        local_source: BrowseState,
        matches: list[MediaItem],
        focus: bool = False,
    ) -> None:
        if self.browsing_stack and self.browsing_stack[-1].search:
            self.browsing_stack.pop()
        title = f"Fuzzy search: {query}"
        state = BrowseState(
            title,
            matches,
            local_source.selected_library,
            search=True,
            search_query=query,
            source="fuzzy_search",
            next_start=len(matches),
            total=len(matches),
            context_media=local_source.context_media,
        )
        self.browsing_stack.append(state)
        self.show_browse_state(state)
        if focus:
            self.focus_media_browser()
        self.set_status(f"{title}: {len(matches)} matches from {len(local_source.items)} loaded items")

    def restore_fuzzy_search_source(self) -> None:
        if self.browsing_stack and self.browsing_stack[-1].source == "fuzzy_search":
            self.browsing_stack.pop()
            if self.browsing_stack:
                state = self.browsing_stack[-1]
                self.show_browse_state(state)
                self.set_status(render_loaded_status(state.title, len(state.items), state.total, state.has_more, state.items))

    def action_back_or_clear(self) -> None:
        search = self.query_one("#search", Input)
        if search.display:
            search.value = ""
            search.display = False
            input_mode = self.input_mode
            self.input_mode = ""
            if input_mode in {"mpv_window_size", "page_size", "auto_load_threshold", "grid_prefetch_pages"}:
                self.action_show_settings()
                return
            if input_mode in {"playlist_name", "playlist_rename"}:
                self.picker_visible = False
                self.playlist_picker_visible = False
                self.playlist_picker_item = None
                self.playlist_picker_items = []
                if self.browsing_stack:
                    state = self.browsing_stack[-1]
                    self.show_browse_state(state, selected_key=self.picker_media_key)
                self.picker_media_key = None
                self.focus_media_browser()
                return
            if self.browsing_stack:
                state = self.browsing_stack[-1]
                self.show_browse_state(state)
            self.focus_media_browser()
            return

        if self.help_visible or self.settings_visible or self.picker_visible:
            self.help_visible = False
            self.settings_visible = False
            self.picker_visible = False
            self.playlist_picker_visible = False
            self.playlist_picker_item = None
            selected_key = self.picker_media_key
            self.picker_media_key = None
            if self.browsing_stack:
                state = self.browsing_stack[-1]
                self.show_browse_state(state, selected_key=selected_key)
            self.focus_media_browser()
            return

        if len(self.browsing_stack) > 1:
            self.browsing_stack.pop()
            state = self.browsing_stack[-1]
            self.show_browse_state(state)
            self.focus_media_browser()
            self.set_status(state.title)
            return

        if self.browsing_stack:
            state = self.browsing_stack[-1]
            if state.source.startswith("library:") and state.selected_library is not None:
                self.open_library_menu(state.selected_library)

    def action_play_selected(self) -> None:
        self.play_selected_media(resume=False)

    def action_resume_selected(self) -> None:
        self.play_selected_media(resume=True)

    def action_toggle_watched(self) -> None:
        media = self.selected_media()
        if media is None:
            self.set_status("No media selected")
            return
        if not media.playable:
            self.set_status("Selected item cannot be marked watched")
            return
        target_watched, method = watched_state_action(media.raw)
        if method is None:
            self.set_status("Selected item does not support watched state changes")
            return
        target = "watched" if target_watched else "unwatched"
        self.set_status(f"Marking {media.title} {target}...")
        self.toggle_watched_state(media)

    def action_remove_continue_watching(self) -> None:
        media = self.selected_media()
        if media is None:
            self.set_status("No media selected")
            return
        if not self.browsing_stack:
            self.set_status("Open Continue Watching or a playlist before removing an item")
            return
        state = self.browsing_stack[-1]
        if state.source == "playlist":
            if state.context_media is None:
                self.set_status("Playlist context is unavailable")
                return
            items = self.selected_bulk_items() or [media]
            self.set_status(f"Removing {playlist_items_label(items)} from {state.context_media.title}...")
            self.remove_playlist_items(state.context_media, items)
            return
        if state.source != "continue_watching":
            self.set_status("Open Continue Watching or a playlist before removing an item")
            return
        self.set_status(f"Removing {media.title} from Continue Watching...")
        self.remove_continue_watching_item(media)

    def remove_playlist_item(self, playlist: MediaItem, media: MediaItem) -> None:
        self.remove_playlist_items(playlist, [media])

    @work(thread=True, exclusive=True)
    def remove_playlist_items(self, playlist: MediaItem, items: list[MediaItem]) -> None:
        if self.service is None:
            return
        try:
            self.service.remove_items_from_playlist(playlist, items)
        except Exception as exc:
            self.call_from_thread(self.show_error, f"failed to remove from playlist: {exc}")
            return
        self.call_from_thread(self.apply_playlist_removal, playlist, items)

    def apply_playlist_removal(self, playlist: MediaItem, items: list[MediaItem]) -> None:
        removed_keys = {item.key for item in items}
        item_label = playlist_items_label(items)
        if not self.browsing_stack or self.browsing_stack[-1].source != "playlist":
            self.set_status(f"Removed {item_label} from {playlist.title}")
            return
        state = self.browsing_stack[-1]
        first_removed_key = items[0].key if items else ""
        index = selected_media_index(state.items, first_removed_key)
        state.items = [item for item in state.items if item.key not in removed_keys]
        self.bulk_selected_keys.difference_update(removed_keys)
        state.total = max(0, state.total - len(removed_keys)) if state.total else len(state.items)
        if not state.items:
            self.show_browse_state(state)
            self.show_detail_text("No items")
            self.set_status(f"Removed {item_label} from {playlist.title}")
            return
        next_index = min(index, len(state.items) - 1)
        self.show_browse_state(state, selected_key=state.items[next_index].key)
        self.focus_media_browser()
        status = f"Removed {item_label} from {playlist.title}"
        self.set_status(status)
        self.set_timer(
            0.2,
            lambda: self.set_status(status),
            name="playlist-removal-status",
        )

    @work(thread=True, exclusive=True)
    def remove_continue_watching_item(self, media: MediaItem) -> None:
        method = getattr(media.raw, "removeFromContinueWatching", None)
        if not callable(method):
            self.call_from_thread(self.set_status, "Selected item cannot be removed from Continue Watching")
            return
        try:
            method()
        except Exception as exc:
            self.call_from_thread(self.show_error, f"failed to remove from Continue Watching: {exc}")
            return
        self.call_from_thread(self.apply_continue_watching_removal, media)

    def apply_continue_watching_removal(self, media: MediaItem) -> None:
        if not self.browsing_stack or self.browsing_stack[-1].source != "continue_watching":
            self.set_status(f"Removed {media.title} from Continue Watching")
            return
        state = self.browsing_stack[-1]
        index = selected_media_index(state.items, media.key)
        state.items = [item for item in state.items if item.key != media.key]
        state.total = max(0, state.total - 1) if state.total else len(state.items)
        if not state.items:
            self.show_browse_state(state)
            self.show_detail_text("No items")
            self.set_status(f"Removed {media.title} from Continue Watching")
            return
        next_index = min(index, len(state.items) - 1)
        self.show_browse_state(state, selected_key=state.items[next_index].key)
        self.focus_media_browser()
        self.set_status(f"Removed {media.title} from Continue Watching")
        self.set_timer(
            0.05,
            lambda: self.set_status(f"Removed {media.title} from Continue Watching"),
            name="continue-watching-removal-status",
        )

    @work(thread=True, exclusive=True)
    def toggle_watched_state(self, media: MediaItem) -> None:
        target_watched, method = watched_state_action(media.raw)
        if not callable(method):
            self.call_from_thread(self.set_status, "Selected item does not support watched state changes")
            return
        try:
            result = method()
            updated_raw = result or media.raw
        except Exception as exc:
            self.call_from_thread(self.show_error, f"failed to update watched state: {exc}")
            return
        reload_method = getattr(updated_raw, "reload", None)
        if callable(reload_method):
            try:
                updated_raw = reload_method()
            except Exception:
                pass
        updated_media = replace(media, raw=updated_raw)
        self.call_from_thread(self.apply_watched_state, updated_media, target_watched)

    def apply_watched_state(self, media: MediaItem, watched: bool) -> None:
        self.detail_cache.pop(media.key, None)
        if watched and self.current_browse_state_source() == "continue_watching":
            self.refresh_continue_watching_after_watched(media)
            return
        selected = self.selected_media()
        selected_key = selected.key if selected is not None else media.key
        if self.browsing_stack:
            state = self.browsing_stack[-1]
            for index, item in enumerate(state.items):
                if item.key == media.key:
                    state.items[index] = media
                    break
            if selected_key == media.key:
                self.show_browse_state(state, selected_key=media.key)
                self.focus_media_browser()
            else:
                self.show_browse_state(state, selected_key=selected_key)
        else:
            self.refresh_visible_media_item(media)
            self.show_media_details(media)
        label = "watched" if watched else "unwatched"
        self.set_status(f"Marked {media.title} {label}")

    @work(thread=True, exclusive=True)
    def refresh_continue_watching_after_watched(self, media: MediaItem) -> None:
        if self.service is None:
            self.call_from_thread(self.set_status, f"Marked {media.title} watched")
            return
        try:
            page = self.service.continue_watching_page(0, self.config.page_size)
        except Exception as exc:
            self.call_from_thread(self.show_error, f"failed to refresh Continue Watching: {exc}")
            return
        self.call_from_thread(self.apply_continue_watching_refresh, media.title, page)

    def apply_continue_watching_refresh(self, title: str, page: MediaPage) -> None:
        state = BrowseState(
            "Continue Watching",
            page.items,
            source="continue_watching",
            next_start=page.next_start,
            total=page.total,
        )
        self.browsing_stack = [state]
        self.show_browse_state(state)
        self.focus_media_browser()
        status = f"Marked {title} watched"
        self.set_status(status)
        self.set_timer(0.05, lambda: self.set_status(status), name="continue-watching-watched-status")

    def refresh_visible_media_item(self, media: MediaItem) -> None:
        if self.media_grid_visible():
            grid = self.query_one("#media-grid", MediaGrid)
            for index, item in enumerate(grid.items):
                if item.key == media.key:
                    grid.items[index] = media
                    grid.refresh_grid()
                    return
        row = self.query_one("#media", ListView).highlighted_child
        if isinstance(row, MediaRow) and row.media.key == media.key:
            updated_row = MediaRow(media)
            row.media = updated_row.media
            row.label_text = updated_row.label_text
            label = row.query_one(Label)
            label.update(updated_row.label_text)

    def play_selected_media(self, resume: bool) -> None:
        media = self.selected_media()
        if media is None:
            self.set_status("No media selected")
            return
        self.play_media(media, resume)

    def play_media(self, media: MediaItem, resume: bool) -> None:
        if not media.playable:
            self.open_media(media)
            return
        if not resume and self.config.confirm_start_over and resume_offset_ms(media.raw):
            self.show_resume_picker(media)
            return
        if resume and not resume_offset_ms(media.raw):
            self.set_status("No resume position for selected media; press p to play from the beginning")
            return
        subtitle_choice = preferred_subtitle_choice(
            media.raw,
            self.config.preferred_subtitle_language,
            self.config.subtitle_mode,
        )
        audio_choice = preferred_audio_choice(media.raw, self.config.preferred_audio_language)
        try:
            stop_mpv(self.player)
            if self.config.playback_display == "terminal":
                self.player = self.play_terminal_media(media, subtitle_choice, audio_choice, resume)
            else:
                self.player = play_with_mpv(
                    media.raw,
                    subtitle_choice=subtitle_choice,
                    audio_choice=audio_choice,
                    window_size=effective_mpv_window_size(self.config),
                    playback_mode=self.config.playback_mode,
                    playback_display=self.config.playback_display,
                    terminal_video_profile=self.config.terminal_video_profile,
                    transcode_quality=self.config.transcode_quality,
                    resume=resume,
                )
        except PlayerError as exc:
            self.clear_playback_footer()
            error = str(exc)
            if is_unavailable_vod_stream_error(error):
                self.show_playback_unavailable(media.title, error)
            else:
                self.show_playback_error(error)
            return
        if self.player is not None and self.config.playback_display == "terminal":
            status = playback_exit_status(self.player, debug_log_path()) or f"Finished terminal playback for {media.title}"
            self.player = None
            self.clear_playback_footer()
            self.show_media_details(media)
            self.set_status(status)
            return
        self.detail_refresh_token += 1
        self.cancel_media_detail_refresh()
        self.show_detail_text(
            render_playback_details(media.title, self.player, self.config, audio_choice, subtitle_choice)
        )
        status = render_playback_status(media.title, self.player, self.config, audio_choice, subtitle_choice)
        self.set_status(status)
        self.set_playback_footer(status)

    def show_resume_picker(self, media: MediaItem) -> None:
        self.picker_visible = True
        self.settings_visible = False
        self.picker_media_key = media.key
        self.set_media_title(f"Playback: {media.title}")
        self.show_media_list()
        self.replace_media_rows([ResumeChoiceRow(media, True), ResumeChoiceRow(media, False)], 0)
        self.query_one("#media", ListView).focus()
        self.show_detail_text(f"{media.title}\n\nChoose where playback should start.")
        self.set_status("Choose resume or start over")

    def choose_resume_playback(self, row: ResumeChoiceRow) -> None:
        self.picker_visible = False
        if self.browsing_stack:
            self.show_browse_state(self.browsing_stack[-1], selected_key=self.picker_media_key)
        self.picker_media_key = None
        self.focus_media_browser()
        self.play_media(row.media, row.resume)

    def play_terminal_media(
        self,
        media: MediaItem,
        subtitle_choice: StreamChoice | None,
        audio_choice: StreamChoice | None,
        resume: bool,
    ) -> PlayerHandle:
        try:
            with self.suspend():
                player = play_with_mpv(
                    media.raw,
                    subtitle_choice=subtitle_choice,
                    audio_choice=audio_choice,
                    window_size=effective_mpv_window_size(self.config),
                    playback_mode=self.config.playback_mode,
                    playback_display=self.config.playback_display,
                    terminal_video_profile=self.config.terminal_video_profile,
                    transcode_quality=self.config.transcode_quality,
                    resume=resume,
                )
                player.process.wait()
                return player
        except SuspendNotSupported as exc:
            raise PlayerError("terminal playback is not supported in this environment") from exc

    def check_player_status(self) -> None:
        if self.player is None:
            return
        status = playback_exit_status(self.player, debug_log_path())
        if status is None:
            return
        selected = self.selected_media()
        self.player = None
        self.clear_playback_footer()
        if selected is not None:
            self.show_media_details(selected)
        self.set_status(status)

    def action_stop_playback(self) -> None:
        if self.player is None:
            self.set_status("Nothing is playing")
            self.player = None
            self.clear_playback_footer()
            return
        if not self.player.active:
            self.set_status(playback_exit_status(self.player, debug_log_path()) or "Nothing is playing")
            self.player = None
            self.clear_playback_footer()
            return
        title = self.player.title
        stop_mpv(self.player)
        self.player = None
        self.clear_playback_footer()
        self.set_status(f"Stopped {title}")

    def active_player_for_control(self) -> PlayerHandle | None:
        if self.player is None:
            self.set_status("Nothing is playing")
            self.clear_playback_footer()
            return None
        if not self.player.active:
            self.set_status(playback_exit_status(self.player, debug_log_path()) or "Nothing is playing")
            self.player = None
            self.clear_playback_footer()
            return None
        return self.player

    def action_toggle_playback_pause(self) -> None:
        player = self.active_player_for_control()
        if player is None:
            return
        if not toggle_mpv_pause(player):
            self.set_status("Playback control unavailable; mpv may still be starting")
            return
        self.set_status(f"Toggled pause for {player.title}")

    def action_seek_playback_backward(self) -> None:
        self.seek_active_playback(-10)

    def action_seek_playback_forward(self) -> None:
        self.seek_active_playback(30)

    def seek_active_playback(self, seconds: int) -> None:
        player = self.active_player_for_control()
        if player is None:
            return
        if not seek_mpv(player, seconds):
            self.set_status("Playback control unavailable; mpv may still be starting")
            return
        label = f"+{seconds}s" if seconds > 0 else f"{seconds}s"
        self.set_status(f"Seeked {player.title} {label}")

    def action_reload(self) -> None:
        self.load_server()

    def on_unmount(self) -> None:
        if self.login_session is not None:
            self.login_session.stop()

    def on_status_changed(self, event: StatusChanged) -> None:
        self.set_status(event.text)

    def set_status(self, text: str) -> None:
        try:
            self.query_one("#status", Static).update(text)
        except NoMatches:
            return

    def set_playback_footer(self, text: str) -> None:
        try:
            footer = self.query_one("#playback-footer", Static)
        except NoMatches:
            return
        footer.display = True
        footer.update(text)

    def clear_playback_footer(self) -> None:
        try:
            footer = self.query_one("#playback-footer", Static)
        except NoMatches:
            return
        footer.update("")
        footer.display = False

    def show_error(self, text: str) -> None:
        config_hint = f"Config: {config_path()}"
        recovery_hint = "Use Settings > Plex > Relogin with Plex to try another server URL."
        self.set_status(f"Error: {text}")
        self.set_media_title("Error")
        view = self.show_media_list()
        view.clear()
        view.append(EmptyStateRow("Plex error", "Open Settings or relogin, then retry."))
        self.show_detail_text(render_error_state_details("Plex Error", text, config_hint, recovery_hint))

    def show_playback_error(self, text: str) -> None:
        self.detail_refresh_token += 1
        self.cancel_media_detail_refresh()
        path = debug_log_path()
        self.set_status(f"Playback error: {text}. Debug log: {path}")
        self.set_media_title("Playback Error")
        view = self.show_media_list()
        view.clear()
        view.append(EmptyStateRow("Playback error", f"Debug log: {path}"))
        self.show_detail_text(render_playback_error_details(text, path))

    def show_playback_unavailable(self, title: str, text: str) -> None:
        self.detail_refresh_token += 1
        self.cancel_media_detail_refresh()
        self.set_media_title("Playback Unavailable")
        view = self.show_media_list()
        view.clear()
        view.append(EmptyStateRow("Not available to play", "Choose another episode."))
        self.show_detail_text(render_empty_state_details(title, text, "Choose another episode."))
        self.set_status(f"Playback unavailable: {text}")


def format_offset(milliseconds: int) -> str:
    seconds = max(0, milliseconds // 1000)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def render_details(
    details: object,
    config: AppConfig | None = None,
    raw: object | None = None,
    context_actions: tuple[str, ...] = (),
) -> str:
    lines = render_detail_header(details, config, context_actions)

    metadata_rows = list(getattr(details, "metadata"))
    episode_context = episode_context_rows(details, metadata_rows)
    if episode_context:
        metadata_rows = [
            (label, value)
            for label, value in metadata_rows
            if label not in EPISODE_CONTEXT_LABEL_SET
        ]

    metadata = [*detail_key_value_rows(metadata_rows)]
    append_detail_section(lines, "Metadata", metadata or ["No metadata reported"])

    if config is not None:
        append_detail_section(
            lines,
            "Preferences",
            detail_key_value_rows([
                ("Audio", preference_value(config.preferred_audio_language)),
                ("Subtitles", f"{subtitle_mode_value(config)} / {subtitle_language_value(config)}"),
                ("Playback Mode", playback_mode_value(config)),
                ("Playback Display", playback_display_value(config)),
                ("Transcode Quality", transcode_quality_value(config)),
            ]),
        )
        if raw is not None and bool(getattr(details, "playable")):
            effective = effective_stream_preference_rows(raw, config)
            if effective:
                append_detail_section(lines, "Effective Playback", detail_key_value_rows(effective))

    audio = getattr(details, "audio", [])
    if audio:
        append_detail_section(lines, stream_section_heading("Audio Tracks", audio), detail_list_rows(audio))
    else:
        append_detail_section(lines, "Audio Tracks", ["No audio tracks reported"])

    subtitles = getattr(details, "subtitles")
    if subtitles:
        append_detail_section(lines, stream_section_heading("Subtitle Tracks", subtitles), detail_list_rows(subtitles))
    else:
        append_detail_section(lines, "Subtitle Tracks", ["No subtitle tracks reported"])

    summary = getattr(details, "summary")
    if summary:
        append_detail_section(lines, "Summary", wrapped_detail_text(summary))

    return "\n".join(lines)


def render_detail_header(
    details: object,
    config: AppConfig | None = None,
    context_actions: tuple[str, ...] = (),
) -> list[str]:
    title = getattr(details, "title")
    metadata = list(getattr(details, "metadata", []))
    title_lines = textwrap.wrap(title, width=DETAIL_SUMMARY_WIDTH) or [title]
    episode_context = episode_context_summary(details, metadata)
    context_lines = textwrap.wrap(episode_context, width=DETAIL_SUMMARY_WIDTH) if episode_context else []
    facts = [str(fact) for fact in getattr(details, "facts", []) if fact]
    artwork = artwork_status(details, config)
    progress = detail_metadata_value(metadata, "Progress")
    title_width = max(len(line) for line in [*title_lines, *context_lines])
    lines = [*title_lines, *context_lines, "-" * min(max(title_width, 8), DETAIL_SUMMARY_WIDTH)]
    if facts:
        lines.extend(textwrap.wrap(" / ".join(facts), width=DETAIL_SUMMARY_WIDTH) or [""])
    lines.extend([
        "",
        "Playback",
        *playback_readiness_rows(bool(getattr(details, "playable")), progress, context_actions),
        f"Artwork: {artwork}",
    ])
    return lines


def playback_readiness_rows(playable: bool, progress: str = "", context_actions: tuple[str, ...] = ()) -> list[str]:
    if playable:
        status = "Status: Ready to play"
        if any(action.startswith("Availability: Listed by Plex") for action in context_actions):
            status = "Status: Listed by Plex; playable stream checked on play"
        rows = [
            status,
        ]
        if progress:
            rows.append(f"Progress: {progress}")
        rows.extend([
            "p: play from beginning",
            "r: resume saved progress",
            "Playlist: Press P",
        ])
        rows.extend(context_actions)
        return rows
    if "Availability: No provider links found" in context_actions:
        rows = [
            "Status: No availability provider",
            "Action: Choose another item",
        ]
        rows.extend(context_actions)
        return rows
    if any(action.startswith("Availability:") for action in context_actions):
        rows = [
            "Status: Opens availability provider",
            "Action: Press Enter to choose/open",
        ]
        rows.extend(context_actions)
        return rows
    rows = [
        "Status: Opens more items",
        "Action: Press Enter to open",
    ]
    rows.extend(context_actions)
    return rows


def detail_metadata_value(metadata: list[tuple[str, str]], label: str) -> str:
    for row_label, value in metadata:
        if row_label == label:
            return value
    return ""


EPISODE_CONTEXT_LABELS = ("Show", "Season", "Episode")
EPISODE_CONTEXT_LABEL_SET = set(EPISODE_CONTEXT_LABELS)


def episode_context_rows(details: object, metadata: list[tuple[str, str]]) -> list[tuple[str, str]]:
    if getattr(details, "kind", "") != "episode":
        return []
    values = {label: value for label, value in metadata}
    return [
        (label, values[label])
        for label in EPISODE_CONTEXT_LABELS
        if values.get(label)
    ]


def episode_context_summary(details: object, metadata: list[tuple[str, str]]) -> str:
    rows = episode_context_rows(details, metadata)
    return " - ".join(value for _label, value in rows)


def append_detail_section(lines: list[str], heading: str, body: list[str]) -> None:
    if lines and lines[-1] != "":
        lines.append("")
    lines.append(heading)
    lines.extend(body)


def detail_key_value_rows(values: list[tuple[str, str]]) -> list[str]:
    rows: list[str] = []
    label_width = detail_label_width(values)
    for label, value in values:
        rows.extend(detail_key_value_row(label, value, label_width))
    return rows


def detail_label_width(values: list[tuple[str, str]]) -> int:
    if not values:
        return 0
    return min(DETAIL_LABEL_WIDTH, max(len(label) for label, _value in values))


def detail_key_value_row(label: str, value: str, label_width: int = DETAIL_LABEL_WIDTH) -> list[str]:
    label_text = f"{label}:"
    prefix = f"{label_text:<{label_width + 2}}"
    value_width = max(8, DETAIL_SUMMARY_WIDTH - len(prefix))
    wrapped = wrapped_detail_text(value, width=value_width) or [""]
    rows = [f"{prefix}{wrapped[0]}"]
    rows.extend(f"{' ' * len(prefix)}{line}" for line in wrapped[1:])
    return rows


def stream_section_heading(label: str, values: list[str]) -> str:
    return f"{label} ({len(values)})"


def detail_list_rows(values: list[str], limit: int = DETAIL_STREAM_LIMIT) -> list[str]:
    rows: list[str] = []
    visible = values[:limit]
    for value in visible:
        wrapped = wrapped_detail_text(value, width=DETAIL_SUMMARY_WIDTH - 2)
        if not wrapped:
            continue
        rows.append(f"- {wrapped[0]}")
        rows.extend(f"  {line}" for line in wrapped[1:])
    remaining = len(values) - len(visible)
    if remaining > 0:
        rows.append(f"... {remaining} more")
    return rows


def wrapped_detail_text(value: str, width: int = DETAIL_SUMMARY_WIDTH) -> list[str]:
    wrapped: list[str] = []
    paragraphs = [paragraph.strip() for paragraph in value.splitlines()]
    for paragraph in paragraphs:
        if not paragraph:
            if wrapped and wrapped[-1] != "":
                wrapped.append("")
            continue
        wrapped.extend(textwrap.wrap(paragraph, width=width) or [""])
    return wrapped


def render_detail_content(
    details: object,
    config: AppConfig | None = None,
    artwork: object | None = None,
    raw: object | None = None,
    context_actions: tuple[str, ...] = (),
) -> object:
    text = render_details(details, config, raw, context_actions)
    if artwork is None:
        return text
    return Group(artwork, Text(""), text)


def render_playlist_picker_details(media: MediaItem | list[MediaItem], playlist_count: int) -> str:
    items = media if isinstance(media, list) else [media]
    count = f"{playlist_count} existing playlist" if playlist_count == 1 else f"{playlist_count} existing playlists"
    return "\n".join([
        "Add to Playlist",
        playlist_items_label(items),
        "",
        "Choose New playlist... to create a playlist with the selected media.",
        f"Or choose one of {count} to add the selected media.",
    ])


def render_playlist_create_details(media: MediaItem | list[MediaItem] | None) -> str:
    items = [] if media is None else media if isinstance(media, list) else [media]
    title = playlist_items_label(items) if items else "selected media"
    return "\n".join([
        "New Playlist",
        "",
        f"Create a playlist containing {title}.",
        "Press Enter, then type the playlist name.",
    ])


def render_playlist_target_details(playlist: MediaItem, media: MediaItem | list[MediaItem] | None) -> str:
    items = [] if media is None else media if isinstance(media, list) else [media]
    title = playlist_items_label(items) if items else "selected media"
    return "\n".join([
        playlist.title,
        "",
        f"Add {title} to this playlist.",
    ])


def playlist_items_label(items: list[MediaItem]) -> str:
    if len(items) == 1:
        return items[0].title
    label = "item" if len(items) == 1 else "items"
    return f"{len(items)} selected {label}"


def media_rows(
    items: list[MediaItem],
    config: AppConfig,
    selected_index: int,
    bulk_selected_keys: set[str] | None = None,
) -> tuple[list[ListItem], int]:
    selected_keys = bulk_selected_keys or set()
    return [media_row(item, config, item.key in selected_keys) for item in items], selected_index


def media_row(item: MediaItem, config: AppConfig, bulk_selected: bool = False) -> MediaRow:
    return MediaRow(item, bulk_selected=bulk_selected)


def render_media_grid(
    items: list[MediaItem],
    selected_key: str,
    config: AppConfig,
    columns: int,
    artwork_overrides: dict[str, object] | None = None,
    bulk_selected_keys: set[str] | None = None,
) -> object:
    rows = []
    collection_cards = grid_items_are_collection_cards(items)
    card_width = grid_card_width(config, collection_card=collection_cards)
    for start in range(0, len(items), columns):
        chunk = items[start:start + columns]
        cards = [
            render_media_grid_card(
                item,
                item.key == selected_key,
                config,
                artwork_overrides,
                collection_card=collection_cards,
                bulk_selected=item.key in (bulk_selected_keys or set()),
            )
            for item in chunk
        ]
        row = Table.grid(padding=(0, 1))
        for _ in cards:
            row.add_column(width=card_width, no_wrap=True)
        row.add_row(*cards)
        rows.append(row if collection_cards else Align.center(row))
        if collection_cards and start + columns < len(items):
            rows.append(Text(""))
    return Group(*rows)


def render_media_grid_card(
    media: MediaItem,
    selected: bool,
    config: AppConfig,
    artwork_overrides: dict[str, object] | None = None,
    collection_card: bool | None = None,
    bulk_selected: bool = False,
) -> object:
    collection_card = is_collection_card(media) if collection_card is None else collection_card
    title_style = f"bold {UI_SELECTED_ACCENT}" if selected else f"bold {UI_GRID_TITLE}"
    card_width = grid_card_width(config, collection_card=collection_card)
    title_lines = grid_card_title_lines(media.title, config, collection_card=collection_card)
    subtitle = grid_card_text(grid_card_subtitle(media), config, collection_card=collection_card)
    artwork = artwork_overrides.get(media.key) if artwork_overrides is not None else None
    artwork = copy_renderable(artwork)
    if artwork is None:
        artwork = (
            grid_missing_artwork_placeholder(media, config)
            if media.playable
            else render_collection_art(media, config, collection_card=collection_card)
        )
    else:
        artwork = center_renderable_lines(artwork, card_width)
    footer = grid_card_footer(media, selected, bulk_selected)
    return Group(
        artwork,
        *(grid_card_line(title, card_width, title_style) for title in title_lines),
        grid_card_line(subtitle, card_width, UI_GRID_MUTED),
        grid_card_line(footer, card_width, f"bold {UI_SELECTED_ACCENT}" if selected else UI_GRID_DIM),
    )


def grid_items_are_collection_cards(items: list[MediaItem]) -> bool:
    return bool(items) and all(is_collection_card(item) for item in items)


def is_collection_card(media: MediaItem) -> bool:
    if media.playable:
        return False
    if media.kind in {"hub", "collection", "playlist", "category"}:
        return True
    if media.artwork_path:
        return False
    return media.kind in {
        "show",
        "season",
        "artist",
        "album",
        "photoalbum",
    }


def grid_missing_artwork_placeholder(media: MediaItem, config: AppConfig) -> Group:
    return grid_artwork_placeholder(grid_artwork_placeholder_label(media), config)


def render_collection_art(media: MediaItem, config: AppConfig, collection_card: bool = True) -> Group:
    spec = grid_density_spec(config)
    width = grid_card_width(config, collection_card=collection_card)
    content_width = grid_card_content_width(config, collection_card=collection_card)
    height = int(spec["art_height"])
    glyph = collection_glyph(media)
    glyph_lines = glyph.lines[: max(1, height - 2)]
    top_pad = max(0, (height - len(glyph_lines)) // 2)
    bottom_pad = max(0, height - top_pad - len(glyph_lines))
    lines = []
    row_index = 0
    for _ in range(top_pad):
        lines.append(collection_art_line("", width, content_width, glyph.background, row_index=row_index, blueprint_style=glyph.blueprint))
        row_index += 1
    for index, line in enumerate(glyph_lines):
        style = glyph.accent if index == glyph.primary_line else glyph.foreground
        lines.append(
            collection_art_line(
                line,
                width,
                content_width,
                glyph.background,
                style,
                row_index=row_index,
                blueprint_style=glyph.blueprint,
            )
        )
        row_index += 1
    for _ in range(bottom_pad):
        lines.append(collection_art_line("", width, content_width, glyph.background, row_index=row_index, blueprint_style=glyph.blueprint))
        row_index += 1
    return Group(*lines[:height])


@dataclass(frozen=True)
class CollectionGlyph:
    lines: tuple[str, ...]
    primary_line: int = 2
    background: str = "on #202332"
    foreground: str = "#8f96b8 on #202332"
    accent: str = "#e5a00d on #202332"
    blueprint: str = "#3b4055 on #202332"


def collection_glyph(media: MediaItem) -> CollectionGlyph:
    title = media.title.lower()
    if "continue" in title and "watch" in title:
        return CollectionGlyph(("  ◜──◝  ", "  │▶ │  ", "  │ ●│  ", "  ◟──◞  "), background="on #202735", foreground="#9098bd on #202735", blueprint="#394357 on #202735")
    if "recently added" in title:
        return CollectionGlyph(("   │   ", " ──┼── ", "   │   ", "  ╴╵╶  "), background="on #202e30", foreground="#93b7b2 on #202e30", blueprint="#39494a on #202e30")
    if "recently released" in title or "new" in title:
        return CollectionGlyph((" ╲  │  ╱ ", "   ✦   ", " ──┼── ", "   ✦   ", " ╱  │  ╲ "), background="on #242638", foreground="#a7a2c6 on #242638", blueprint="#3e4057 on #242638")
    if "recommended" in title:
        return CollectionGlyph((" ●    ╱ ", "  ╲  ●  ", "   ╲╱   ", "  ●─╯   "), background="on #222535", foreground="#9ba3c6 on #222535", blueprint="#3c4159 on #222535")
    if "trending" in title or title.startswith("top "):
        return CollectionGlyph(("     ╱ ", "  ● ╱  ", "   ╱●  ", "  ╱    ", " ●     "), background="on #2a2630", foreground="#b9a0bd on #2a2630", blueprint="#463c49 on #2a2630")
    if "unwatched" in title:
        return CollectionGlyph((" ○   ○ ", "   ○   ", " ○   ○ ", "   ○   "), background="on #242a33", foreground="#9ca8bd on #242a33", blueprint="#3e4654 on #242a33")
    if "actor" in title or "by " in title:
        return CollectionGlyph(("   ○   ", "  ╱│╲  ", "   │   ", "  ╱ ╲  "), background="on #272b35", foreground="#a7adc7 on #272b35", blueprint="#414757 on #272b35")
    if "genre" in title or media.kind == "category":
        return category_collection_glyph(media.title)
    if media.kind == "playlist":
        return CollectionGlyph((" ╭────╮ ", " ├────┤ ", " ├────┤ ", " ╰────╯ "), background="on #232c2a", foreground="#99b8ad on #232c2a", blueprint="#3d4944 on #232c2a")
    if media.kind == "collection":
        return CollectionGlyph((" ◇  ◇ ", "  ◇◇  ", " ◇  ◇ ", "  ◇◇  "), background="on #202e30", foreground="#9eb7ba on #202e30", blueprint="#39494a on #202e30")
    if media.kind in {"show", "season"}:
        return CollectionGlyph((" ┌────┐ ", " ├────┤ ", " ├────┤ ", " └────┘ "), background="on #2b2732", foreground="#b2a2c6 on #2b2732", blueprint="#463f50 on #2b2732")
    return CollectionGlyph(("  ╱╲   ", " ╱  ╲  ", " ╲  ╱  ", "  ╲╱   "), background="on #262936", foreground="#9aa2bf on #262936", blueprint="#404557 on #262936")


def category_collection_glyph(title: str) -> CollectionGlyph:
    normalized = title.lower()
    motifs = {
        "action": ("   ╱╱  ", "  ╱╱   ", " ╱╱    ", "   ╱╱  "),
        "adventure": (" ╱╲    ", "╱  ╲   ", "╲  ╱   ", " ╲╱    "),
        "animation": (" ▢ ▢  ", "  ▢ ▢ ", " ▢ ▢  ", "  ▢ ▢ "),
        "comedy": (" ○  ○ ", "   ○  ", " ○  ○ ", "   ○  "),
        "documentary": (" ┬─┬  ", " ├─┤  ", " ┼─┼  ", " ┴─┴  "),
        "drama": ("  ││  ", "  ││  ", " ─┼┼─ ", "  ││  "),
        "horror": ("  ◇   ", " ◇ ◇  ", "  ◇   ", " ◇ ◇  "),
        "sci": (" ●─╮  ", "   ●  ", " ╰─●  ", "  ●   "),
        "science": (" ●─╮  ", "   ●  ", " ╰─●  ", "  ●   "),
        "romance": (" ◜ ◝  ", "  ◇   ", " ◟ ◞  ", "  ◇   "),
        "thriller": (" ╲╲   ", "  ╲╲  ", "   ╲╲ ", "  ╲╲  "),
    }
    lines = (" ▬▬   ", "  ▬▬  ", " ▬▬   ", "  ▬▬  ")
    for key, motif in motifs.items():
        if key in normalized:
            lines = motif
            break
    return CollectionGlyph(lines, background="on #202e30", foreground="#94b0ad on #202e30", blueprint="#39494a on #202e30")


def collection_art_line(
    value: str,
    width: int,
    content_width: int,
    background_style: str,
    glyph_style: str | None = None,
    row_index: int = 0,
    blueprint_style: str = "#3b4055 on #202332",
) -> Text:
    left = (width - content_width) // 2
    right = width - content_width - left
    text = Text(" " * left, style="dim")
    inner = collection_blueprint_layer(content_width, row_index, background_style, blueprint_style)
    if value and glyph_style is not None:
        glyph_text = truncate_text(value, content_width)
        glyph_left = max(0, (content_width - len(glyph_text)) // 2)
        glyph_right = max(0, content_width - glyph_left - len(glyph_text))
        inner = collection_blueprint_layer(glyph_left, row_index, background_style, blueprint_style)
        inner.append(glyph_text, style=glyph_style)
        inner.append_text(collection_blueprint_layer(glyph_right, row_index, background_style, blueprint_style))
    text.append_text(inner)
    text.append(" " * right, style="dim")
    return text


def collection_blueprint_layer(width: int, row_index: int, background_style: str, blueprint_style: str) -> Text:
    if width <= 0:
        return Text("")
    chars = [" "] * width
    if row_index == 0 and width >= 2:
        chars[0] = "┌"
        chars[-1] = "┐"
    elif width >= 7 and row_index % 3 == 1:
        chars[width // 3] = "·"
        chars[(width * 2) // 3] = "·"
    elif row_index % 3 == 2:
        chars[width // 2] = "│"
    text = Text()
    for char in chars:
        text.append(char, style=blueprint_style if char != " " else background_style)
    return text


def grid_artwork_placeholder(status: str, config: AppConfig) -> Group:
    spec = grid_density_spec(config)
    width = grid_card_width(config)
    content_width = grid_card_content_width(config)
    height = int(spec["art_height"])
    background, accent = grid_artwork_placeholder_palette(status)
    lines = []
    for index in range(height):
        line_style = accent if index in grid_artwork_placeholder_accent_rows(height) else background
        lines.append(grid_artwork_placeholder_line(width, content_width, line_style))
    return Group(*lines)


def grid_artwork_placeholder_palette(status: str) -> tuple[str, str]:
    palettes = {
        "hub": ("on #222535", "on #3f4563"),
        "collection": ("on #202e30", "on #3d5b5e"),
        "playlist": ("on #232c2a", "on #416059"),
        "show": ("on #2b2732", "on #574866"),
        "season": ("on #2d2826", "on #5f4c3f"),
        "artist": ("on #272b35", "on #485670"),
        "album": ("on #282a30", "on #4c5364"),
        "browse": ("on #262936", "on #444b61"),
    }
    return palettes.get(status, ("on #252834", "on #464d60"))


def grid_artwork_placeholder_accent_rows(height: int) -> set[int]:
    if height <= 3:
        return {height // 2}
    return {height // 3, (height * 2) // 3}


def grid_artwork_placeholder_line(width: int, content_width: int, style: str) -> Text:
    left = (width - content_width) // 2
    right = width - content_width - left
    line = Text(" " * left, style="dim")
    line.append(" " * content_width, style=style)
    line.append(" " * right, style="dim")
    return line


def grid_artwork_placeholder_label(media: MediaItem) -> str:
    if media.artwork_path:
        return "poster"
    if media.playable:
        return "no poster"
    labels = {
        "hub": "hub",
        "collection": "collection",
        "playlist": "playlist",
        "show": "show",
        "season": "season",
        "artist": "artist",
        "album": "album",
        "photoalbum": "album",
    }
    return labels.get(media.kind, "browse")


def grid_card_text(value: str, config: AppConfig, collection_card: bool = False) -> str:
    return truncate_text(value.strip(), grid_card_content_width(config, collection_card=collection_card))


def grid_card_title_lines(value: str, config: AppConfig, collection_card: bool = False) -> list[str]:
    text = value.strip()
    width = grid_card_content_width(config, collection_card=collection_card)
    if not collection_card:
        return [truncate_text(text, width)]
    lines = textwrap.wrap(
        text,
        width=width,
        max_lines=2,
        placeholder="...",
        break_long_words=False,
    ) or [""]
    lines = [truncate_text(line, width) for line in lines[:2]]
    while len(lines) < 2:
        lines.append("")
    return lines


def grid_card_subtitle(media: MediaItem) -> str:
    return media_metadata_label(media, include_kind=not is_collection_card(media))


def media_metadata_label(media: MediaItem, include_kind: bool = True) -> str:
    bits = []
    if include_kind:
        bits.append(kind_label(media.kind))
    subtitle = media.subtitle.strip()
    if subtitle and subtitle.lower() not in {bit.lower() for bit in bits}:
        bits.extend(bit.strip() for bit in subtitle.split("  ") if bit.strip())
    return " · ".join(bits)


def fuzzy_match_media(query: str, items: list[MediaItem]) -> list[MediaItem]:
    scored = [(fuzzy_media_score(query, item), index, item) for index, item in enumerate(items)]
    matches = [(score, index, item) for score, index, item in scored if score >= 0.58]
    matches.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    return [item for _, _, item in matches]


def fuzzy_media_score(query: str, item: MediaItem) -> float:
    normalized_query = normalize_search_text(query)
    if not normalized_query:
        return 0.0
    title = normalize_search_text(item.title)
    subtitle = normalize_search_text(item.subtitle)
    kind = normalize_search_text(kind_label(item.kind))
    searchable = " ".join(value for value in (title, subtitle, kind) if value)
    if not searchable:
        return 0.0
    if normalized_query in searchable:
        return 1.0 if normalized_query in title else 0.92

    query_tokens = normalized_query.split()
    search_tokens = searchable.split()
    if query_tokens and all(any(token in candidate for candidate in search_tokens) for token in query_tokens):
        return 0.88

    acronym = "".join(token[0] for token in search_tokens if token)
    if normalized_query and (acronym.startswith(normalized_query) or normalized_query in acronym):
        return 0.86

    title_ratio = SequenceMatcher(None, normalized_query, title).ratio()
    full_ratio = SequenceMatcher(None, normalized_query, searchable).ratio()
    token_ratio = 0.0
    if query_tokens and search_tokens:
        token_ratio = sum(
            max(SequenceMatcher(None, token, candidate).ratio() for candidate in search_tokens)
            for token in query_tokens
        ) / len(query_tokens)
    return max(title_ratio, full_ratio, token_ratio * 0.9)


def normalize_search_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def grid_card_footer(media: MediaItem, selected: bool, bulk_selected: bool = False) -> str:
    progress = progress_bar(media.raw)
    bulk_prefix = "✓ " if bulk_selected else ""
    if progress:
        selected_prefix = "▶ " if selected else ""
        return f"{bulk_prefix}{selected_prefix}{progress}".strip()
    if selected:
        return f"{bulk_prefix}▶ selected".strip()
    if media.playable:
        return f"{bulk_prefix}playable".strip()
    return f"{bulk_prefix}open".strip()


def grid_card_line(value: str, width: int, style: str) -> Text:
    return Text(value.center(width), style=style)


def center_renderable_lines(renderable: object, width: int) -> object:
    if isinstance(renderable, KittyImage):
        plain_width = renderable.columns + renderable.left_padding + renderable.right_padding
        if plain_width >= width:
            return renderable.copy()
        left = (width - plain_width) // 2
        right = width - plain_width - left
        return renderable.padded(left, right)
    if isinstance(renderable, Group):
        return Group(*(center_renderable_lines(item, width) for item in renderable.renderables))
    if isinstance(renderable, Text):
        plain_width = len(renderable.plain)
        if plain_width >= width:
            return renderable.copy()
        left = (width - plain_width) // 2
        right = width - plain_width - left
        padded = Text(" " * left)
        padded.append_text(renderable.copy())
        padded.append(" " * right)
        return padded
    text = str(renderable)
    if len(text) >= width:
        return Text(text)
    return Text(text.center(width))


def copy_renderable(renderable: object | None) -> object | None:
    if isinstance(renderable, Group):
        return Group(*(copy_renderable(item) for item in renderable.renderables))
    if hasattr(renderable, "copy"):
        return renderable.copy()
    return renderable


def render_card_artwork(data: bytes, config: AppConfig) -> object:
    spec = grid_density_spec(config)
    width = int(spec["art_width"])
    height = int(spec["art_height"])
    protocol_artwork = render_protocol_artwork(data, config.artwork_renderer, width=width, max_height=height)
    if protocol_artwork is not None:
        return protocol_artwork
    artwork = render_artwork(data, width=width, max_height=height)
    return Group(*artwork.split("\n"))


def card_artwork_fetch_size(config: AppConfig) -> tuple[int, int]:
    spec = grid_density_spec(config)
    width = int(spec["art_width"])
    height = int(spec["art_height"])
    return artwork_fetch_pixel_size(config, width, height)


def artwork_fetch_pixel_size(config: AppConfig, width: int, height: int) -> tuple[int, int]:
    if resolve_protocol_renderer(config.artwork_renderer) == "kitty":
        return kitty_pixel_size(width, height)
    return width, height * 2


def grid_artwork_cache_key(item: MediaItem, config: AppConfig) -> tuple[str, str, str]:
    return item.artwork_path, config.grid_density, config.artwork_renderer


def grid_density_spec(config: AppConfig | None) -> dict[str, int]:
    density = getattr(config, "grid_density", "comfortable")
    return GRID_DENSITY_SPECS.get(density, GRID_DENSITY_SPECS["comfortable"])


def grid_card_width(config: AppConfig | None, collection_card: bool = False) -> int:
    width = int(grid_density_spec(config)["width"])
    if collection_card:
        width += GRID_COLLECTION_CARD_EXTRA_WIDTH
    return width


def grid_card_content_width(config: AppConfig | None, collection_card: bool = False) -> int:
    content_width = int(grid_density_spec(config)["content_width"])
    if collection_card:
        content_width += GRID_COLLECTION_CARD_EXTRA_WIDTH
    return content_width


def grid_card_render_width(config: AppConfig | None, collection_card: bool = False) -> int:
    return grid_card_width(config, collection_card=collection_card) + GRID_CARD_GAP


def grid_card_height(config: AppConfig | None, collection_card: bool = False) -> int:
    height = int(grid_density_spec(config)["height"])
    if collection_card:
        height += 1
    return height


def grid_geometry_for_size(
    width: int,
    height: int,
    config: AppConfig | None,
    collection_cards: bool = False,
) -> tuple[int, int]:
    spec = grid_density_spec(config)
    max_columns = int(spec["max_columns"])
    if collection_cards:
        max_columns = max(1, max_columns - 1)
    columns = max(
        1,
        min(max_columns, max(1, width - 4) // grid_card_render_width(config, collection_card=collection_cards)),
    )
    rows = max(
        1,
        min(4, max(1, height - 2) // grid_card_height(config, collection_card=collection_cards)),
    )
    return columns, rows


def truncate_text(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return value[:max(0, width - 3)] + "..."


def selected_media_from_row(row: object) -> MediaItem | None:
    if isinstance(row, MediaRow):
        return row.media
    return None


def artwork_enabled(config: AppConfig | None) -> bool:
    return config is None or config.artwork_mode == "on"


def detail_artwork_enabled(config: AppConfig) -> bool:
    if not artwork_enabled(config):
        return False
    if config.detail_artwork_mode == "off":
        return False
    if config.detail_artwork_mode == "list_only" and config.media_view == "grid":
        return False
    return True


def artwork_status(details: object, config: AppConfig | None) -> str:
    if not artwork_enabled(config):
        return "disabled"
    path = getattr(details, "artwork_path", "")
    if not path:
        return "missing"
    if config is not None and artwork_is_cached(path, config):
        return "cached"
    return "available"


def visible_libraries(libraries: list[LibraryItem], config: AppConfig) -> list[LibraryItem]:
    hidden = set(config.hidden_library_keys)
    return ordered_libraries([library for library in libraries if library.key not in hidden], config)


def ordered_libraries(libraries: list[LibraryItem], config: AppConfig) -> list[LibraryItem]:
    if not config.library_order_keys:
        return libraries
    by_key = {library.key: library for library in libraries}
    ordered = [by_key[key] for key in config.library_order_keys if key in by_key]
    ordered_keys = {library.key for library in ordered}
    ordered.extend(library for library in libraries if library.key not in ordered_keys)
    return ordered


def sidebar_rows(config: AppConfig, libraries: list[LibraryItem]) -> list[ListItem]:
    rows: list[ListItem] = [ContinueWatchingRow()]
    if config.show_playlists:
        rows.append(PlaylistsRow())
    if config.show_discover:
        rows.append(DiscoverRow())
    if config.show_on_plex:
        rows.append(OnPlexRow())
    rows.extend(LibraryRow(library) for library in libraries)
    return rows


def library_by_key(libraries: list[LibraryItem], key: str) -> LibraryItem | None:
    for library in libraries:
        if library.key == key:
            return library
    return None


def library_settings_label(library: LibraryItem, duplicate_titles: set[str]) -> str:
    if library.title not in duplicate_titles:
        return library.title
    return f"{library.title} ({library.kind} #{library.key})"


def duplicate_library_titles(libraries: list[LibraryItem]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for library in libraries:
        if library.title in seen:
            duplicates.add(library.title)
        seen.add(library.title)
    return duplicates


def library_visibility_row(
    library: LibraryItem,
    config: AppConfig,
    duplicate_titles: set[str] | None = None,
) -> SettingsActionRow:
    state = "Hidden" if library.key in config.hidden_library_keys else "Visible"
    label = library_settings_label(library, duplicate_titles or set())
    return SettingsActionRow(
        f"{label}: {state}",
        f"toggle_library_visibility:{library.key}",
    )


def library_order_row(
    library: LibraryItem,
    direction: str,
    duplicate_titles: set[str] | None = None,
) -> SettingsActionRow:
    label = "Move up" if direction == "up" else "Move down"
    library_label = library_settings_label(library, duplicate_titles or set())
    return SettingsActionRow(
        f"{library_label}: {label}",
        f"move_library_{direction}:{library.key}",
    )


def hidden_library_count_value(config: AppConfig) -> str:
    count = len(config.hidden_library_keys)
    if count == 0:
        return "None"
    if count == 1:
        return "1 hidden"
    return f"{count} hidden"


def settings_rows(config: AppConfig, libraries: list[LibraryItem] | None = None) -> list[ListItem]:
    rows: list[ListItem] = [
        SettingsHeaderRow("Account"),
        SettingsValueRow(f"Server: {config.base_url or 'not set'}"),
        SettingsValueRow(f"Server Token: {'saved' if config.token else 'not set'}"),
        SettingsValueRow(f"Account Token: {'saved' if config.account_token else 'not set'}"),
        SettingsValueRow(f"Home Token: {'saved' if (config.home_account_token or config.account_token) else 'not set'}"),
        SettingsActionRow("Reconnect / reload libraries", "reload"),
        SettingsActionRow("Relogin with Plex", "relogin"),
        SettingsActionRow("Switch Plex profile", "switch_profile"),
        SettingsHeaderRow("Streams"),
        SettingsValueRow(f"Audio Preference: {preference_value(config.preferred_audio_language)}"),
        SettingsActionRow(f"Subtitle Mode: {subtitle_mode_value(config)}", "cycle_subtitle_mode"),
        SettingsValueRow(f"Subtitle Language: {subtitle_language_value(config)}"),
        SettingsActionRow("Clear audio preference", "clear_audio"),
        SettingsActionRow("Set subtitles to Auto", "subtitle_auto"),
        SettingsActionRow("Set subtitles to None", "subtitle_none"),
        SettingsActionRow("Clear subtitle preference", "clear_subtitle"),
        SettingsActionRow("Clear audio/subtitle preferences", "clear_tracks"),
        SettingsHeaderRow("Playback"),
        SettingsActionRow(f"Playback Mode: {playback_mode_value(config)}", "cycle_playback_mode"),
        SettingsActionRow(f"Playback Display: {playback_display_value(config)}", "cycle_playback_display"),
        SettingsActionRow(f"Start Over Prompt: {show_setting_value(config.confirm_start_over)}", "toggle_confirm_start_over"),
        SettingsActionRow(f"Terminal Video: {terminal_video_profile_value(config)}", "cycle_terminal_video_profile"),
        SettingsActionRow(f"Transcode Quality: {transcode_quality_value(config)}", "cycle_transcode_quality"),
        SettingsActionRow(f"mpv Window Size: {mpv_window_size_value(config)}", "cycle_mpv_window_size"),
        SettingsActionRow("Set custom mpv window size", "set_mpv_window_size"),
        SettingsHeaderRow("Artwork"),
        SettingsActionRow(f"Artwork: {artwork_mode_value(config)}", "toggle_artwork"),
        SettingsActionRow(f"Details Artwork: {detail_artwork_mode_value(config)}", "cycle_detail_artwork"),
        SettingsActionRow(f"Artwork Renderer: {artwork_renderer_value(config)}", "cycle_artwork_renderer"),
        SettingsHeaderRow("Browsing"),
        SettingsActionRow(f"Playlists Sidebar: {show_setting_value(config.show_playlists)}", "toggle_show_playlists"),
        SettingsActionRow(f"Discover Sidebar: {show_setting_value(config.show_discover)}", "toggle_show_discover"),
        SettingsActionRow(f"On Plex Sidebar: {show_setting_value(config.show_on_plex)}", "toggle_show_on_plex"),
        SettingsActionRow(f"Discover Type: {discover_media_type_value(config)}", "cycle_discover_media_type"),
        SettingsActionRow(f"Library Enter: {library_enter_action_value(config)}", "cycle_library_enter_action"),
        SettingsActionRow(f"Media View: {media_view_value(config)}", "toggle_media_view"),
        SettingsActionRow(f"Grid Density: {grid_density_value(config)}", "cycle_grid_density"),
        numeric_settings_row(config, "page_size"),
        numeric_settings_row(config, "auto_load_threshold"),
        numeric_settings_row(config, "grid_prefetch_pages"),
    ]
    if libraries:
        rows.append(SettingsHeaderRow("Libraries"))
        ordered = ordered_libraries(libraries, config)
        rows.append(SettingsValueRow(f"Sidebar visibility: {hidden_library_count_value(config)}"))
        duplicate_titles = duplicate_library_titles(ordered)
        for library in ordered:
            rows.append(library_visibility_row(library, config, duplicate_titles))
            rows.append(library_order_row(library, "up", duplicate_titles))
            rows.append(library_order_row(library, "down", duplicate_titles))
    rows.extend([
        SettingsHeaderRow("Diagnostics"),
        SettingsValueRow(f"Config Path: {config_path()}"),
        SettingsValueRow(f"Cache Path: {cache_path()}"),
        SettingsValueRow(f"Debug Log: {debug_log_path()}"),
        SettingsValueRow(f"Client ID: {config.client_identifier or 'not set'}"),
        SettingsValueRow(f"Theme: {config.theme}"),
        SettingsActionRow("Show debug log path", "show_debug_log"),
        SettingsActionRow("Show recent debug log", "show_recent_debug_log"),
        SettingsActionRow("Show app diagnostics", "show_app_diagnostics"),
    ])
    return rows


def render_settings(config: AppConfig) -> str:
    lines = ["Settings"]
    append_settings_section(
        lines,
        "Account",
        [
            ("Server", config.base_url or "not set"),
            ("Server Token", "saved" if config.token else "not set"),
            ("Account Token", "saved" if config.account_token else "not set"),
            ("Home Token", "saved" if (config.home_account_token or config.account_token) else "not set"),
        ],
        ["Reconnect / reload libraries", "Relogin with Plex", "Switch Plex profile"],
    )
    append_settings_section(
        lines,
        "Streams",
        [
            ("Audio Preference", preference_value(config.preferred_audio_language)),
            ("Subtitle Mode", subtitle_mode_value(config)),
            ("Subtitle Language", subtitle_language_value(config)),
        ],
        [
            "Clear audio preference",
            "Set subtitles to Auto",
            "Set subtitles to None",
            "Clear subtitle preference",
            "Clear audio/subtitle preferences",
        ],
    )
    append_settings_section(
        lines,
        "Playback",
        [
            ("Playback Mode", playback_mode_value(config)),
            ("Playback Display", playback_display_value(config)),
            ("Start Over Prompt", show_setting_value(config.confirm_start_over)),
            ("Terminal Video", terminal_video_profile_value(config)),
            ("Transcode Quality", transcode_quality_value(config)),
            ("mpv Window Size", mpv_window_size_value(config)),
        ],
        [
            "Force transcode only when direct/default playback is not desired.",
            "Terminal playback is experimental, sub-par for normal watching, and takes over the terminal until mpv exits.",
            "Cycle common mpv sizes or set a custom value such as 80%, 90%, 1280x720, or 80%x80%.",
        ],
    )
    append_settings_section(
        lines,
        "Artwork",
        [
            ("Artwork", artwork_mode_value(config)),
            ("Details Artwork", detail_artwork_mode_value(config)),
            ("Artwork Renderer", artwork_renderer_value(config)),
        ],
    )
    append_settings_section(
        lines,
        "Browsing",
        [
            ("Library Enter", library_enter_action_value(config)),
            ("Playlists Sidebar", show_setting_value(config.show_playlists)),
            ("Discover Sidebar", show_setting_value(config.show_discover)),
            ("On Plex Sidebar", show_setting_value(config.show_on_plex)),
            ("Discover Type", discover_media_type_value(config)),
            ("Media View", media_view_value(config)),
            ("Grid Density", grid_density_value(config)),
            ("Page Size", str(config.page_size)),
            ("Auto-load Threshold", str(config.auto_load_threshold)),
            ("Grid Prefetch Pages", str(config.grid_prefetch_pages)),
            ("Hidden Libraries", hidden_library_count_value(config)),
        ],
        ["Custom browsing values use whole numbers inside the allowed range."],
    )
    append_settings_section(
        lines,
        "Diagnostics",
        [
            ("Config Path", str(config_path())),
            ("Cache Path", str(cache_path())),
            ("Debug Log", str(debug_log_path())),
            ("Client ID", config.client_identifier or "not set"),
            ("Theme", config.theme),
        ],
        ["Show recent debug log", "Show app diagnostics"],
    )
    return "\n".join(lines)


def append_settings_section(
    lines: list[str],
    heading: str,
    values: list[tuple[str, str]],
    notes: list[str] | None = None,
) -> None:
    lines.extend(["", heading])
    lines.extend(detail_key_value_rows(values))
    for note in notes or []:
        for index, line in enumerate(wrapped_detail_text(note, width=DETAIL_SUMMARY_WIDTH - 2)):
            lines.append(f"- {line}" if index == 0 else f"  {line}")


def render_help() -> str:
    return "\n".join([
        "Navigation",
        "enter: open selected row",
        "space: alternate library action",
        "escape: go back / close current view",
        "tab / shift+tab: move focus",
        "l: focus libraries",
        "m: focus media list",
        "d: focus details",
        "v: toggle list/grid view",
        "[: jump to previous alphabet section",
        "]: jump to next alphabet section",
        "left/right: move across grid cards",
        "pageup/pagedown: move one grid page",
        "",
        "Search",
        "/: fuzzy search loaded items in the current view",
        "g: search all libraries through Plex",
        "",
        "Playback",
        "p: play selected media from beginning",
        "r: resume selected media from saved progress",
        "c: pause / resume active mpv playback",
        "z: seek active playback back 10 seconds",
        "f: seek active playback forward 30 seconds",
        "w: mark selected media watched / unwatched",
        "x: stop launched mpv",
        "",
        "Playlist Management",
        "enter on Playlists sidebar row: browse all playlists",
        "P: add selected media to an existing or new playlist",
        "u: toggle selected item for bulk playlist actions",
        "backspace/delete: remove selected item from the open playlist",
        "e: rename selected or open playlist",
        "D: confirm delete selected or open playlist",
        "backspace/delete: remove selected item from Continue Watching",
        "",
        "Streams",
        "a: choose and save audio preference",
        "s: choose and save subtitle preference",
        "A: clear audio preference",
        "S: cycle subtitle mode",
        "",
        "Settings",
        ",: show settings",
        "ctrl+r: reconnect / reload libraries",
        "PLEX_TUI_PERF_LOG=1: write browsing timings and navigation diagnostics",
        "PLEX_TUI_ARTWORK_LOG=1: include verbose grid artwork internals",
        "?: show help",
        "q: quit",
        "",
        "Paths",
        f"Config: {config_path()}",
        f"Debug log: {debug_log_path()}",
    ])


LIBRARY_MENU_ENTRIES = (
    ("library", "Library", "Browse every item in this Plex library."),
    ("recommended", "Recommended", "Browse Plex hub rows such as recently added or promoted groups."),
    ("collections", "Collections", "Browse collections from this Plex library."),
    ("playlists", "Playlists", "Browse playlists connected to this Plex library."),
    ("categories", "Categories", "Browse genre/category groupings from this Plex library."),
)


LIBRARY_ENTRY_GLYPHS = {
    "library": "▦",
    "recommended": "✦",
    "collections": "◇",
    "playlists": "▤",
    "categories": "◈",
}


def library_menu_rows(library: LibraryItem) -> list[LibraryMenuRow]:
    return [
        LibraryMenuRow(library, entry, label, description)
        for entry, label, description in LIBRARY_MENU_ENTRIES
    ]


def library_entry_label(entry: str) -> str:
    for candidate, label, _description in LIBRARY_MENU_ENTRIES:
        if candidate == entry:
            return label
    return entry.replace("_", " ").title()


def library_entry_glyph(entry: str) -> str:
    return LIBRARY_ENTRY_GLYPHS.get(entry, "›")


def library_menu_description(library: LibraryItem) -> str:
    return "\n".join([
        library.title,
        "",
        "Choose how to browse this Plex library.",
        "",
        "▦ Library: all items.",
        "✦ Recommended: Plex hub rows.",
        "◇ Collections: library collections.",
        "▤ Playlists: library playlists.",
        "◈ Categories: genre/category groupings.",
    ])


def context_hint(row: object) -> str:
    if isinstance(row, ContinueWatchingRow):
        return "Libraries: Enter opens Continue Watching"
    if isinstance(row, PlaylistsRow):
        return "Libraries: Enter opens playlists"
    if isinstance(row, DiscoverRow):
        return "Libraries: Enter searches Plex Discover"
    if isinstance(row, OnPlexRow):
        return "Libraries: Enter browses Movies & Shows on Plex"
    if isinstance(row, AvailabilityRow):
        return "Availability: Enter opens provider link"
    if isinstance(row, ResumeChoiceRow):
        return "Playback: Enter chooses start point"
    if isinstance(row, LibraryRow):
        return "Libraries: Enter opens primary view / Space opens alternate view"
    if isinstance(row, LibraryMenuRow):
        return "Library: Enter opens browse mode"
    if isinstance(row, LoadMoreRow):
        return "Media: Enter loads next page"
    if isinstance(row, EmptyStateRow):
        return row.action_text or "Media: No items available"
    if isinstance(row, MediaRow):
        if row.media.kind == "playlist":
            return "Media: Enter opens playlist / e rename / D delete"
        if row.media.playable:
            return "Media: Enter selects / p play from beginning / r resume / P playlist / w watched / a audio / s subtitles"
        return "Media: Enter opens item"
    if isinstance(row, MediaGrid):
        media = row.selected_media
        if media is not None and media.playable:
            return "Grid: Arrows/page select card / p play from beginning / r resume / P playlist / w watched / a audio / s subtitles"
        return "Grid: Arrows/page select card / Enter opens item"
    if isinstance(row, ServerRow):
        return "Servers: Enter selects server"
    if isinstance(row, ProfileRow):
        return "Profiles: Enter switches profile"
    if isinstance(row, StreamRow):
        return "Streams: Enter saves preference"
    if isinstance(row, PlaylistCreateRow):
        return "Playlists: Enter creates a new playlist"
    if isinstance(row, PlaylistTargetRow):
        return "Playlists: Enter adds selected media"
    if isinstance(row, SettingsNumericRow):
        return "Settings: Enter edits / Left-Right adjusts"
    if isinstance(row, SettingsActionRow):
        if row.action_kind == "confirm":
            return "Settings: Enter arms / Enter again confirms"
        if row.action_kind == "input":
            return "Settings: Enter edits value"
        if row.action_kind == "toggle":
            return "Settings: Enter or Left-Right toggles"
        if row.action_kind == "cycle":
            return "Settings: Enter or Left-Right cycles"
        if row.action_kind == "step":
            return "Settings: Enter adjusts setting"
        if row.action_kind == "reset":
            return "Settings: Enter resets setting"
        if row.action_kind == "show":
            return "Settings: Enter shows details"
        if row.action_kind == "set":
            return "Settings: Enter sets value"
        return "Settings: Enter runs action"
    if isinstance(row, SettingsHeaderRow):
        return "Settings: Section header"
    if isinstance(row, SettingsValueRow):
        return "Settings: Current value"
    return "Enter selects row"


def current_detail_actions(state: BrowseState | None, item: MediaItem | None = None) -> tuple[str, ...]:
    if state is not None and state.source == "discover" and item is not None:
        if availability_urls(item.raw):
            return ("Availability: Enter opens provider link",)
        return ("Availability: No provider links found",)
    if item is not None and item.playable and is_online_metadata(item.raw):
        return ("Availability: Listed by Plex; playable stream checked on play",)
    if item is not None and item.kind == "playlist":
        return (
            "Playlist: Enter opens contents",
            "Playlist: e renames / D deletes",
        )
    if is_playlist_browse_state(state):
        return (PLAYLIST_REMOVE_HINT,)
    return ()


def media_row_status(row: MediaRow, state: BrowseState | None) -> str:
    if state is not None and state.source == "discover" and availability_urls(row.media.raw):
        return "Media: Enter opens availability link or provider picker"
    status = context_hint(row)
    if is_playlist_browse_state(state):
        status = f"{status} / Backspace/Delete remove from playlist"
    return status


def render_browse_status(state: BrowseState) -> str:
    status = render_loaded_status(state.title, len(state.items), state.total, state.has_more, state.items)
    if is_playlist_browse_state(state):
        status = f"{status} / Backspace/Delete removes selected item"
    return status


def is_playlist_browse_state(state: BrowseState | None) -> bool:
    return bool(state is not None and state.source == "playlist")


def settings_action_kind(action: str) -> str:
    if confirmation_required(action):
        return "confirm"
    if action.startswith("set_"):
        return "input"
    if action.startswith(("increase_", "decrease_", "move_")):
        return "step"
    if action.startswith("reset_"):
        return "reset"
    if action.startswith("toggle_"):
        return "toggle"
    if action.startswith("cycle_"):
        return "cycle"
    if action.startswith("show_"):
        return "show"
    if action.startswith("artwork_renderer_") or action.startswith("subtitle_"):
        return "set"
    if action in {"reload", "relogin"}:
        return "run"
    return "run"


def settings_action_badge(action_kind: str) -> str:
    badges = {
        "confirm": "confirm",
        "input": "edit",
        "step": "step",
        "reset": "reset",
        "toggle": "toggle",
        "cycle": "cycle",
        "show": "show",
        "set": "set",
        "run": "run",
    }
    return badges.get(action_kind, action_kind)


def render_settings_row_details(
    row: SettingsActionRow | SettingsHeaderRow | SettingsValueRow,
    config: AppConfig,
    pending_confirmation_action: str = "",
) -> str:
    if isinstance(row, SettingsHeaderRow):
        return "\n".join([
            "Settings Section",
            "",
            row.label_text,
            "",
            "Controls",
            "- Up/Down moves through rows.",
            "- Enter runs the highlighted setting when available.",
        ])
    if isinstance(row, SettingsValueRow):
        return "\n".join([
            "Current Setting",
            "",
            row.label_text,
            "",
            "This row is informational and does not change on Enter.",
            "",
            "Controls",
            "- Up/Down moves through rows.",
        ])

    if pending_confirmation_action == row.action and confirmation_required(row.action):
        return (
            "Confirm Action\n\n"
            f"{settings_action_label(row.action)}\n\n"
            "Status: armed\n\n"
            f"{settings_action_current_value(row.action, config)}\n\n"
            "Controls\n"
            "- Press Enter on this same row again to confirm.\n"
            "- Move away to cancel the confirmation."
        )

    if isinstance(row, SettingsNumericRow):
        spec = numeric_setting_spec(row.setting_name)
        return "\n".join([
            "Numeric Setting",
            "",
            settings_action_label(row.action),
            "",
            f"Current value: {getattr(config, row.setting_name)}",
            f"Allowed range: {spec['minimum']} to {spec['maximum']}",
            f"Step: {spec['step']}",
            f"Default: {spec['default']}",
            "",
            "Controls",
            "- Enter edits the value.",
            "- Left/Right adjusts by one step.",
            "- Submit an empty value to reset to default.",
        ])

    if row.action_kind in {"toggle", "cycle"}:
        lines = [
            "Setting Control",
            "",
            settings_action_label(row.action),
            "",
            f"Type: {row.action_kind}",
            settings_action_current_value(row.action, config),
            "",
            "Controls",
            "- Enter changes this setting.",
            "- Left/Right changes this setting without opening an input.",
        ]
        return "\n".join(line for line in lines if line)

    lines = [
        "Setting Action",
        "",
        settings_action_label(row.action),
        "",
        f"Type: {row.action_kind}",
        settings_action_current_value(row.action, config),
        "",
        "Controls",
        settings_action_help(row.action),
    ]
    return "\n".join(line for line in lines if line)


def render_settings_change_details(action: str, label: str, value: str, config: AppConfig) -> str:
    lines = [
        "Setting Saved",
        "",
        label,
        "",
        f"Current value: {value}",
    ]
    current = settings_action_current_value(action, config)
    if current and current != f"Current value: {value}":
        lines.extend(["", current])
    lines.extend([
        "",
        "Controls",
        "- The changed row remains selected.",
        f"- {settings_action_help(action)}",
    ])
    return "\n".join(lines)


def settings_action_current_value(action: str, config: AppConfig) -> str:
    if action == "clear_tracks":
        return (
            f"Current audio preference: {preference_value(config.preferred_audio_language)}\n"
            f"Current subtitle mode: {subtitle_mode_value(config)}\n"
            f"Current subtitle language: {subtitle_language_value(config)}"
        )
    if action == "clear_audio":
        return f"Current audio preference: {preference_value(config.preferred_audio_language)}"
    if action == "switch_profile":
        return f"Profile switching: {'available' if (config.home_account_token or config.account_token) else 'login required'}"
    if action in {"subtitle_auto", "subtitle_none", "clear_subtitle"}:
        return (
            f"Current subtitle mode: {subtitle_mode_value(config)}\n"
            f"Current subtitle language: {subtitle_language_value(config)}"
        )
    if action == "cycle_subtitle_mode":
        return (
            f"Current subtitle mode: {subtitle_mode_value(config)}\n"
            f"Current subtitle language: {subtitle_language_value(config)}"
        )
    if action in {"cycle_mpv_window_size", "set_mpv_window_size", "reset_mpv_window_size"}:
        return f"Current mpv window size: {mpv_window_size_value(config)}"
    if action == "cycle_playback_mode":
        return f"Current playback mode: {playback_mode_value(config)}"
    if action == "cycle_playback_display":
        return f"Current playback display: {playback_display_value(config)}"
    if action == "toggle_confirm_start_over":
        return f"Current start-over prompt: {show_setting_value(config.confirm_start_over)}"
    if action == "cycle_terminal_video_profile":
        return f"Current terminal video: {terminal_video_profile_value(config)}"
    if action == "cycle_transcode_quality":
        return f"Current transcode quality: {transcode_quality_value(config)}"
    if action == "toggle_artwork":
        return f"Current artwork: {artwork_mode_value(config)}"
    if action == "cycle_detail_artwork":
        return f"Current details artwork: {detail_artwork_mode_value(config)}"
    if action.startswith("artwork_renderer_") or action == "cycle_artwork_renderer":
        return f"Current artwork renderer: {artwork_renderer_value(config)}"
    if action == "toggle_media_view":
        return f"Current media view: {media_view_value(config)}"
    if action == "toggle_show_playlists":
        return f"Current Playlists sidebar: {show_setting_value(config.show_playlists)}"
    if action == "toggle_show_discover":
        return f"Current Discover sidebar: {show_setting_value(config.show_discover)}"
    if action == "toggle_show_on_plex":
        return f"Current On Plex sidebar: {show_setting_value(config.show_on_plex)}"
    if action == "cycle_discover_media_type":
        return f"Current Discover type: {discover_media_type_value(config)}"
    if action == "cycle_library_enter_action":
        return f"Current library Enter action: {library_enter_action_value(config)}"
    if action == "cycle_grid_density":
        return f"Current grid density: {grid_density_value(config)}"
    if action.startswith("toggle_library_visibility:"):
        key = action.removeprefix("toggle_library_visibility:")
        state = "Hidden" if key in config.hidden_library_keys else "Visible"
        return f"Current library visibility: {state}"
    if action.startswith(("move_library_up:", "move_library_down:")):
        return "Current library order can be changed from the Libraries section."
    if "page_size" in action:
        return f"Current page size: {config.page_size}"
    if "auto_load_threshold" in action:
        return f"Current auto-load threshold: {config.auto_load_threshold}"
    if "grid_prefetch_pages" in action:
        return f"Current grid prefetch pages: {config.grid_prefetch_pages}"
    if action == "show_app_diagnostics":
        return f"Version: {__version__}"
    if action.startswith("show_"):
        return f"Debug log: {debug_log_path()}"
    return ""


def settings_action_help(action: str) -> str:
    if confirmation_required(action):
        return "Press Enter once to arm this change. Press Enter again on the same row to confirm."
    if action == "reload":
        return "Press Enter to reconnect and reload libraries."
    if action == "relogin":
        return "Press Enter to start Plex login again."
    if action == "switch_profile":
        return "Press Enter to choose a Plex Home profile. PIN-protected profiles ask for a PIN."
    if action == "subtitle_auto":
        return "Press Enter to let Plex or saved language preference choose subtitles."
    if action == "subtitle_none":
        return "Press Enter to disable subtitles by default."
    if action == "cycle_subtitle_mode":
        return "Press Enter to cycle subtitle mode. Use subtitle picker to save a preferred language."
    if action == "cycle_mpv_window_size":
        return "Press Enter to cycle through default window-size presets."
    if action == "cycle_playback_mode":
        return "Press Enter to choose auto/direct-default playback or force Plex transcoding."
    if action == "cycle_playback_display":
        return "Press Enter to choose external mpv windows or novelty terminal playback."
    if action == "toggle_confirm_start_over":
        return "Press Enter to ask before starting over when selected media can resume."
    if action == "cycle_terminal_video_profile":
        return "Press Enter to choose smooth, balanced, or sharp terminal playback."
    if action == "cycle_transcode_quality":
        return "Press Enter to choose the quality used when playback mode forces transcoding."
    if action == "set_mpv_window_size":
        return "Press Enter to type a custom size such as 1280x720, 80%, or 80%x80%."
    if action == "toggle_artwork":
        return "Press Enter to turn artwork fetching on or off."
    if action == "cycle_detail_artwork":
        return "Press Enter to choose where poster art appears in the details pane."
    if action.startswith("artwork_renderer_") or action == "cycle_artwork_renderer":
        return "Press Enter to select this terminal artwork renderer."
    if action == "toggle_media_view":
        return "Press Enter to switch between list and grid browsing."
    if action == "toggle_show_playlists":
        return "Press Enter to show or hide Playlists in the sidebar."
    if action == "toggle_show_discover":
        return "Press Enter to show or hide Discover in the sidebar."
    if action == "toggle_show_on_plex":
        return "Press Enter to show or hide On Plex in the sidebar."
    if action == "cycle_discover_media_type":
        return "Press Enter to filter Discover searches by movies, shows, or all results."
    if action == "cycle_library_enter_action":
        return "Press Enter to choose whether library rows open all items or browse modes by default."
    if action == "cycle_grid_density":
        return "Press Enter to cycle compact, comfortable, and large grid layouts."
    if action.startswith("toggle_library_visibility:"):
        return "Press Enter to show or hide this library in the sidebar."
    if action.startswith(("move_library_up:", "move_library_down:")):
        return "Press Enter to move this library in the sidebar order."
    if action.startswith(("increase_", "decrease_")):
        return "Press Enter to adjust this value by one step."
    if action.startswith("reset_"):
        return "Press Enter to restore the default value."
    if action.startswith("set_"):
        return "Press Enter to type a custom value."
    if action == "show_debug_log":
        return "Press Enter to show the debug log path."
    if action == "show_recent_debug_log":
        return "Press Enter to show the most recent debug log lines."
    if action == "show_app_diagnostics":
        return "Press Enter to show version, paths, playback, artwork, and browsing diagnostics."
    return "Press Enter to run this action."


def confirmation_required(action: str) -> bool:
    return action in {"clear_tracks", "clear_audio", "clear_subtitle"}


def settings_action_label(action: str) -> str:
    labels = {
        "clear_tracks": "Clear audio/subtitle preferences",
        "clear_audio": "Clear audio preference",
        "clear_subtitle": "Clear subtitle preference",
        "reload": "Reconnect / reload libraries",
        "relogin": "Relogin with Plex",
        "switch_profile": "Switch Plex profile",
        "subtitle_auto": "Set subtitles to Auto",
        "subtitle_none": "Set subtitles to None",
        "cycle_subtitle_mode": "Subtitle Mode",
        "cycle_playback_mode": "Playback Mode",
        "cycle_playback_display": "Playback Display",
        "toggle_confirm_start_over": "Start Over Prompt",
        "cycle_terminal_video_profile": "Terminal Video",
        "cycle_transcode_quality": "Transcode Quality",
        "cycle_mpv_window_size": "mpv Window Size",
        "set_mpv_window_size": "mpv Window Size",
        "reset_mpv_window_size": "mpv Window Size: reset to Default",
        "toggle_artwork": "Artwork",
        "cycle_detail_artwork": "Details Artwork",
        "artwork_renderer_block": "Artwork Renderer: block",
        "artwork_renderer_auto": "Artwork Renderer: auto",
        "artwork_renderer_kitty": "Artwork Renderer: Kitty",
        "cycle_artwork_renderer": "Artwork Renderer",
        "toggle_media_view": "Media View",
        "toggle_show_playlists": "Playlists Sidebar",
        "toggle_show_discover": "Discover Sidebar",
        "cycle_discover_media_type": "Discover Type",
        "cycle_library_enter_action": "Library Enter",
        "cycle_grid_density": "Grid Density",
        "decrease_page_size": "Page Size: decrease",
        "increase_page_size": "Page Size: increase",
        "set_page_size": "Page Size",
        "reset_page_size": f"Page Size: reset to {DEFAULT_PAGE_SIZE}",
        "decrease_auto_load_threshold": "Auto-load Threshold: decrease",
        "increase_auto_load_threshold": "Auto-load Threshold: increase",
        "set_auto_load_threshold": "Auto-load Threshold",
        "reset_auto_load_threshold": f"Auto-load Threshold: reset to {DEFAULT_AUTO_LOAD_THRESHOLD}",
        "decrease_grid_prefetch_pages": "Grid Prefetch Pages: decrease",
        "increase_grid_prefetch_pages": "Grid Prefetch Pages: increase",
        "set_grid_prefetch_pages": "Grid Prefetch Pages",
        "reset_grid_prefetch_pages": f"Grid Prefetch Pages: reset to {DEFAULT_GRID_PREFETCH_PAGES}",
        "show_debug_log": "Show debug log path",
        "show_recent_debug_log": "Show recent debug log",
        "show_app_diagnostics": "Show app diagnostics",
    }
    if action.startswith("toggle_library_visibility:"):
        return "Library visibility"
    if action.startswith("move_library_up:"):
        return "Library order: move up"
    if action.startswith("move_library_down:"):
        return "Library order: move down"
    return labels.get(action, action)


def numeric_settings_row(config: AppConfig, name: str) -> SettingsNumericRow:
    spec = numeric_setting_spec(name)
    value = int(getattr(config, name))
    label = f"{spec['label']}: {value}"
    return SettingsNumericRow(label, f"set_{name}", name)


def numeric_setting_spec(name: str) -> dict[str, int | str]:
    specs: dict[str, dict[str, int | str]] = {
        "page_size": {
            "label": "Page Size",
            "minimum": MIN_PAGE_SIZE,
            "maximum": MAX_PAGE_SIZE,
            "default": DEFAULT_PAGE_SIZE,
            "step": 10,
        },
        "auto_load_threshold": {
            "label": "Auto-load Threshold",
            "minimum": MIN_AUTO_LOAD_THRESHOLD,
            "maximum": MAX_AUTO_LOAD_THRESHOLD,
            "default": DEFAULT_AUTO_LOAD_THRESHOLD,
            "step": 5,
        },
        "grid_prefetch_pages": {
            "label": "Grid Prefetch Pages",
            "minimum": MIN_GRID_PREFETCH_PAGES,
            "maximum": MAX_GRID_PREFETCH_PAGES,
            "default": DEFAULT_GRID_PREFETCH_PAGES,
            "step": 1,
        },
    }
    return specs[name]


def numeric_setting_label(name: str) -> str:
    if name == "auto_load_threshold":
        return "Auto-load threshold"
    if name == "grid_prefetch_pages":
        return "Grid prefetch pages"
    if name == "page_size":
        return "Page size"
    return name


def render_loaded_status(
    title: str,
    loaded: int,
    total: int | None,
    has_more: bool,
    items: list[MediaItem] | None = None,
) -> str:
    suffix = progress_count_suffix(items)
    if total is None:
        return f"{title}: {loaded} items{suffix}"
    if has_more:
        return f"{title}: {loaded} of {total} items loaded{suffix}"
    return f"{title}: {loaded} items{suffix}"


def progress_count_suffix(items: list[MediaItem] | None) -> str:
    count = in_progress_count(items or [])
    if not count:
        return ""
    label = "item" if count == 1 else "items"
    return f" / {count} in-progress {label}"


def in_progress_count(items: list[MediaItem]) -> int:
    return sum(1 for item in items if watched_state(item.raw) == "in progress")


def empty_state_message(state: BrowseState) -> str:
    if state.search:
        return "No matching media"
    if state.source == "continue_watching":
        return "Nothing in progress"
    if state.context_media is not None and state.context_media.kind == "playlist":
        return "Playlist is empty"
    return "No items found"


def empty_state_action(state: BrowseState) -> str:
    if state.search:
        return "Try a broader search or switch scope."
    if state.source == "continue_watching":
        return "Start playback from a library item to populate this view."
    if state.context_media is not None and state.context_media.kind == "playlist":
        return "Use P on playable media to add items."
    return "Go back or choose another library view."


def render_empty_state_details(title: str, message: str, action: str = "") -> str:
    lines = [
        "◇ Empty View",
        title,
        "-" * min(max(len(title), 8), DETAIL_SUMMARY_WIDTH),
        message,
    ]
    if action:
        lines.extend(["", "Next Step", action])
    return "\n".join(lines)


def render_loading_state_details(title: str, message: str) -> str:
    return "\n".join([
        "✦ Loading",
        title,
        "-" * min(max(len(title), 8), DETAIL_SUMMARY_WIDTH),
        message,
    ])


def render_error_state_details(title: str, error: str, diagnostic: str, recovery: str) -> str:
    lines = [
        f"△ {title}",
        "-" * min(max(len(title), 8), DETAIL_SUMMARY_WIDTH),
        "Cause",
        *wrapped_detail_text(error),
        "",
        "Diagnostics",
        *wrapped_detail_text(diagnostic),
        "",
        "Next Step",
        *wrapped_detail_text(recovery),
    ]
    return "\n".join(lines)


def alphabet_jump_index(items: list[MediaItem], current_index: int, direction: int) -> int | None:
    if not items or direction == 0:
        return None
    current_index = min(max(0, current_index), len(items) - 1)
    current_group = alphabet_group_label(items[current_index])
    if direction > 0:
        for index in range(current_index + 1, len(items)):
            if alphabet_group_label(items[index]) != current_group:
                return index
        return None

    group_start = current_index
    while group_start > 0 and alphabet_group_label(items[group_start - 1]) == current_group:
        group_start -= 1
    if group_start == 0:
        return None
    previous_group = alphabet_group_label(items[group_start - 1])
    index = group_start - 1
    while index > 0 and alphabet_group_label(items[index - 1]) == previous_group:
        index -= 1
    return index


def alphabet_section_groups(items: list[MediaItem]) -> list[str]:
    groups: list[str] = []
    for item in items:
        group = alphabet_group_label(item)
        if not groups or groups[-1] != group:
            groups.append(group)
    return groups


def write_alphabet_jump_log(
    items: list[MediaItem],
    current_index: int,
    direction: int,
    target_index: int | None,
) -> None:
    if os.environ.get("PLEX_TUI_PERF_LOG") != "1" or not items:
        return
    current_index = min(max(0, current_index), len(items) - 1)
    current = items[current_index]
    target = items[target_index] if target_index is not None else None
    direction_label = "next" if direction > 0 else "previous"
    groups = ",".join(alphabet_section_groups(items))
    target_detail = (
        "target_index=None"
        if target is None or target_index is None
        else (
            f"target_index={target_index} target_group={alphabet_group_label(target)!r} "
            f"target_title={target.title!r} target_sort_title={alphabet_title(target)!r}"
        )
    )
    write_debug_log(
        f"nav alphabet_jump direction={direction_label} loaded={len(items)} "
        f"current_index={current_index} current_group={alphabet_group_label(current)!r} "
        f"current_title={current.title!r} current_sort_title={alphabet_title(current)!r} "
        f"section_groups={groups!r} {target_detail}"
    )


def alphabet_group_label(item: MediaItem) -> str:
    title = alphabet_title(item).strip()
    for character in title:
        if character.isalnum():
            return character.upper() if character.isalpha() else "#"
    return "#"


def alphabet_title(item: MediaItem) -> str:
    for attr in ("titleSort", "sortTitle", "title_sort"):
        value = getattr(item.raw, attr, None)
        if value:
            return str(value)
    return item.title


def grid_status(grid: MediaGrid, state: BrowseState | None) -> str:
    total_loaded = len(grid.items)
    total_available = state.total if state is not None else None
    page_count = max(1, (total_loaded + grid.page_size - 1) // grid.page_size)
    current_page = min(page_count, (grid.selected_index // grid.page_size) + 1)
    selected = min(grid.selected_index + 1, total_loaded)
    total_text = f"{total_loaded} loaded" if total_available is None else f"{total_loaded} of {total_available} loaded"
    hint = context_hint(grid)
    selected_media = grid.selected_media
    if state is not None and state.source == "discover" and selected_media is not None and availability_urls(selected_media.raw):
        hint = "Grid: Arrows/page select card / Enter opens availability link or provider picker"
    status = f"{hint} / item {selected} / page {current_page} of {page_count} / {total_text}{progress_count_suffix(grid.items)}"
    if is_playlist_browse_state(state):
        status = f"{status} / Backspace/Delete remove from playlist"
    return status


def grid_page_key(items: list[MediaItem]) -> tuple[str, ...]:
    return tuple(item.key for item in items)


def should_auto_load_more(state: BrowseState, selected_key: str, threshold: int) -> bool:
    if not state.has_more:
        return False
    if threshold <= 0:
        return False
    start_index = max(0, len(state.items) - threshold)
    for index, item in enumerate(state.items):
        if item.key == selected_key:
            return index >= start_index
    return False


def render_picker_details(stream_type: str, current_choice: StreamChoice | None, config: AppConfig) -> str:
    lines = [
        "Current Selection",
        current_choice.label if current_choice is not None else "None available",
        "",
        "Saved Preference",
    ]
    if stream_type == "audio":
        lines.append(f"Audio: {preference_value(config.preferred_audio_language)}")
    else:
        lines.append(f"Subtitles: {subtitle_preference_value(config)}")
    lines.extend([
        "",
        "Enter saves the highlighted track as the global preference for future playback.",
        "Escape returns without changing the saved preference.",
    ])
    return "\n".join(lines)


def preference_value(value: str) -> str:
    return value or "Plex/default"


def subtitle_preference_value(config: AppConfig) -> str:
    if config.subtitle_mode == "none":
        return "None"
    if config.subtitle_mode == "preferred":
        return preference_value(config.preferred_subtitle_language)
    return "Plex/default"


def subtitle_mode_value(config: AppConfig) -> str:
    if config.subtitle_mode == "none":
        return "None"
    if config.subtitle_mode == "preferred":
        return "Preferred"
    return "Auto"


def subtitle_language_value(config: AppConfig) -> str:
    if config.subtitle_mode != "preferred":
        return "Plex/default"
    return preference_value(config.preferred_subtitle_language)


def artwork_mode_value(config: AppConfig) -> str:
    return "On" if config.artwork_mode == "on" else "Off"


def artwork_renderer_value(config: AppConfig) -> str:
    if config.artwork_renderer == "kitty":
        return "Kitty"
    if config.artwork_renderer == "auto":
        return "Auto"
    return "Block"


def next_artwork_renderer(value: str) -> str:
    values = ["block", "auto", "kitty"]
    try:
        index = values.index(value)
    except ValueError:
        return "block"
    return values[(index + 1) % len(values)]


def detail_artwork_mode_value(config: AppConfig) -> str:
    if config.detail_artwork_mode == "on":
        return "On"
    if config.detail_artwork_mode == "off":
        return "Off"
    return "List only"


def next_detail_artwork_mode(value: str) -> str:
    if value == "list_only":
        return "on"
    if value == "on":
        return "off"
    return "list_only"


def media_view_value(config: AppConfig) -> str:
    if config.media_view == "grid":
        return "Grid"
    return "List"


def show_setting_value(value: bool) -> str:
    return "Shown" if value else "Hidden"


def discover_media_type_value(config: AppConfig) -> str:
    labels = {
        "movies_shows": "Movies & Shows",
        "movie": "Movies",
        "show": "Shows",
        "all": "All",
    }
    return labels.get(config.discover_media_type, "Movies & Shows")


def next_discover_media_type(value: str) -> str:
    values = ["movies_shows", "movie", "show", "all"]
    try:
        index = values.index(value)
    except ValueError:
        return "movies_shows"
    return values[(index + 1) % len(values)]


def library_enter_action_value(config: AppConfig) -> str:
    if config.library_enter_action == "browse_modes":
        return "Browse Modes"
    return "Library"


def next_library_enter_action(value: str) -> str:
    return "browse_modes" if value == "library" else "library"


def grid_density_value(config: AppConfig) -> str:
    if config.grid_density == "compact":
        return "Compact"
    if config.grid_density == "large":
        return "Large"
    return "Comfortable"


def next_media_view(media_view: str) -> str:
    return "grid" if media_view == "list" else "list"


def next_grid_density(value: str) -> str:
    values = ["comfortable", "large", "compact"]
    try:
        index = values.index(value)
    except ValueError:
        return "comfortable"
    return values[(index + 1) % len(values)]


def mpv_window_size_value(config: AppConfig) -> str:
    if config.mpv_window_size:
        return config.mpv_window_size
    return f"Default ({DEFAULT_MPV_WINDOW_SIZE})"


def effective_mpv_window_size(config: AppConfig) -> str:
    return config.mpv_window_size or DEFAULT_MPV_WINDOW_SIZE


def playback_mode_value(config: AppConfig) -> str:
    if config.playback_mode == "transcode":
        return "Force transcode"
    return "Auto / direct default"


def next_playback_mode(value: str) -> str:
    return "transcode" if value == "auto" else "auto"


def playback_display_value(config: AppConfig) -> str:
    if config.playback_display == "terminal":
        return "Terminal graphics"
    return "External mpv window"


def next_playback_display(value: str) -> str:
    return "terminal" if value == "external" else "external"


def terminal_video_profile_value(config: AppConfig) -> str:
    labels = {
        "smooth": "Smooth (15 fps / 640px)",
        "balanced": "Balanced (24 fps / 854px)",
        "sharp": "Sharp (24 fps / 960px)",
    }
    return labels.get(config.terminal_video_profile, labels["smooth"])


def next_terminal_video_profile(value: str) -> str:
    values = ["smooth", "balanced", "sharp"]
    try:
        index = values.index(value)
    except ValueError:
        return "smooth"
    return values[(index + 1) % len(values)]


def transcode_quality_value(config: AppConfig) -> str:
    return transcode_quality_label(config.transcode_quality)


def next_transcode_quality(value: str) -> str:
    qualities = ["original", "1080p_8", "720p_4", "480p_2"]
    try:
        index = qualities.index(value)
    except ValueError:
        return "original"
    return qualities[(index + 1) % len(qualities)]


def next_mpv_window_size(value: str) -> str:
    if value == "1280x720":
        return ""
    sizes = ["", "80%", "90%", "100%", "1600x900", "1920x1080"]
    try:
        index = sizes.index(value)
    except ValueError:
        return ""
    return sizes[(index + 1) % len(sizes)]


def render_playback_preferences(
    config: AppConfig,
    audio_choice: StreamChoice | None,
    subtitle_choice: StreamChoice | None,
) -> str:
    return "; ".join([
        render_audio_playback_preference(config, audio_choice),
        render_subtitle_playback_preference(config, subtitle_choice),
    ])


def render_playback_status(
    title: str,
    player: PlayerHandle,
    config: AppConfig,
    audio_choice: StreamChoice | None,
    subtitle_choice: StreamChoice | None,
) -> str:
    details = [f"Playing {title}"]
    if player.start_offset_ms:
        details.append(f"resume {format_offset(player.start_offset_ms)}")
    details.append(f"mode {player.stream_mode}")
    if config.playback_mode == "transcode":
        details.append(f"quality {transcode_quality_value(config)}")
    if config.playback_display == "terminal":
        details.append("terminal display")
    if player.subtitle_count:
        details.append(f"{player.subtitle_count} subtitles")
    details.append(render_playback_preferences(config, audio_choice, subtitle_choice))
    details.append(PLAYBACK_CONTROL_HINT)
    return " / ".join(details)


def render_playback_details(
    title: str,
    player: PlayerHandle,
    config: AppConfig,
    audio_choice: StreamChoice | None,
    subtitle_choice: StreamChoice | None,
) -> str:
    lines = [
        title,
        "",
        "Playback",
        "Status: Playing",
        f"Mode: {player.stream_mode}",
        f"Playback preference: {playback_mode_value(config)}",
        f"Playback display: {playback_display_value(config)}",
        f"Terminal video: {terminal_video_profile_value(config)}",
        f"Transcode quality: {transcode_quality_value(config)}",
        f"Resume: {format_offset(player.start_offset_ms) if player.start_offset_ms else 'start'}",
        f"Subtitles available: {player.subtitle_count}",
        f"mpv window: {mpv_window_size_value(config)}",
        "",
        "Controls",
        *playback_control_rows(config),
        "",
        "Selected Streams",
        f"Audio: {render_audio_playback_preference(config, audio_choice).removeprefix('audio ')}",
        f"Subtitles: {render_subtitle_playback_preference(config, subtitle_choice).removeprefix('subtitles ')}",
        "",
        "Diagnostics",
        f"Debug log: {debug_log_path()}",
        "Use Settings > Show recent debug log if playback exits unexpectedly.",
    ]
    return "\n".join(lines)


def playback_control_rows(config: AppConfig) -> list[str]:
    if config.playback_display == "terminal":
        return [
            "Terminal playback owns the screen until mpv exits.",
            "Use mpv keyboard controls while the terminal player is active.",
        ]
    return [
        "c: pause / resume active playback",
        "z: seek back 10 seconds",
        "f: seek forward 30 seconds",
        "x: stop playback",
    ]


def recent_debug_log_lines(path: Path, max_lines: int = 20) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError):
        return ["Unable to read debug log."]
    if max_lines <= 0:
        return []
    return lines[-max_lines:]


def render_debug_log_details(path: Path, max_lines: int = 20) -> str:
    lines = [
        "Recent Debug Log",
        "",
        f"Path: {path}",
        "",
        f"Last {max_lines} lines",
    ]
    recent = recent_debug_log_lines(path, max_lines)
    if recent:
        lines.extend(recent)
    else:
        lines.append("No debug log entries yet.")
    lines.extend([
        "",
        "Set PLEX_TUI_PERF_LOG=1 before launch to include browsing performance timings.",
    ])
    return "\n".join(lines)


def detect_mpv() -> tuple[str, str]:
    path = shutil.which("mpv")
    if path is None:
        return "missing", "mpv was not found on PATH"
    try:
        result = subprocess.run(
            [path, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return path, f"version check failed: {exc}"
    first_line = (result.stdout or result.stderr).splitlines()
    version = first_line[0].strip() if first_line else "version unknown"
    return path, version


def mpv_install_hints() -> list[str]:
    return [
        "Install mpv:",
        "  macOS/Homebrew: brew install mpv",
        "  Debian/Ubuntu: sudo apt install mpv",
        "  Fedora: sudo dnf install mpv",
        "  Arch Linux / Manjaro: sudo pacman -S mpv",
    ]


def playback_failure_hints(error: str, recent_log: list[str] | None = None) -> list[str]:
    text = "\n".join([error, *(recent_log or [])]).lower()
    hints: list[str] = []
    if "mpv was not found" in text or "mpv missing" in text or "no such file or directory: 'mpv'" in text:
        hints.extend(mpv_install_hints())
    elif "failed to launch mpv" in text or "permission denied" in text:
        hints.extend([
            "mpv launch failed:",
            "  Confirm mpv is executable and available on PATH.",
            "  Run `mpv --version` in the same shell used to start plex-tui.",
        ])
    if "could not get stream url" in text:
        hints.extend([
            "Plex did not provide a stream URL:",
            "  Confirm the server is reachable and the saved token still works.",
            "  Try reloading libraries or signing in again from Settings.",
        ])
    if "empty stream url" in text:
        hints.extend([
            "Plex returned an empty stream URL:",
            "  Try a different item to separate media-specific issues from server issues.",
            "  Check whether Plex can play the item in its own web player.",
        ])
    if ("sub-file" in text or "subtitle" in text) and ("failed" in text or "error" in text):
        hints.extend([
            "Subtitle playback may be involved:",
            "  Try Subtitle Mode: none, then retry playback.",
            "  If that works, choose a different subtitle track or clear the saved subtitle preference.",
        ])
    if "playback exited with code" in text:
        hints.extend([
            "mpv exited abnormally:",
            "  Open the debug log path above and check the launch arguments.",
            "  Retry from a terminal with the same media if you need raw mpv output.",
        ])
    return dedupe_lines(hints)


def dedupe_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        deduped.append(line)
    return deduped


def render_app_diagnostics(config: AppConfig, mpv_info: tuple[str, str]) -> str:
    mpv_path, mpv_version = mpv_info
    lines = [
        "App Diagnostics",
        "",
        "Application",
        f"Version: {__version__}",
        f"Theme: {config.theme}",
        "",
        "Paths",
        f"Config: {config_path()}",
        f"Cache: {cache_path()}",
        f"Debug log: {debug_log_path()}",
        "",
        "Plex",
        f"Server: {config.base_url or 'not set'}",
        f"Server token: {'saved' if config.token else 'not set'}",
        f"Account token: {'saved' if config.account_token else 'not set'}",
        f"Client ID: {config.client_identifier or 'not set'}",
        "",
        "Playback",
        f"mpv: {mpv_path}",
        f"mpv version: {mpv_version}",
        f"mpv window size: {mpv_window_size_value(config)}",
        f"Playback mode: {playback_mode_value(config)}",
        f"Playback display: {playback_display_value(config)}",
        f"Terminal video: {terminal_video_profile_value(config)}",
        f"Transcode quality: {transcode_quality_value(config)}",
    ]
    if mpv_path == "missing" or mpv_version.startswith("version check failed"):
        lines.extend(["", *mpv_install_hints()])
    lines.extend([
        "",
        "Streams",
        f"Audio preference: {preference_value(config.preferred_audio_language)}",
        f"Subtitle mode: {subtitle_mode_value(config)}",
        f"Subtitle language: {subtitle_language_value(config)}",
        "",
        "Artwork",
        f"Artwork: {artwork_mode_value(config)}",
        f"Renderer: {artwork_renderer_value(config)}",
        f"Renderer status: {protocol_renderer_status(config.artwork_renderer)}",
        f"Details artwork: {detail_artwork_mode_value(config)}",
        "",
        "Browsing",
        f"Media view: {media_view_value(config)}",
        f"Grid density: {grid_density_value(config)}",
        f"Page size: {config.page_size}",
        f"Auto-load threshold: {config.auto_load_threshold}",
        f"Grid prefetch pages: {config.grid_prefetch_pages}",
    ])
    return "\n".join(lines)


def render_playback_error_details(error: str, path: Path, max_lines: int = 12) -> str:
    recent = recent_debug_log_lines(path, max_lines)
    lines = [
        "Playback Error",
        "",
        "Cause",
        error,
        "",
        "Diagnostics",
        f"Debug log: {path}",
        "The debug log includes the mpv launch command and recent playback errors.",
    ]
    hints = playback_failure_hints(error, recent)
    if hints:
        lines.extend([
            "",
            "Suggested Next Steps",
            *hints,
        ])
    lines.extend([
        "",
        "Recent Debug Log",
    ])
    if recent:
        lines.extend(recent)
    else:
        lines.append("No debug log entries yet.")
    return "\n".join(lines)


def is_unavailable_vod_stream_error(error: str) -> bool:
    return "does not provide a playable stream" in error


def effective_stream_preference_rows(raw: object, config: AppConfig) -> list[tuple[str, str]]:
    audio_choice = preferred_audio_choice(raw, config.preferred_audio_language)
    subtitle_choice = preferred_subtitle_choice(
        raw,
        config.preferred_subtitle_language,
        config.subtitle_mode,
    )
    return [
        ("Playback Mode", playback_mode_value(config)),
        ("Playback Display", playback_display_value(config)),
        ("Terminal Video", terminal_video_profile_value(config)),
        ("Transcode Quality", transcode_quality_value(config)),
        ("Audio", render_audio_playback_preference(config, audio_choice).removeprefix("audio ")),
        ("Subtitles", render_subtitle_playback_preference(config, subtitle_choice).removeprefix("subtitles ")),
    ]


def playback_exit_status(player: PlayerHandle, debug_path: object | None = None) -> str | None:
    returncode = player.process.poll()
    if returncode is None:
        return None
    if returncode == 0:
        return f"Playback ended: {player.title}"
    if returncode < 0:
        return append_debug_log_hint(f"Playback terminated by signal {-returncode}: {player.title}", debug_path)
    return append_debug_log_hint(f"Playback exited with code {returncode}: {player.title}", debug_path)


def append_debug_log_hint(message: str, debug_path: object | None) -> str:
    if debug_path is None:
        return message
    return f"{message}. Debug log: {debug_path}"


def watched_state_action(raw: object) -> tuple[bool, Any | None]:
    target_watched = watched_state(raw) != "watched"
    method_name = "markWatched" if target_watched else "markUnwatched"
    method = getattr(raw, method_name, None)
    return target_watched, method if callable(method) else None


def render_audio_playback_preference(config: AppConfig, audio_choice: StreamChoice | None) -> str:
    preferred = config.preferred_audio_language
    if not preferred:
        return "audio Plex/default"
    if audio_choice is None:
        return f"audio {preferred} not found, Plex/default"
    return f"audio {audio_choice.label}"


def render_subtitle_playback_preference(config: AppConfig, subtitle_choice: StreamChoice | None) -> str:
    if config.subtitle_mode == "none":
        return "subtitles none"
    if config.subtitle_mode != "preferred" or not config.preferred_subtitle_language:
        return "subtitles Plex/default"
    if subtitle_choice is None:
        return f"subtitles {config.preferred_subtitle_language} not found, Plex/default"
    return f"subtitles {subtitle_choice.label}"


def stream_preference_key(choice: StreamChoice) -> str:
    if choice.stream is None:
        return ""
    return stream_language_key(choice.stream) or stream_language_label(choice.stream).lower()


def selected_stream_index(choices: list[StreamChoice], selected_choice: StreamChoice | None) -> int:
    for index, choice in enumerate(choices):
        if stream_choice_matches(choice, selected_choice):
            return index
    return 0


def set_list_index(view: ListView, index: int) -> None:
    view.index = None
    view.index = index
    children = list(view.children)
    if 0 <= index < len(children) and isinstance(children[index], ListItem):
        mark_active_row(view, children[index])
        view.call_after_refresh(mark_active_row, view, children[index])


def mark_active_row(view: ListView, active_row: ListItem) -> None:
    for child in view.children:
        if isinstance(child, ListItem):
            child.set_class(child is active_row, "active-row")


def stream_choice_matches(choice: StreamChoice, selected_choice: StreamChoice | None) -> bool:
    if selected_choice is None:
        return False
    if choice.stream_id != selected_choice.stream_id:
        return False
    if choice.stream is None or selected_choice.stream is None:
        return choice.stream is selected_choice.stream
    return same_stream(choice.stream, selected_choice.stream)


def selected_media_index(items: list[MediaItem], selected_key: str | None) -> int:
    if selected_key is None:
        return 0
    for index, item in enumerate(items):
        if item.key == selected_key:
            return index
    return 0


def write_performance_log(event: str, started: float, detail: str = "") -> None:
    if os.environ.get("PLEX_TUI_PERF_LOG") != "1":
        return
    elapsed_ms = (time.perf_counter() - started) * 1000
    suffix = f" {detail}" if detail else ""
    write_debug_log(f"perf {event} {elapsed_ms:.1f}ms{suffix}")


def write_artwork_performance_log(event: str, started: float, detail: str = "") -> None:
    if os.environ.get("PLEX_TUI_ARTWORK_LOG") != "1":
        return
    write_performance_log(event, started, detail)
