from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from rich.align import Align
from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult, ScreenStackError
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual import events
from textual.message import Message
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static

from . import __version__
from .artwork import artwork_is_cached, fetch_artwork, protocol_renderer_status, render_artwork, render_protocol_artwork
from .auth import LoginSession, ServerChoice, save_server_choice
from .config import (
    DEFAULT_AUTO_LOAD_THRESHOLD,
    DEFAULT_GRID_PREFETCH_PAGES,
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
    same_stream,
    stop_mpv,
    stream_language_key,
    stream_language_label,
    subtitle_choices,
)
from .plex_service import PlexService, media_details, row_progress_marker
GRID_CARD_GAP = 2
GRID_DENSITY_SPECS = {
    "compact": {"width": 18, "content_width": 15, "art_width": 14, "art_height": 7, "height": 10, "max_columns": 6},
    "comfortable": {"width": 22, "content_width": 19, "art_width": 18, "art_height": 9, "height": 12, "max_columns": 5},
    "large": {"width": 28, "content_width": 25, "art_width": 24, "art_height": 12, "height": 15, "max_columns": 4},
}
GRID_DETAIL_REFRESH_DELAY = 0.65
LIST_DETAIL_REFRESH_DELAY = 0.35
DETAIL_ARTWORK_REFRESH_DELAY = 0.55
GRID_PREFETCH_WORKERS = 3
DETAIL_SUMMARY_WIDTH = 38
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

    @property
    def has_more(self) -> bool:
        if self.total is None or self.next_start >= self.total:
            return False
        if self.source == "continue_watching":
            return True
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


class LibraryMenuRow(ListItem):
    def __init__(self, library: LibraryItem, entry: str, label: str, description: str) -> None:
        self.library = library
        self.entry = entry
        self.label_text = label
        self.description = description
        super().__init__(Label(f"› {label}"))


class MediaRow(ListItem):
    def __init__(self, media: MediaItem) -> None:
        marker = "▶" if media.playable else "›"
        subtitle = f" [{media.kind}] {media.subtitle}".rstrip()
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
    ) -> None:
        self.items = items
        self.selected_index = min(max(0, selected_index), max(0, len(items) - 1))
        self.columns = max(1, columns)
        self.rows = max(1, rows)
        self.config = config
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
        self.update(render_media_grid(visible_items, selected_key, self.config, self.columns, self.artwork))
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
        if self.parent is not None:
            self.parent.scroll_to(y=max(0, row * grid_card_height(self.config)), animate=False)

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


class ServerRow(ListItem):
    def __init__(self, choice: ServerChoice) -> None:
        super().__init__(Label(f"{choice.name}  {choice.uri}"))
        self.choice = choice


class StreamRow(ListItem):
    def __init__(self, choice: StreamChoice, stream_type: str, current: bool = False) -> None:
        marker = "* " if current else "  "
        suffix = " (current)" if current else ""
        super().__init__(Label(f"{marker}{choice.label}{suffix}"))
        self.choice = choice
        self.stream_type = stream_type


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


FOCUS_TITLE_PREFIX = "[FOCUS] "


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
        border: solid $accent;
    }

    #sidebar.focused-pane {
        border: heavy $accent;
        background: $boost;
    }

    #main {
        width: 1fr;
        border: solid $primary;
    }

    #main.focused-pane {
        border: heavy $primary;
        background: $boost;
    }

    #details {
        width: 42;
        border: solid $secondary;
    }

    #search {
        margin: 0 1;
    }

    #status {
        height: 1;
        padding: 0 1;
        background: $surface;
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
    }

    .focused-pane > .pane-title {
        background: $accent;
        color: $text;
    }

    #main.focused-pane > .pane-title {
        background: $primary;
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
        Binding("r", "reload", "Reload"),
        Binding("/", "focus_search", "Search"),
        Binding("g", "focus_global_search", "Global"),
        Binding("tab", "focus_next", "Next"),
        Binding("shift+tab", "focus_previous", "Prev"),
        Binding("question_mark", "show_help", "Help"),
        Binding("l", "focus_libraries", "Focus libraries"),
        Binding("m", "focus_media", "Focus media list"),
        Binding("d", "focus_details", "Focus details"),
        Binding("v", "toggle_media_view", "View"),
        Binding("left", "grid_left", "Left"),
        Binding("right", "grid_right", "Right"),
        Binding("comma", "show_settings", "Settings"),
        Binding("escape", "back_or_clear", "Back"),
        Binding("p", "play_selected", "Play"),
        Binding("a", "audio_picker", "Audio"),
        Binding("s", "subtitle_picker", "Subtitles"),
        Binding("A", "clear_audio_preference", "Clear audio"),
        Binding("S", "cycle_subtitle_mode", "Sub mode"),
        Binding("x", "stop_playback", "Stop"),
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
    help_visible: bool
    settings_visible: bool
    picker_visible: bool
    selected_subtitle: StreamChoice | None
    selected_audio: StreamChoice | None
    picker_media_key: str | None
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
                yield Input(placeholder="Search current library", id="search")
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
        self.help_visible = False
        self.settings_visible = False
        self.picker_visible = False
        self.selected_subtitle = None
        self.selected_audio = None
        self.picker_media_key = None
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
            if visible:
                self.populate_libraries(visible, selected_library_key=visible[0].key)
                self.open_library_entry(visible[0])
            else:
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
            for choice in choices:
                view.append(ServerRow(choice))
            view.focus()
            self.show_detail_text("Choose the connection you want this app to use.")
            self.set_status("Select a Plex server connection and press Enter")

        self.call_from_thread(show_choices)

    def populate_libraries(self, libraries: list[LibraryItem], selected_library_key: str | None = None) -> None:
        selected_index = 0
        if selected_library_key is not None:
            for index, library in enumerate(libraries, start=1):
                if library.key == selected_library_key:
                    selected_index = index
                    break
        self.replace_list_rows_async(
            "#libraries",
            [ContinueWatchingRow(), *[LibraryRow(library) for library in libraries]],
            selected_index,
            "library-list",
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        row = event.item
        if isinstance(row, ContinueWatchingRow):
            self.open_continue_watching()
        elif isinstance(row, LibraryRow):
            self.open_library_menu(row.library)
        elif isinstance(row, LibraryMenuRow):
            self.open_library_entry(row.library, row.entry, row.label_text)
        elif isinstance(row, MediaRow):
            self.open_media(row.media)
        elif isinstance(row, LoadMoreRow):
            self.load_more_media()
        elif isinstance(row, ServerRow):
            self.choose_server(row.choice)
        elif isinstance(row, StreamRow):
            self.choose_stream(row.choice, row.stream_type)
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
            self.set_status(context_hint(row))
            self.maybe_auto_load_more(row.media)
        elif isinstance(row, LoadMoreRow):
            mark_active_row(event.list_view, row)
            self.show_detail_text("Load the next page of items.")
            self.set_status(context_hint(row))
        elif isinstance(row, ServerRow):
            mark_active_row(event.list_view, row)
            self.show_detail_text(f"{row.choice.name}\n\n{row.choice.uri}\n\nSource: {row.choice.source}")
            self.set_status(context_hint(row))
        elif isinstance(row, StreamRow):
            mark_active_row(event.list_view, row)
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

    def open_library_menu(self, library: LibraryItem) -> None:
        self.selected_library = library
        self.browsing_stack = []
        self.set_media_title(library.title)
        self.show_media_list()
        self.replace_media_rows(library_menu_rows(library), 0)
        self.show_detail_text(library_menu_description(library))
        self.focus_media_browser()
        self.set_status(f"{library.title}: choose a browse mode")

    @work(thread=True)
    def open_library_entry(self, library: LibraryItem, entry: str = "library", label: str | None = None) -> None:
        if self.service is None:
            return
        title = library.title if entry == "library" else f"{library.title}: {label or library_entry_label(entry)}"
        self.post_message(StatusChanged(f"Loading {title}..."))
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
            self.set_status(render_loaded_status(title, len(page.items), page.total, page.has_more))

        self.call_from_thread(update)

    @work(thread=True)
    def open_continue_watching(self) -> None:
        if self.service is None:
            return
        title = "Continue Watching"
        self.post_message(StatusChanged(f"Loading {title}..."))
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
            self.set_status(render_loaded_status(title, len(page.items), page.total, page.has_more))

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
    def load_more_media(self, selected_key: str | None = None) -> None:
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
            if state.search:
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
            self.show_browse_state(state, selected_key=selected_key or first_new_key)
            self.focus_media_browser()
            self.set_status(render_loaded_status(state.title, len(state.items), state.total, state.has_more))

        self.call_from_thread(update)

    @work(thread=True)
    def open_media(self, media: MediaItem) -> None:
        if self.service is None:
            return
        if media.playable:
            self.call_from_thread(self.set_status, f"Selected {media.title}. Press p to play.")
            return
        self.post_message(StatusChanged(f"Opening {media.title}..."))
        try:
            children = self.service.children(media)
        except Exception as exc:
            self.call_from_thread(self.show_error, str(exc))
            return

        def update() -> None:
            if not children:
                self.set_status(f"No child items for {media.title}")
                return
            state = BrowseState(media.title, children, self.selected_library)
            self.browsing_stack.append(state)
            self.show_browse_state(state)
            self.focus_media_browser()
            self.set_status(f"{media.title}: {len(children)} items")

        self.call_from_thread(update)

    def show_media(self, title: str, items: list[MediaItem], selected_key: str | None = None) -> None:
        self.set_media_title(title)
        state = BrowseState(title, items)
        self.show_browse_state(state, selected_key=selected_key)

    def show_browse_state(self, state: BrowseState, selected_key: str | None = None) -> None:
        self.set_media_title(state.title)
        if state.items:
            started = time.perf_counter()
            selected_index = selected_media_index(state.items, selected_key)
            if self.config.media_view == "grid":
                grid = self.show_media_grid()
                columns, rows = self.media_grid_geometry()
                grid.set_items(state.items, selected_index, self.config, columns, rows)
                self.schedule_grid_prefetch(grid)
            else:
                self.show_media_list()
                rows, selected_row_index = media_rows(state.items, self.config, selected_index)
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
            self.show_media_list()
            self.replace_media_rows([])
            self.show_detail_text("No items")

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
        self.show_detail_text(render_detail_content(details, self.config, raw=item.raw))
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
            self.show_detail_text(render_detail_content(details, self.config, raw=full_item.raw))
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
                detail_fetch_started = time.perf_counter()
                data = fetch_artwork(full_item.raw, artwork_path, self.config, width=width, height=height * 2)
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
                    card_width, card_height = card_artwork_pixel_size(self.config)
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

    def media_grid_geometry(self) -> tuple[int, int]:
        media_size = self.query_one("#main").size
        return grid_geometry_for_size(media_size.width, media_size.height, self.config)

    def action_focus_search(self) -> None:
        self.search_global = False
        self.input_mode = "search"
        search = self.query_one("#search", Input)
        search.placeholder = "Search current library"
        search.value = ""
        search.display = True
        search.focus()
        self.set_focus_pane(main=True)

    def action_focus_global_search(self) -> None:
        self.search_global = True
        self.input_mode = "search"
        search = self.query_one("#search", Input)
        search.placeholder = "Search all libraries"
        search.value = ""
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
            self.action_show_settings()
            self.set_status(f"Media view: {media_view_value(self.config)}")
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
            width, height = card_artwork_pixel_size(self.config)
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
        if action.startswith("toggle_library_visibility:"):
            self.toggle_library_visibility(action.removeprefix("toggle_library_visibility:"))
            return
        if action == "cycle_grid_density":
            next_density = next_grid_density(self.config.grid_density)
            if self.update_preferences(grid_density=next_density):
                self.refresh_settings_after_change(action, "Grid density", grid_density_value(self.config))
            return
        if action == "cycle_mpv_window_size":
            self.action_cycle_mpv_window_size()
            return
        if action == "set_mpv_window_size":
            self.prompt_mpv_window_size()
            return
        if action == "reset_mpv_window_size":
            if self.update_preferences(mpv_window_size=""):
                self.refresh_settings_after_change(action, "mpv window size", "Default")
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
                self.action_show_settings()
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
        if stream_type == "subtitle":
            self.selected_subtitle = None
            self.set_status(f"Subtitle preference: {choice.label}")
        elif stream_type == "audio":
            self.selected_audio = None
            self.set_status(f"Audio preference: {choice.label}")
        self.picker_visible = False
        if self.browsing_stack:
            state = self.browsing_stack[-1]
            self.show_browse_state(state, selected_key=self.picker_media_key)
        self.picker_media_key = None
        self.focus_media_browser()

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
        search.placeholder = 'mpv window size: 1280x720, 80%, 80%x80%, or empty for default'
        search.value = self.config.mpv_window_size
        search.display = True
        search.focus()
        self.show_detail_text("Enter an mpv --autofit value. Examples: 1280x720, 80%, 80%x80%. Submit empty to reset to Default.")
        self.set_status("Enter custom mpv window size")

    def save_mpv_window_size_input(self, value: str) -> None:
        size = value.strip()
        if size and not valid_mpv_window_size(size):
            self.prompt_mpv_window_size()
            self.set_status("Invalid mpv window size. Use 1280x720, 80%, or 80%x80%.")
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
            self.input_mode = ""
            self.run_search(query, self.search_global)

    @work(thread=True)
    def run_search(self, query: str, global_search: bool = False) -> None:
        if self.service is None or not query:
            return
        scope = "all libraries" if global_search else "current library"
        self.post_message(StatusChanged(f"Searching {scope} for {query}..."))
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
            title = f"Global search: {query}" if global_search else f"Search: {query}"
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
            self.set_status(render_loaded_status(title, len(page.items), page.total, page.has_more))

        self.call_from_thread(update)

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
            if self.browsing_stack:
                state = self.browsing_stack[-1]
                self.show_browse_state(state)
            self.focus_media_browser()
            return

        if self.help_visible or self.settings_visible or self.picker_visible:
            self.help_visible = False
            self.settings_visible = False
            self.picker_visible = False
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
        media = self.selected_media()
        if media is None:
            self.set_status("No media selected")
            return
        if not media.playable:
            self.set_status("Selected item is not directly playable")
            return
        subtitle_choice = preferred_subtitle_choice(
            media.raw,
            self.config.preferred_subtitle_language,
            self.config.subtitle_mode,
        )
        audio_choice = preferred_audio_choice(media.raw, self.config.preferred_audio_language)
        try:
            stop_mpv(self.player)
            self.player = play_with_mpv(
                media.raw,
                subtitle_choice=subtitle_choice,
                audio_choice=audio_choice,
                window_size=self.config.mpv_window_size,
            )
        except PlayerError as exc:
            self.clear_playback_footer()
            self.show_playback_error(str(exc))
            return
        self.detail_refresh_token += 1
        self.cancel_media_detail_refresh()
        self.show_detail_text(
            render_playback_details(media.title, self.player, self.config, audio_choice, subtitle_choice)
        )
        status = render_playback_status(media.title, self.player, self.config, audio_choice, subtitle_choice)
        self.set_status(status)
        self.set_playback_footer(status)

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
        self.set_status(f"Error: {text}")
        self.set_media_title("Error")
        view = self.show_media_list()
        view.clear()
        view.append(ListItem(Label(f"{text}\n{config_hint}")))
        self.show_detail_text(config_hint)

    def show_playback_error(self, text: str) -> None:
        self.detail_refresh_token += 1
        self.cancel_media_detail_refresh()
        path = debug_log_path()
        self.set_status(f"Playback error: {text}. Debug log: {path}")
        self.set_media_title("Playback Error")
        view = self.show_media_list()
        view.clear()
        view.append(ListItem(Label(f"{text}\nDebug log: {path}")))
        self.show_detail_text(render_playback_error_details(text, path))


def format_offset(milliseconds: int) -> str:
    seconds = max(0, milliseconds // 1000)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def render_details(details: object, config: AppConfig | None = None, raw: object | None = None) -> str:
    lines = render_detail_header(details, config)

    metadata = [*detail_key_value_rows(getattr(details, "metadata"))]
    append_detail_section(lines, "Metadata", metadata or ["No metadata reported"])

    if config is not None:
        append_detail_section(
            lines,
            "Preferences",
            detail_key_value_rows([
                ("Audio", preference_value(config.preferred_audio_language)),
                ("Subtitles", f"{subtitle_mode_value(config)} / {subtitle_language_value(config)}"),
            ]),
        )
        if raw is not None:
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


def render_detail_header(details: object, config: AppConfig | None = None) -> list[str]:
    title = getattr(details, "title")
    title_lines = textwrap.wrap(title, width=DETAIL_SUMMARY_WIDTH) or [title]
    facts = [str(fact) for fact in getattr(details, "facts", []) if fact]
    artwork = artwork_status(details, config)
    title_width = max(len(line) for line in title_lines)
    lines = [*title_lines, "-" * min(max(title_width, 8), DETAIL_SUMMARY_WIDTH)]
    if facts:
        lines.extend(textwrap.wrap(" / ".join(facts), width=DETAIL_SUMMARY_WIDTH) or [""])
    lines.extend([
        "",
        "Playback",
        *playback_readiness_rows(bool(getattr(details, "playable"))),
        f"Artwork: {artwork}",
    ])
    return lines


def playback_readiness_rows(playable: bool) -> list[str]:
    if playable:
        return [
            "Status: Ready to play",
            "Action: Press p to play",
        ]
    return [
        "Status: Opens more items",
        "Action: Press Enter to open",
    ]


def append_detail_section(lines: list[str], heading: str, body: list[str]) -> None:
    if lines and lines[-1] != "":
        lines.append("")
    lines.append(heading)
    lines.extend(body)


def detail_key_value_rows(values: list[tuple[str, str]]) -> list[str]:
    rows: list[str] = []
    for label, value in values:
        rows.extend(wrapped_detail_text(f"{label}: {value}"))
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
) -> object:
    text = render_details(details, config, raw)
    if artwork is None:
        return text
    return Group(artwork, Text(""), text)


def media_rows(
    items: list[MediaItem],
    config: AppConfig,
    selected_index: int,
) -> tuple[list[ListItem], int]:
    return [media_row(item, config) for item in items], selected_index


def media_row(item: MediaItem, config: AppConfig) -> MediaRow:
    return MediaRow(item)


def render_media_grid(
    items: list[MediaItem],
    selected_key: str,
    config: AppConfig,
    columns: int,
    artwork_overrides: dict[str, object] | None = None,
) -> object:
    rows = []
    for start in range(0, len(items), columns):
        chunk = items[start:start + columns]
        cards = [
            render_media_grid_card(item, item.key == selected_key, config, artwork_overrides)
            for item in chunk
        ]
        row = Table.grid(padding=(0, 1))
        for _ in cards:
            row.add_column(width=grid_card_width(config), no_wrap=True)
        row.add_row(*cards)
        rows.append(Align.center(row))
    return Group(*rows)


def render_media_grid_card(
    media: MediaItem,
    selected: bool,
    config: AppConfig,
    artwork_overrides: dict[str, object] | None = None,
) -> object:
    title_style = "bold #e5a00d" if selected else "bold"
    card_width = grid_card_width(config)
    title = grid_card_text(media.title, config)
    subtitle = grid_card_text("  ".join(bit for bit in (media.kind, media.subtitle) if bit), config)
    artwork = artwork_overrides.get(media.key) if artwork_overrides is not None else None
    artwork = copy_renderable(artwork)
    if artwork is None:
        artwork = grid_artwork_placeholder(grid_artwork_placeholder_label(media), config)
    else:
        artwork = center_renderable_lines(artwork, card_width)
    footer = grid_card_footer(media, selected)
    return Group(
        artwork,
        grid_card_line(title, card_width, title_style),
        grid_card_line(subtitle, card_width, "dim"),
        grid_card_line(footer, card_width, "#e5a00d" if selected else "dim"),
    )


def grid_artwork_placeholder(status: str, config: AppConfig) -> Group:
    spec = grid_density_spec(config)
    width = grid_card_width(config)
    height = int(spec["art_height"])
    label = truncate_text(f"[{status}]", grid_card_content_width(config))
    blank = " " * width
    lines = []
    midpoint = height // 2
    for index in range(height):
        lines.append(grid_card_line(label, width, "dim") if index == midpoint else Text(blank, style="dim"))
    return Group(*lines)


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


def grid_card_text(value: str, config: AppConfig) -> str:
    return truncate_text(value.strip(), grid_card_content_width(config))


def grid_card_footer(media: MediaItem, selected: bool) -> str:
    if selected:
        return "▶ selected"
    if media.playable:
        return "playable"
    return "open"


def grid_card_line(value: str, width: int, style: str) -> Text:
    return Text(value.center(width), style=style)


def center_renderable_lines(renderable: object, width: int) -> object:
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
    artwork = render_artwork(data, width=int(spec["art_width"]), max_height=int(spec["art_height"]))
    return Group(*artwork.split("\n"))


def card_artwork_pixel_size(config: AppConfig) -> tuple[int, int]:
    spec = grid_density_spec(config)
    return int(spec["art_width"]), int(spec["art_height"]) * 2


def grid_artwork_cache_key(item: MediaItem, config: AppConfig) -> tuple[str, str]:
    return item.artwork_path, config.grid_density


def grid_density_spec(config: AppConfig | None) -> dict[str, int]:
    density = getattr(config, "grid_density", "comfortable")
    return GRID_DENSITY_SPECS.get(density, GRID_DENSITY_SPECS["comfortable"])


def grid_card_width(config: AppConfig | None) -> int:
    return int(grid_density_spec(config)["width"])


def grid_card_content_width(config: AppConfig | None) -> int:
    return int(grid_density_spec(config)["content_width"])


def grid_card_render_width(config: AppConfig | None) -> int:
    return grid_card_width(config) + GRID_CARD_GAP


def grid_card_height(config: AppConfig | None) -> int:
    return int(grid_density_spec(config)["height"])


def grid_geometry_for_size(width: int, height: int, config: AppConfig | None) -> tuple[int, int]:
    spec = grid_density_spec(config)
    columns = max(1, min(int(spec["max_columns"]), max(1, width - 4) // grid_card_render_width(config)))
    rows = max(1, min(4, max(1, height - 2) // grid_card_height(config)))
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
    return [library for library in libraries if library.key not in hidden]


def library_by_key(libraries: list[LibraryItem], key: str) -> LibraryItem | None:
    for library in libraries:
        if library.key == key:
            return library
    return None


def library_visibility_row(library: LibraryItem, config: AppConfig) -> SettingsActionRow:
    state = "Hidden" if library.key in config.hidden_library_keys else "Visible"
    return SettingsActionRow(
        f"{library.title}: {state}",
        f"toggle_library_visibility:{library.key}",
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
        SettingsActionRow("Reconnect / reload libraries", "reload"),
        SettingsActionRow("Relogin with Plex", "relogin"),
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
        SettingsActionRow(f"mpv Window Size: {mpv_window_size_value(config)}", "set_mpv_window_size"),
        SettingsHeaderRow("Artwork"),
        SettingsActionRow(f"Artwork: {artwork_mode_value(config)}", "toggle_artwork"),
        SettingsActionRow(f"Details Artwork: {detail_artwork_mode_value(config)}", "cycle_detail_artwork"),
        SettingsActionRow(f"Artwork Renderer: {artwork_renderer_value(config)}", "cycle_artwork_renderer"),
        SettingsHeaderRow("Browsing"),
        SettingsActionRow(f"Media View: {media_view_value(config)}", "toggle_media_view"),
        SettingsActionRow(f"Grid Density: {grid_density_value(config)}", "cycle_grid_density"),
        numeric_settings_row(config, "page_size"),
        numeric_settings_row(config, "auto_load_threshold"),
        numeric_settings_row(config, "grid_prefetch_pages"),
    ]
    if libraries:
        rows.append(SettingsHeaderRow("Library Visibility"))
        rows.extend(library_visibility_row(library, config) for library in libraries)
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
    lines = [
        "Settings",
        "",
        "Account",
        f"Server: {config.base_url or 'not set'}",
        f"Server Token: {'saved' if config.token else 'not set'}",
        f"Account Token: {'saved' if config.account_token else 'not set'}",
        "Reconnect / reload libraries",
        "Relogin with Plex",
        "",
        "Streams",
        f"Audio Preference: {preference_value(config.preferred_audio_language)}",
        f"Subtitle Mode: {subtitle_mode_value(config)}",
        f"Subtitle Language: {subtitle_language_value(config)}",
        "Clear audio preference",
        "Set subtitles to Auto",
        "Set subtitles to None",
        "Clear subtitle preference",
        "Clear audio/subtitle preferences",
        "",
        "Playback",
        f"mpv Window Size: {mpv_window_size_value(config)}",
        "Set custom mpv window size with values like 1280x720, 80%, or 80%x80%.",
        "",
        "Artwork",
        f"Artwork: {artwork_mode_value(config)}",
        f"Details Artwork: {detail_artwork_mode_value(config)}",
        f"Artwork Renderer: {artwork_renderer_value(config)}",
        "",
        "Browsing",
        f"Media View: {media_view_value(config)}",
        f"Grid Density: {grid_density_value(config)}",
        f"Page Size: {config.page_size}",
        f"Auto-load Threshold: {config.auto_load_threshold}",
        f"Grid Prefetch Pages: {config.grid_prefetch_pages}",
        f"Hidden Libraries: {hidden_library_count_value(config)}",
        "Set custom browsing values with whole numbers inside the allowed range.",
        "",
        "Diagnostics",
        f"Config Path: {config_path()}",
        f"Cache Path: {cache_path()}",
        f"Debug Log: {debug_log_path()}",
        f"Client ID: {config.client_identifier or 'not set'}",
        f"Theme: {config.theme}",
        "Show recent debug log",
        "Show app diagnostics",
    ]
    return "\n".join(lines)


def render_help() -> str:
    return "\n".join([
        "Navigation",
        "enter: open selected row",
        "escape: go back / close current view",
        "tab / shift+tab: move focus",
        "l: focus libraries",
        "m: focus media list",
        "d: focus details",
        "v: toggle list/grid view",
        "left/right: move across grid cards",
        "pageup/pagedown: move one grid page",
        "",
        "Search",
        "/: search current library",
        "g: search all libraries",
        "",
        "Playback",
        "p: play selected media with mpv",
        "x: stop launched mpv",
        "",
        "Streams",
        "a: choose and save audio preference",
        "s: choose and save subtitle preference",
        "A: clear audio preference",
        "S: cycle subtitle mode",
        "",
        "Settings",
        ",: show settings",
        "r: reconnect / reload libraries",
        "PLEX_TUI_PERF_LOG=1: write browsing timings to the debug log",
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
)


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


def library_menu_description(library: LibraryItem) -> str:
    return "\n".join([
        library.title,
        "",
        "Choose how to browse this Plex library.",
        "",
        "Library: all items.",
        "Recommended: Plex hub rows.",
        "Collections: library collections.",
        "Playlists: library playlists.",
    ])


def context_hint(row: object) -> str:
    if isinstance(row, ContinueWatchingRow):
        return "Libraries: Enter opens Continue Watching"
    if isinstance(row, LibraryRow):
        return "Libraries: Enter opens library / Escape shows browse modes"
    if isinstance(row, LibraryMenuRow):
        return "Library: Enter opens browse mode"
    if isinstance(row, LoadMoreRow):
        return "Media: Enter loads next page"
    if isinstance(row, MediaRow):
        if row.media.playable:
            return "Media: Enter selects / p plays / a audio / s subtitles"
        return "Media: Enter opens item"
    if isinstance(row, MediaGrid):
        media = row.selected_media
        if media is not None and media.playable:
            return "Grid: Arrows/page select card / p plays / a audio / s subtitles"
        return "Grid: Arrows/page select card / Enter opens item"
    if isinstance(row, ServerRow):
        return "Servers: Enter selects server"
    if isinstance(row, StreamRow):
        return "Streams: Enter saves preference"
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


def settings_action_kind(action: str) -> str:
    if confirmation_required(action):
        return "confirm"
    if action.startswith("set_"):
        return "input"
    if action.startswith(("increase_", "decrease_")):
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
    if action == "toggle_artwork":
        return f"Current artwork: {artwork_mode_value(config)}"
    if action == "cycle_detail_artwork":
        return f"Current details artwork: {detail_artwork_mode_value(config)}"
    if action.startswith("artwork_renderer_") or action == "cycle_artwork_renderer":
        return f"Current artwork renderer: {artwork_renderer_value(config)}"
    if action == "toggle_media_view":
        return f"Current media view: {media_view_value(config)}"
    if action == "cycle_grid_density":
        return f"Current grid density: {grid_density_value(config)}"
    if action.startswith("toggle_library_visibility:"):
        key = action.removeprefix("toggle_library_visibility:")
        state = "Hidden" if key in config.hidden_library_keys else "Visible"
        return f"Current library visibility: {state}"
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
    if action == "subtitle_auto":
        return "Press Enter to let Plex or saved language preference choose subtitles."
    if action == "subtitle_none":
        return "Press Enter to disable subtitles by default."
    if action == "cycle_subtitle_mode":
        return "Press Enter to cycle subtitle mode. Use subtitle picker to save a preferred language."
    if action == "cycle_mpv_window_size":
        return "Press Enter to cycle through default window-size presets."
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
    if action == "cycle_grid_density":
        return "Press Enter to cycle compact, comfortable, and large grid layouts."
    if action.startswith("toggle_library_visibility:"):
        return "Press Enter to show or hide this library in the sidebar."
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
        "subtitle_auto": "Set subtitles to Auto",
        "subtitle_none": "Set subtitles to None",
        "cycle_subtitle_mode": "Subtitle Mode",
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


def render_loaded_status(title: str, loaded: int, total: int | None, has_more: bool) -> str:
    if total is None:
        return f"{title}: {loaded} items"
    if has_more:
        return f"{title}: {loaded} of {total} items loaded"
    return f"{title}: {loaded} items"


def grid_status(grid: MediaGrid, state: BrowseState | None) -> str:
    total_loaded = len(grid.items)
    total_available = state.total if state is not None else None
    page_count = max(1, (total_loaded + grid.page_size - 1) // grid.page_size)
    current_page = min(page_count, (grid.selected_index // grid.page_size) + 1)
    selected = min(grid.selected_index + 1, total_loaded)
    total_text = f"{total_loaded} loaded" if total_available is None else f"{total_loaded} of {total_available} loaded"
    return f"{context_hint(grid)} / item {selected} / page {current_page} of {page_count} / {total_text}"


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
    return config.mpv_window_size or "Default"


def next_mpv_window_size(value: str) -> str:
    sizes = ["", "1280x720", "1600x900", "1920x1080", "80%"]
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
    if player.subtitle_count:
        details.append(f"{player.subtitle_count} subtitles")
    details.append(render_playback_preferences(config, audio_choice, subtitle_choice))
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
        f"Resume: {format_offset(player.start_offset_ms) if player.start_offset_ms else 'start'}",
        f"Subtitles available: {player.subtitle_count}",
        f"mpv window: {mpv_window_size_value(config)}",
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


def effective_stream_preference_rows(raw: object, config: AppConfig) -> list[tuple[str, str]]:
    audio_choice = preferred_audio_choice(raw, config.preferred_audio_language)
    subtitle_choice = preferred_subtitle_choice(
        raw,
        config.preferred_subtitle_language,
        config.subtitle_mode,
    )
    return [
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
