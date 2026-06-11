from __future__ import annotations

import os
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static

from .artwork import artwork_is_cached, fetch_artwork, render_artwork, render_protocol_artwork
from .auth import LoginSession, ServerChoice, save_server_choice
from .config import (
    DEFAULT_AUTO_LOAD_THRESHOLD,
    DEFAULT_PAGE_SIZE,
    MAX_AUTO_LOAD_THRESHOLD,
    MAX_PAGE_SIZE,
    MIN_AUTO_LOAD_THRESHOLD,
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
    "compact": {"width": 19, "content_width": 16, "art_width": 14, "art_height": 7, "height": 10, "max_columns": 6},
    "comfortable": {"width": 23, "content_width": 20, "art_width": 18, "art_height": 9, "height": 12, "max_columns": 5},
    "large": {"width": 29, "content_width": 26, "art_width": 24, "art_height": 12, "height": 15, "max_columns": 4},
}


@dataclass
class BrowseState:
    title: str
    items: list[MediaItem]
    selected_library: LibraryItem | None = None
    search: bool = False
    search_query: str = ""
    global_search: bool = False
    next_start: int = 0
    total: int | None = None

    @property
    def has_more(self) -> bool:
        if self.total is None or self.next_start >= self.total:
            return False
        if self.search:
            return bool(self.search_query and self.selected_library is not None and not self.global_search)
        return self.selected_library is not None


class LibraryRow(ListItem):
    def __init__(self, library: LibraryItem) -> None:
        super().__init__(Label(library.title))
        self.library = library


class MediaRow(ListItem):
    def __init__(self, media: MediaItem) -> None:
        marker = ">" if not media.playable else " "
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
        started = time.perf_counter()
        self.update(render_media_grid(self.visible_page_items(), selected_key, self.config, self.columns, self.artwork))
        write_performance_log("grid_render", started, f"items={len(self.visible_page_items())} columns={self.columns}")

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
        self.label_text = label
        super().__init__(Label(label))
        self.action = action


class SettingsHeaderRow(ListItem):
    def __init__(self, label: str) -> None:
        self.label_text = f"[ {label} ]"
        super().__init__(Label(self.label_text))


class SettingsValueRow(ListItem):
    def __init__(self, label: str) -> None:
        self.label_text = label
        super().__init__(Label(label))


class StatusChanged(Message):
    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()


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

    #main {
        width: 1fr;
        border: solid $primary;
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

    .pane-title {
        text-style: bold;
        padding: 0 1;
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
    applying_config_theme: bool
    detail_refresh_token: int
    grid_prefetch_token: int

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("Libraries", classes="pane-title")
                yield ListView(id="libraries")
            with Vertical(id="main"):
                yield Static("Media", id="media-title", classes="pane-title")
                yield Input(placeholder="Search current library", id="search")
                yield ListView(id="media")
                with VerticalScroll(id="media-grid-scroll"):
                    yield MediaGrid()
            with Vertical(id="details"):
                yield Static("Details", classes="pane-title")
                with VerticalScroll(id="detail-scroll"):
                    yield Static("Select an item", id="detail-content")
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
        self.applying_config_theme = False
        self.detail_refresh_token = 0
        self.grid_prefetch_token = 0
        try:
            self.config = load_config()
            self.apply_config_theme()
        except Exception:
            pass
        self.query_one("#search", Input).display = False
        self.query_one("#media-grid-scroll", VerticalScroll).display = False
        self.set_interval(1.0, self.check_player_status)
        self.load_server()

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
            self.apply_config_theme()
            self.title = f"plex-tui - {service.friendly_name}"
            self.set_status(f"Connected to {service.friendly_name}")
            self.populate_libraries(libraries)
            if libraries:
                self.open_library(libraries[0])

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
            self.query_one("#media-title", Static).update("Plex Login")
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
            self.query_one("#media-title", Static).update("Select Server")
            view = self.show_media_list()
            view.clear()
            for choice in choices:
                view.append(ServerRow(choice))
            view.focus()
            self.show_detail_text("Choose the connection you want this app to use.")
            self.set_status("Select a Plex server connection and press Enter")

        self.call_from_thread(show_choices)

    def populate_libraries(self, libraries: list[LibraryItem]) -> None:
        self.replace_list_rows_async(
            "#libraries",
            [LibraryRow(library) for library in libraries],
            0 if libraries else None,
            "library-list",
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        row = event.item
        if isinstance(row, LibraryRow):
            self.open_library(row.library)
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
        if isinstance(row, LibraryRow):
            mark_active_row(event.list_view, row)
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
        elif isinstance(row, StreamRow) or isinstance(row, (SettingsActionRow, SettingsHeaderRow, SettingsValueRow)):
            mark_active_row(event.list_view, row)
            self.set_status(context_hint(row))
        elif row is None and not list(event.list_view.children):
            self.show_detail_text("Select an item")

    def on_media_grid_highlighted(self, event: MediaGrid.Highlighted) -> None:
        self.show_media_details(event.media)
        if isinstance(event.control, MediaGrid):
            self.schedule_grid_prefetch(event.control)
            self.set_status(grid_status(event.control, self.browsing_stack[-1] if self.browsing_stack else None))
        self.maybe_auto_load_more(event.media)

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
    def open_library(self, library: LibraryItem) -> None:
        if self.service is None:
            return
        self.post_message(StatusChanged(f"Loading {library.title}..."))
        started = time.perf_counter()
        try:
            page = self.service.library_page(library, 0, self.config.page_size)
        except Exception as exc:
            self.call_from_thread(self.show_error, str(exc))
            return
        write_performance_log(
            "library_page",
            started,
            f"title={library.title!r} start=0 size={self.config.page_size} items={len(page.items)} total={page.total}",
        )

        def update() -> None:
            self.selected_library = library
            state = BrowseState(
                library.title,
                page.items,
                library,
                next_start=page.next_start,
                total=page.total,
            )
            self.browsing_stack = [state]
            self.show_browse_state(state)
            self.focus_media_browser()
            self.set_status(render_loaded_status(library.title, len(page.items), page.total, page.has_more))

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
            return
        self.query_one("#media", ListView).focus()

    def media_grid_visible(self) -> bool:
        return bool(self.query_one("#media-grid-scroll", VerticalScroll).display)

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
        self.query_one("#media-title", Static).update(title)
        state = BrowseState(title, items)
        self.show_browse_state(state, selected_key=selected_key)

    def show_browse_state(self, state: BrowseState, selected_key: str | None = None) -> None:
        self.query_one("#media-title", Static).update(state.title)
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
        delay = 0.35 if self.media_grid_visible() else 0.0
        self.refresh_media_details(item, token, delay)

    @work(thread=True, exclusive=True)
    def refresh_media_details(self, item: MediaItem, token: int, delay: float = 0.0) -> None:
        started = time.perf_counter()
        if delay:
            time.sleep(delay)
        if token != self.detail_refresh_token:
            write_performance_log("detail_refresh_skipped", started, f"title={item.title!r} reason=stale")
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
        write_performance_log("detail_reload", started, f"title={item.title!r}")

        details = media_details(full_item)

        def update_text() -> None:
            if token != self.detail_refresh_token:
                return
            selected = self.selected_media()
            if selected is not None and selected.key == item.key:
                self.show_detail_text(render_detail_content(details, self.config, raw=full_item.raw))

        self.call_from_thread(update_text)

        artwork = None
        card_artwork = None
        if artwork_enabled(self.config) and details.artwork_path:
            artwork_started = time.perf_counter()
            try:
                data = fetch_artwork(full_item.raw, details.artwork_path, self.config)
                if detail_artwork_enabled(self.config):
                    width, height = self.detail_artwork_size()
                    artwork = (
                        render_protocol_artwork(data, self.config.artwork_renderer, width=width, max_height=height)
                        or render_artwork(data, width=width, max_height=height)
                    )
                card_artwork = render_card_artwork(data, self.config)
            except Exception:
                artwork = None
            write_performance_log("detail_artwork", artwork_started, f"title={item.title!r} path={details.artwork_path!r}")
        if not artwork and not card_artwork:
            return

        def update_artwork() -> None:
            if token != self.detail_refresh_token:
                return
            selected = self.selected_media()
            if selected is not None and selected.key == item.key:
                if artwork is not None:
                    self.show_detail_text(render_detail_content(details, self.config, artwork, raw=full_item.raw))
                grid = self.query_one("#media-grid", MediaGrid)
                if self.media_grid_visible() and card_artwork is not None:
                    grid.set_artwork(item.key, card_artwork)

        self.call_from_thread(update_artwork)

    def show_detail_text(self, content: Any) -> None:
        self.query_one("#detail-content", Static).update(content)
        self.query_one("#detail-scroll", VerticalScroll).scroll_home(animate=False)

    def detail_artwork_size(self) -> tuple[int, int]:
        pane_width = self.query_one("#details").size.width
        width = min(36, max(14, pane_width - 6))
        return width, 22

    def media_grid_geometry(self) -> tuple[int, int]:
        media_size = self.query_one("#main").size
        spec = grid_density_spec(self.config)
        columns = max(1, min(int(spec["max_columns"]), max(1, media_size.width - 4) // grid_card_render_width(self.config)))
        rows = max(1, min(4, max(1, media_size.height - 2) // grid_card_height(self.config)))
        return columns, rows

    def action_focus_search(self) -> None:
        self.search_global = False
        self.input_mode = "search"
        search = self.query_one("#search", Input)
        search.placeholder = "Search current library"
        search.value = ""
        search.display = True
        search.focus()

    def action_focus_global_search(self) -> None:
        self.search_global = True
        self.input_mode = "search"
        search = self.query_one("#search", Input)
        search.placeholder = "Search all libraries"
        search.value = ""
        search.display = True
        search.focus()

    def action_focus_libraries(self) -> None:
        self.query_one("#libraries", ListView).focus()
        self.set_status("Focus moved to libraries")

    def action_focus_media(self) -> None:
        self.focus_media_browser()
        self.set_status("Focus moved to media list")

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
        self.set_status(f"Media view: {media_view_value(self.config)}")

    def action_grid_left(self) -> None:
        self.move_grid_selection(-1)

    def action_grid_right(self) -> None:
        self.move_grid_selection(1)

    def move_grid_selection(self, direction: int) -> None:
        grid = self.query_one("#media-grid", MediaGrid)
        if self.media_grid_visible():
            grid.move_selection(direction)

    def schedule_grid_prefetch(self, grid: MediaGrid) -> None:
        if not artwork_enabled(self.config):
            return
        self.grid_prefetch_token += 1
        token = self.grid_prefetch_token
        self.prefetch_grid_items(grid.visible_page_items(), token, "current")
        next_items = grid.visible_page_items(page_offset=1)
        if next_items:
            self.prefetch_grid_items(next_items, token, "next", delay=0.5)

    @work(thread=True)
    def prefetch_grid_items(
        self,
        items: list[MediaItem],
        token: int,
        page_label: str,
        delay: float = 0.0,
    ) -> None:
        if not artwork_enabled(self.config):
            return
        started = time.perf_counter()
        if delay:
            time.sleep(delay)
        if token != self.grid_prefetch_token:
            write_performance_log("grid_prefetch_skipped", started, f"page={page_label} reason=stale")
            return
        page_key = tuple(item.key for item in items)
        if page_key in self.prefetched_grid_pages:
            write_performance_log("grid_prefetch_skipped", started, f"page={page_label} reason=cached items={len(items)}")
            return
        self.prefetched_grid_pages.add(page_key)

        rendered: dict[str, object] = {}
        for item in items:
            if not item.artwork_path:
                continue
            try:
                data = fetch_artwork(item.raw, item.artwork_path, self.config)
                rendered[item.key] = render_card_artwork(data, self.config)
            except Exception:
                continue

        write_performance_log(
            "grid_prefetch",
            started,
            f"page={page_label} items={len(items)} rendered={len(rendered)}",
        )
        if not rendered:
            return

        def update() -> None:
            grid = self.query_one("#media-grid", MediaGrid)
            if not grid.is_mounted:
                return
            grid.artwork.update(rendered)
            grid.refresh_grid()

        self.call_from_thread(update)

    def action_show_settings(self, selected_action: str | None = None) -> None:
        self.help_visible = False
        self.picker_visible = False
        self.settings_visible = True
        self.query_one("#media-title", Static).update("Settings")
        view = self.show_media_list()
        view.clear()
        selected_index = 0
        rows = settings_rows(self.config)
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
        self.show_detail_text(f"Changed\n\n{label}: {value}\n\nSettings saved.")
        self.set_status(f"{label}: {value}")

    def action_show_help(self) -> None:
        self.help_visible = True
        self.settings_visible = False
        self.picker_visible = False
        self.query_one("#media-title", Static).update("Help")
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
        if action == "show_debug_log":
            path = debug_log_path()
            self.show_detail_text(f"Debug log\n\n{path}\n\nSet PLEX_TUI_PERF_LOG=1 before launch to include browsing performance timings.")
            self.set_status(f"Debug log: {path}")
            return
        if action == "show_recent_debug_log":
            path = debug_log_path()
            self.show_detail_text(render_debug_log_details(path))
            self.set_status(f"Recent debug log: {path}")
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
        self.set_status(f"Unknown settings action: {action}")

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
            self.query_one("#media-title", Static).update(f"{picker_title}: {media.title}")
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
        self.refresh_settings_after_change(numeric_step_action(name, step), label, str(value))
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
            if input_mode in {"mpv_window_size", "page_size", "auto_load_threshold"}:
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
            self.show_playback_error(str(exc))
            return
        self.detail_refresh_token += 1
        self.show_detail_text(
            render_playback_details(media.title, self.player, self.config, audio_choice, subtitle_choice)
        )
        self.set_status(
            render_playback_status(media.title, self.player, self.config, audio_choice, subtitle_choice)
        )

    def check_player_status(self) -> None:
        if self.player is None:
            return
        status = playback_exit_status(self.player, debug_log_path())
        if status is None:
            return
        selected = self.selected_media()
        self.player = None
        if selected is not None:
            self.show_media_details(selected)
        self.set_status(status)

    def action_stop_playback(self) -> None:
        if self.player is None:
            self.set_status("Nothing is playing")
            self.player = None
            return
        if not self.player.active:
            self.set_status(playback_exit_status(self.player, debug_log_path()) or "Nothing is playing")
            self.player = None
            return
        title = self.player.title
        stop_mpv(self.player)
        self.player = None
        self.set_status(f"Stopped {title}")

    def action_reload(self) -> None:
        self.load_server()

    def on_unmount(self) -> None:
        if self.login_session is not None:
            self.login_session.stop()

    def on_status_changed(self, event: StatusChanged) -> None:
        self.set_status(event.text)

    def set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def show_error(self, text: str) -> None:
        config_hint = f"Config: {config_path()}"
        self.set_status(f"Error: {text}")
        self.query_one("#media-title", Static).update("Error")
        view = self.show_media_list()
        view.clear()
        view.append(ListItem(Label(f"{text}\n{config_hint}")))
        self.show_detail_text(config_hint)

    def show_playback_error(self, text: str) -> None:
        path = debug_log_path()
        self.set_status(f"Playback error: {text}. Debug log: {path}")
        self.query_one("#media-title", Static).update("Playback Error")
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
    lines = [getattr(details, "title"), ""]

    lines.append("Metadata")
    for label, value in getattr(details, "metadata"):
        lines.append(f"{label}: {value}")
    lines.append(f"Playable: {'yes' if getattr(details, 'playable') else 'no'}")
    lines.append(f"Artwork: {artwork_status(details, config)}")

    if config is not None:
        lines.extend([
            "",
            "Preferences",
            f"Audio preference: {preference_value(config.preferred_audio_language)}",
            f"Subtitle mode: {subtitle_mode_value(config)}",
            f"Subtitle language: {subtitle_language_value(config)}",
        ])
        if raw is not None:
            effective = effective_stream_preference_rows(raw, config)
            if effective:
                lines.extend(["", "Effective Playback"])
                lines.extend(f"{label}: {value}" for label, value in effective)

    lines.extend(["", "Audio"])
    audio = getattr(details, "audio", [])
    if audio:
        lines.extend(f"- {track}" for track in audio)
    else:
        lines.append("None reported")

    lines.extend(["", "Subtitles"])
    subtitles = getattr(details, "subtitles")
    if subtitles:
        lines.extend(f"- {subtitle}" for subtitle in subtitles)
    else:
        lines.append("None reported")

    summary = getattr(details, "summary")
    if summary:
        lines.extend(["", "Summary", summary])

    return "\n".join(lines)


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
        rows.append(row)
    return Group(*rows)


def render_media_grid_card(
    media: MediaItem,
    selected: bool,
    config: AppConfig,
    artwork_overrides: dict[str, object] | None = None,
) -> object:
    marker = "▸ " if selected else "  "
    title_style = "bold #e5a00d" if selected else "bold"
    content_width = grid_card_content_width(config)
    title = truncate_text(media.title, content_width)
    subtitle = truncate_text("  ".join(bit for bit in (media.kind, media.subtitle) if bit), content_width)
    artwork = artwork_overrides.get(media.key) if artwork_overrides is not None else None
    if artwork is None:
        artwork = cached_card_artwork(media, config)
    if artwork is None:
        status = "poster" if media.artwork_path else "no poster"
        artwork = Text(f"[{status}]", style="dim")
    footer = "selected" if selected else ""
    return Group(
        artwork,
        Text(f"{marker}{title}", style=title_style),
        Text(f"  {subtitle}", style="dim"),
        Text(f"  {footer}", style="#e5a00d" if selected else "dim"),
    )


def cached_card_artwork(media: MediaItem, config: AppConfig) -> object | None:
    if not artwork_enabled(config) or not media.artwork_path or not artwork_is_cached(media.artwork_path, config):
        return None
    try:
        return render_card_artwork(fetch_artwork(media.raw, media.artwork_path, config), config)
    except Exception:
        return None


def render_card_artwork(data: bytes, config: AppConfig) -> object:
    spec = grid_density_spec(config)
    return render_artwork(data, width=int(spec["art_width"]), max_height=int(spec["art_height"]))


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


def settings_rows(config: AppConfig) -> list[ListItem]:
    return [
        SettingsHeaderRow("Account"),
        SettingsValueRow(f"Server: {config.base_url or 'not set'}"),
        SettingsValueRow(f"Server Token: {'saved' if config.token else 'not set'}"),
        SettingsValueRow(f"Account Token: {'saved' if config.account_token else 'not set'}"),
        SettingsActionRow("Reconnect / reload libraries", "reload"),
        SettingsActionRow("Relogin with Plex", "relogin"),
        SettingsHeaderRow("Streams"),
        SettingsValueRow(f"Audio Preference: {preference_value(config.preferred_audio_language)}"),
        SettingsValueRow(f"Subtitle Mode: {subtitle_mode_value(config)}"),
        SettingsValueRow(f"Subtitle Language: {subtitle_language_value(config)}"),
        SettingsActionRow("Clear audio preference", "clear_audio"),
        SettingsActionRow("Set subtitles to Auto", "subtitle_auto"),
        SettingsActionRow("Set subtitles to None", "subtitle_none"),
        SettingsActionRow("Clear subtitle preference", "clear_subtitle"),
        SettingsActionRow("Clear audio/subtitle preferences", "clear_tracks"),
        SettingsHeaderRow("Playback"),
        SettingsActionRow(f"mpv Window Size: {mpv_window_size_value(config)}  [cycle]", "cycle_mpv_window_size"),
        SettingsActionRow("mpv Window Size: set custom value...", "set_mpv_window_size"),
        SettingsActionRow("mpv Window Size: reset to Default", "reset_mpv_window_size"),
        SettingsHeaderRow("Artwork"),
        SettingsActionRow(f"Artwork: {artwork_mode_value(config)}  [toggle]", "toggle_artwork"),
        SettingsActionRow(f"Details Artwork: {detail_artwork_mode_value(config)}  [cycle]", "cycle_detail_artwork"),
        SettingsActionRow("Artwork Renderer: block", "artwork_renderer_block"),
        SettingsActionRow("Artwork Renderer: auto", "artwork_renderer_auto"),
        SettingsActionRow("Artwork Renderer: Kitty", "artwork_renderer_kitty"),
        SettingsHeaderRow("Browsing"),
        SettingsActionRow(f"Media View: {media_view_value(config)}  [toggle]", "toggle_media_view"),
        SettingsActionRow(f"Grid Density: {grid_density_value(config)}  [cycle]", "cycle_grid_density"),
        SettingsActionRow(f"Page Size: {config.page_size}  [-10]", "decrease_page_size"),
        SettingsActionRow(f"Page Size: {config.page_size}  [+10]", "increase_page_size"),
        SettingsActionRow("Page Size: set custom value...", "set_page_size"),
        SettingsActionRow(f"Page Size: reset to {DEFAULT_PAGE_SIZE}", "reset_page_size"),
        SettingsActionRow(f"Auto-load Threshold: {config.auto_load_threshold}  [-5]", "decrease_auto_load_threshold"),
        SettingsActionRow(f"Auto-load Threshold: {config.auto_load_threshold}  [+5]", "increase_auto_load_threshold"),
        SettingsActionRow("Auto-load Threshold: set custom value...", "set_auto_load_threshold"),
        SettingsActionRow(f"Auto-load Threshold: reset to {DEFAULT_AUTO_LOAD_THRESHOLD}", "reset_auto_load_threshold"),
        SettingsHeaderRow("Diagnostics"),
        SettingsValueRow(f"Config Path: {config_path()}"),
        SettingsValueRow(f"Cache Path: {cache_path()}"),
        SettingsValueRow(f"Debug Log: {debug_log_path()}"),
        SettingsValueRow(f"Client ID: {config.client_identifier or 'not set'}"),
        SettingsValueRow(f"Theme: {config.theme}"),
        SettingsActionRow("Show debug log path", "show_debug_log"),
        SettingsActionRow("Show recent debug log", "show_recent_debug_log"),
    ]


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
        "Set custom browsing values with whole numbers inside the allowed range.",
        "",
        "Diagnostics",
        f"Config Path: {config_path()}",
        f"Cache Path: {cache_path()}",
        f"Debug Log: {debug_log_path()}",
        f"Client ID: {config.client_identifier or 'not set'}",
        f"Theme: {config.theme}",
        "Show recent debug log",
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
        "?: show help",
        "q: quit",
        "",
        "Paths",
        f"Config: {config_path()}",
        f"Debug log: {debug_log_path()}",
    ])


def context_hint(row: object) -> str:
    if isinstance(row, LibraryRow):
        return "Enter opens library"
    if isinstance(row, LoadMoreRow):
        return "Enter loads next page"
    if isinstance(row, MediaRow):
        if row.media.playable:
            return "Enter selects item / p plays / a audio / s subtitles"
        return "Enter opens item"
    if isinstance(row, MediaGrid):
        media = row.selected_media
        if media is not None and media.playable:
            return "Arrows/page select card / p plays / a audio / s subtitles"
        return "Arrows/page select card / Enter opens item"
    if isinstance(row, ServerRow):
        return "Enter selects server"
    if isinstance(row, StreamRow):
        return "Enter saves preference"
    if isinstance(row, SettingsActionRow):
        return "Enter runs action"
    if isinstance(row, SettingsHeaderRow):
        return "Settings section"
    if isinstance(row, SettingsValueRow):
        return "Current setting value"
    return "Enter selects row"


def confirmation_required(action: str) -> bool:
    return action in {"clear_tracks", "clear_audio", "clear_subtitle"}


def settings_action_label(action: str) -> str:
    labels = {
        "clear_tracks": "Clear audio/subtitle preferences",
        "clear_audio": "Clear audio preference",
        "clear_subtitle": "Clear subtitle preference",
    }
    return labels.get(action, action)


def numeric_setting_label(name: str) -> str:
    if name == "auto_load_threshold":
        return "Auto-load threshold"
    if name == "page_size":
        return "Page size"
    return name


def numeric_step_action(name: str, step: int) -> str:
    prefix = "increase" if step > 0 else "decrease"
    return f"{prefix}_{name}"


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
    details.append(player.stream_mode)
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
        "Status: playing",
        f"Stream mode: {player.stream_mode}",
        f"Resume: {format_offset(player.start_offset_ms) if player.start_offset_ms else 'start'}",
        f"Subtitles available: {player.subtitle_count}",
        f"mpv window size: {mpv_window_size_value(config)}",
        "",
        "Selected Streams",
        f"Audio: {render_audio_playback_preference(config, audio_choice).removeprefix('audio ')}",
        f"Subtitles: {render_subtitle_playback_preference(config, subtitle_choice).removeprefix('subtitles ')}",
        "",
        "Diagnostics",
        f"Debug log: {debug_log_path()}",
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


def render_playback_error_details(error: str, path: Path, max_lines: int = 12) -> str:
    lines = [
        "Playback Error",
        "",
        error,
        "",
        f"Debug log: {path}",
        "",
        "Recent Debug Log",
    ]
    recent = recent_debug_log_lines(path, max_lines)
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
