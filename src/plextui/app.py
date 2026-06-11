from __future__ import annotations

from dataclasses import dataclass

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static

from .auth import LoginSession, ServerChoice, save_server_choice
from .config import AppConfig, config_path, load_config
from .models import LibraryItem, MediaItem
from .player import PlayerError, PlayerHandle, StreamChoice, audio_choices, play_with_mpv, stop_mpv, subtitle_choices
from .plex_service import PlexService, media_details


@dataclass
class BrowseState:
    title: str
    items: list[MediaItem]
    selected_library: LibraryItem | None = None
    search: bool = False


class LibraryRow(ListItem):
    def __init__(self, library: LibraryItem) -> None:
        super().__init__(Label(library.title))
        self.library = library


class MediaRow(ListItem):
    def __init__(self, media: MediaItem) -> None:
        marker = ">" if not media.playable else " "
        subtitle = f" [{media.kind}] {media.subtitle}".rstrip()
        super().__init__(Label(f"{marker} {media.title}{subtitle}"))
        self.media = media


class ServerRow(ListItem):
    def __init__(self, choice: ServerChoice) -> None:
        super().__init__(Label(f"{choice.name}  {choice.uri}"))
        self.choice = choice


class StreamRow(ListItem):
    def __init__(self, choice: StreamChoice, stream_type: str) -> None:
        super().__init__(Label(choice.label))
        self.choice = choice
        self.stream_type = stream_type


class SettingsActionRow(ListItem):
    def __init__(self, label: str, action: str) -> None:
        super().__init__(Label(label))
        self.action = action


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
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "reload", "Reload"),
        Binding("/", "focus_search", "Search"),
        Binding("g", "focus_global_search", "Global"),
        Binding("tab", "focus_next", "Next"),
        Binding("shift+tab", "focus_previous", "Prev"),
        Binding("l", "focus_libraries", "Focus libraries"),
        Binding("m", "focus_media", "Focus media list"),
        Binding("comma", "show_settings", "Settings"),
        Binding("escape", "back_or_clear", "Back"),
        Binding("p", "play_selected", "Play"),
        Binding("a", "audio_picker", "Audio"),
        Binding("s", "subtitle_picker", "Subtitles"),
        Binding("x", "stop_playback", "Stop"),
    ]

    service: reactive[PlexService | None] = reactive(None)
    selected_library: reactive[LibraryItem | None] = reactive(None)
    browsing_stack: list[BrowseState]
    config: AppConfig
    login_session: LoginSession | None
    pending_account_token: str
    search_global: bool
    settings_visible: bool
    picker_visible: bool
    selected_subtitle: StreamChoice | None
    selected_audio: StreamChoice | None
    picker_media_key: str | None
    player: PlayerHandle | None

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
        self.settings_visible = False
        self.picker_visible = False
        self.selected_subtitle = None
        self.selected_audio = None
        self.picker_media_key = None
        self.player = None
        self.query_one("#search", Input).display = False
        self.load_server()

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
            view = self.query_one("#media", ListView)
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
            view = self.query_one("#media", ListView)
            view.clear()
            for choice in choices:
                view.append(ServerRow(choice))
            view.focus()
            self.show_detail_text("Choose the connection you want this app to use.")
            self.set_status("Select a Plex server connection and press Enter")

        self.call_from_thread(show_choices)

    def populate_libraries(self, libraries: list[LibraryItem]) -> None:
        view = self.query_one("#libraries", ListView)
        view.clear()
        for library in libraries:
            view.append(LibraryRow(library))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        row = event.item
        if isinstance(row, LibraryRow):
            self.open_library(row.library)
        elif isinstance(row, MediaRow):
            self.open_media(row.media)
        elif isinstance(row, ServerRow):
            self.choose_server(row.choice)
        elif isinstance(row, StreamRow):
            self.choose_stream(row.choice, row.stream_type)
        elif isinstance(row, SettingsActionRow):
            self.run_settings_action(row.action)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "media":
            return
        row = event.item
        if row is not None and row not in list(event.list_view.children):
            return
        if row is not None and event.list_view.highlighted_child is not row:
            return
        if isinstance(row, MediaRow):
            self.show_media_details(row.media)
        elif isinstance(row, ServerRow):
            self.show_detail_text(f"{row.choice.name}\n\n{row.choice.uri}\n\nSource: {row.choice.source}")
        elif row is None and not list(event.list_view.children):
            self.show_detail_text("Select an item")

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
        try:
            items = self.service.library_items(library)
        except Exception as exc:
            self.call_from_thread(self.show_error, str(exc))
            return

        def update() -> None:
            self.selected_library = library
            self.browsing_stack = [BrowseState(library.title, items, library)]
            self.show_media(library.title, items)
            self.query_one("#media", ListView).focus()
            self.set_status(f"{library.title}: {len(items)} items")

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
            self.browsing_stack.append(BrowseState(media.title, children, self.selected_library))
            self.show_media(media.title, children)
            self.query_one("#media", ListView).focus()
            self.set_status(f"{media.title}: {len(children)} items")

        self.call_from_thread(update)

    def show_media(self, title: str, items: list[MediaItem], selected_key: str | None = None) -> None:
        self.query_one("#media-title", Static).update(title)
        view = self.query_one("#media", ListView)
        view.clear()
        for item in items:
            view.append(MediaRow(item))
        if items:
            selected_index = selected_media_index(items, selected_key)
            view.index = selected_index
            self.show_media_details(items[selected_index])
        else:
            self.show_detail_text("No items")

    def show_media_details(self, item: MediaItem) -> None:
        details = media_details(item)
        self.show_detail_text(render_details(details))
        self.refresh_media_details(item)

    @work(thread=True, exclusive=True)
    def refresh_media_details(self, item: MediaItem) -> None:
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
            )
        except Exception:
            return

        def update() -> None:
            row = self.query_one("#media", ListView).highlighted_child
            if isinstance(row, MediaRow) and row.media.key == item.key:
                details = media_details(full_item)
                self.show_detail_text(render_details(details))

        self.call_from_thread(update)

    def show_detail_text(self, text: str) -> None:
        self.query_one("#detail-content", Static).update(text)
        self.query_one("#detail-scroll", VerticalScroll).scroll_home(animate=False)

    def action_focus_search(self) -> None:
        self.search_global = False
        search = self.query_one("#search", Input)
        search.placeholder = "Search current library"
        search.value = ""
        search.display = True
        search.focus()

    def action_focus_global_search(self) -> None:
        self.search_global = True
        search = self.query_one("#search", Input)
        search.placeholder = "Search all libraries"
        search.value = ""
        search.display = True
        search.focus()

    def action_focus_libraries(self) -> None:
        self.query_one("#libraries", ListView).focus()
        self.set_status("Focus moved to libraries")

    def action_focus_media(self) -> None:
        self.query_one("#media", ListView).focus()
        self.set_status("Focus moved to media list")

    def action_show_settings(self) -> None:
        self.picker_visible = False
        self.settings_visible = True
        self.query_one("#media-title", Static).update("Settings")
        view = self.query_one("#media", ListView)
        view.clear()
        for label, value in config_rows(self.config):
            view.append(ListItem(Label(f"{label}: {value}")))
        view.append(ListItem(Label("")))
        view.append(SettingsActionRow("Reconnect / reload libraries", "reload"))
        view.append(SettingsActionRow("Relogin with Plex", "relogin"))
        view.append(SettingsActionRow("Clear selected audio/subtitle tracks", "clear_tracks"))
        self.show_detail_text(render_settings(self.config))
        view.focus()
        self.set_status("Settings")

    def run_settings_action(self, action: str) -> None:
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
            self.selected_audio = None
            self.selected_subtitle = None
            self.set_status("Cleared selected audio/subtitle tracks")
            return
        self.set_status(f"Unknown settings action: {action}")

    def action_subtitle_picker(self) -> None:
        row = self.query_one("#media", ListView).highlighted_child
        if not isinstance(row, MediaRow) or not row.media.playable:
            self.set_status("Select playable media before choosing subtitles")
            return
        self.open_stream_picker(row.media, "subtitle")

    def action_audio_picker(self) -> None:
        row = self.query_one("#media", ListView).highlighted_child
        if not isinstance(row, MediaRow) or not row.media.playable:
            self.set_status("Select playable media before choosing audio")
            return
        self.open_stream_picker(row.media, "audio")

    @work(thread=True)
    def open_stream_picker(self, media: MediaItem, stream_type: str) -> None:
        self.post_message(StatusChanged(f"Loading {stream_type} tracks..."))
        try:
            choices = subtitle_choices(media.raw) if stream_type == "subtitle" else audio_choices(media.raw)
        except Exception as exc:
            self.call_from_thread(self.show_error, str(exc))
            return

        def update() -> None:
            self.picker_visible = True
            self.settings_visible = False
            self.picker_media_key = media.key
            self.query_one("#media-title", Static).update("Subtitle Tracks" if stream_type == "subtitle" else "Audio Tracks")
            view = self.query_one("#media", ListView)
            view.clear()
            for choice in choices:
                view.append(StreamRow(choice, stream_type))
            view.focus()
            self.show_detail_text(f"Select a {stream_type} track for the next playback.")
            self.set_status(f"Choose {stream_type} track")

        self.call_from_thread(update)

    def choose_stream(self, choice: StreamChoice, stream_type: str) -> None:
        if stream_type == "subtitle":
            self.selected_subtitle = choice
            self.set_status(f"Subtitle: {choice.label}")
        elif stream_type == "audio":
            self.selected_audio = choice
            self.set_status(f"Audio: {choice.label}")
        self.picker_visible = False
        if self.browsing_stack:
            state = self.browsing_stack[-1]
            self.show_media(state.title, state.items, selected_key=self.picker_media_key)
        self.picker_media_key = None
        self.query_one("#media", ListView).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            query = event.value.strip()
            event.input.display = False
            self.run_search(query, self.search_global)

    @work(thread=True)
    def run_search(self, query: str, global_search: bool = False) -> None:
        if self.service is None or not query:
            return
        scope = "all libraries" if global_search else "current library"
        self.post_message(StatusChanged(f"Searching {scope} for {query}..."))
        try:
            library = None if global_search else self.selected_library
            items = self.service.search(query, library)
        except Exception as exc:
            self.call_from_thread(self.show_error, str(exc))
            return

        def update() -> None:
            title = f"Global search: {query}" if global_search else f"Search: {query}"
            if self.browsing_stack and self.browsing_stack[-1].search:
                self.browsing_stack.pop()
            self.browsing_stack.append(BrowseState(title, items, None if global_search else self.selected_library, search=True))
            self.show_media(title, items)
            self.query_one("#media", ListView).focus()
            self.set_status(f"{len(items)} results in {scope}")

        self.call_from_thread(update)

    def action_back_or_clear(self) -> None:
        search = self.query_one("#search", Input)
        if search.display:
            search.value = ""
            search.display = False
            if self.browsing_stack:
                state = self.browsing_stack[-1]
                self.show_media(state.title, state.items)
            self.query_one("#media", ListView).focus()
            return

        if self.settings_visible or self.picker_visible:
            self.settings_visible = False
            self.picker_visible = False
            selected_key = self.picker_media_key
            self.picker_media_key = None
            if self.browsing_stack:
                state = self.browsing_stack[-1]
                self.show_media(state.title, state.items, selected_key=selected_key)
            self.query_one("#media", ListView).focus()
            return

        if len(self.browsing_stack) > 1:
            self.browsing_stack.pop()
            state = self.browsing_stack[-1]
            self.show_media(state.title, state.items)
            self.query_one("#media", ListView).focus()
            self.set_status(state.title)

    def action_play_selected(self) -> None:
        row = self.query_one("#media", ListView).highlighted_child
        if not isinstance(row, MediaRow):
            self.set_status("No media selected")
            return
        if not row.media.playable:
            self.set_status("Selected item is not directly playable")
            return
        try:
            stop_mpv(self.player)
            self.player = play_with_mpv(
                row.media.raw,
                subtitle_choice=self.selected_subtitle,
                audio_choice=self.selected_audio,
            )
        except PlayerError as exc:
            self.show_error(str(exc))
            return
        subtitle_text = (
            f" with {self.player.subtitle_count} subtitles"
            if self.player.subtitle_count
            else ""
        )
        resume_text = (
            f" from {format_offset(self.player.start_offset_ms)}"
            if self.player.start_offset_ms
            else ""
        )
        self.set_status(f"Playing {row.media.title}{resume_text}{subtitle_text} ({self.player.stream_mode})")

    def action_stop_playback(self) -> None:
        if self.player is None or not self.player.active:
            self.set_status("Nothing is playing")
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
        self.query_one("#media", ListView).clear()
        self.query_one("#media", ListView).append(ListItem(Label(f"{text}\n{config_hint}")))
        self.show_detail_text(config_hint)


def format_offset(milliseconds: int) -> str:
    seconds = max(0, milliseconds // 1000)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def render_details(details: object) -> str:
    lines = [getattr(details, "title"), ""]

    lines.append("Metadata")
    for label, value in getattr(details, "metadata"):
        lines.append(f"{label}: {value}")
    lines.append(f"Playable: {'yes' if getattr(details, 'playable') else 'no'}")

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


def config_rows(config: AppConfig) -> list[tuple[str, str]]:
    return [
        ("Config Path", str(config_path())),
        ("Base URL", config.base_url or "not set"),
        ("Server Token", "saved" if config.token else "not set"),
        ("Account Token", "saved" if config.account_token else "not set"),
        ("Client ID", config.client_identifier or "not set"),
    ]


def render_settings(config: AppConfig) -> str:
    lines = ["Settings", ""]
    for label, value in config_rows(config):
        lines.append(f"{label}: {value}")
    lines.extend([
        "",
        "Actions",
        "Reconnect / reload libraries",
        "Relogin with Plex",
        "Clear selected audio/subtitle tracks",
    ])
    return "\n".join(lines)


def selected_media_index(items: list[MediaItem], selected_key: str | None) -> int:
    if selected_key is None:
        return 0
    for index, item in enumerate(items):
        if item.key == selected_key:
            return index
    return 0
