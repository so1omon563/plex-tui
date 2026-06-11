from __future__ import annotations

from dataclasses import dataclass

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static

from .auth import LoginSession, ServerChoice, save_server_choice
from .config import AppConfig, config_path, load_config
from .models import LibraryItem, MediaItem
from .player import PlayerError, play_with_mpv
from .plex_service import PlexService


@dataclass
class BrowseState:
    title: str
    items: list[MediaItem]
    selected_library: LibraryItem | None = None


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
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "reload", "Reload"),
        Binding("/", "focus_search", "Search"),
        Binding("escape", "back_or_clear", "Back"),
        Binding("p", "play_selected", "Play"),
    ]

    service: reactive[PlexService | None] = reactive(None)
    selected_library: reactive[LibraryItem | None] = reactive(None)
    browsing_stack: list[BrowseState]
    config: AppConfig
    login_session: LoginSession | None
    pending_account_token: str

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
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.browsing_stack = []
        self.login_session = None
        self.pending_account_token = ""
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
            self.set_status(f"{media.title}: {len(children)} items")

        self.call_from_thread(update)

    def show_media(self, title: str, items: list[MediaItem]) -> None:
        self.query_one("#media-title", Static).update(title)
        view = self.query_one("#media", ListView)
        view.clear()
        for item in items:
            view.append(MediaRow(item))

    def action_focus_search(self) -> None:
        search = self.query_one("#search", Input)
        search.display = True
        search.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self.run_search(event.value.strip())

    @work(thread=True)
    def run_search(self, query: str) -> None:
        if self.service is None or not query:
            return
        self.post_message(StatusChanged(f"Searching for {query}..."))
        try:
            items = self.service.search(query, self.selected_library)
        except Exception as exc:
            self.call_from_thread(self.show_error, str(exc))
            return

        def update() -> None:
            self.show_media(f"Search: {query}", items)
            self.set_status(f"{len(items)} results")

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

        if len(self.browsing_stack) > 1:
            self.browsing_stack.pop()
            state = self.browsing_stack[-1]
            self.show_media(state.title, state.items)
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
            play_with_mpv(row.media.raw)
        except PlayerError as exc:
            self.show_error(str(exc))
            return
        self.set_status(f"Playing {row.media.title}")

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
