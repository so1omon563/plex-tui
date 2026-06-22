from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from plextui import __version__
from plextui import __main__ as cli
from plextui.config import AppConfig
from plextui.models import LibraryItem, MediaItem
from plextui.plex_service import MediaPage


class FakeAvailability:
    title = "Tubi"
    offerType = "free"
    url = "https://tubitv.example/movie"


class FakeDiscoverRaw:
    title = "Free Movie"

    def streamingServices(self):
        return [FakeAvailability()]


class FakeCliService:
    def __init__(self, _config: AppConfig) -> None:
        self.movie_library = LibraryItem("Movies", "1", "movie", object())
        self.show_library = LibraryItem("TV Shows", "2", "show", object())
        self.libraries_calls = 0
        self.search_calls = []
        self.discover_calls = []
        self.continue_watching_calls = []

    @property
    def friendly_name(self) -> str:
        return "Plex"

    def libraries(self) -> list[LibraryItem]:
        self.libraries_calls += 1
        return [self.movie_library, self.show_library]

    def continue_watching_page(self, start: int, size: int) -> MediaPage:
        self.continue_watching_calls.append((start, size))
        return MediaPage(
            [
                MediaItem(
                    "Movie",
                    "2024",
                    "movie",
                    "m1",
                    True,
                    SimpleNamespace(viewOffset=50_000, duration=100_000),
                )
            ],
            start=0,
            total=1,
        )

    def search_page(self, query: str, library: LibraryItem | None, start: int, size: int) -> MediaPage:
        self.search_calls.append((query, library, start, size))
        return MediaPage(
            [MediaItem("Interstellar", "2014", "movie", "m2", True, SimpleNamespace())],
            start=0,
            total=1,
        )

    def discover_page(self, query: str, start: int, size: int) -> MediaPage:
        self.discover_calls.append((query, start, size))
        return MediaPage(
            [
                MediaItem("First Movie", "2024", "movie", "plex://movie/1", False, SimpleNamespace(title="First Movie")),
                MediaItem("Free Movie", "2024  Available: Tubi (free)", "movie", "plex://movie/2", False, FakeDiscoverRaw()),
            ],
            start=0,
            total=2,
        )


def test_cli_prints_config_path(monkeypatch, capsys):
    monkeypatch.setattr(cli, "config_path", lambda: "/tmp/plex-tui/config.toml")

    assert cli.main(["--config-path"]) == 0

    assert capsys.readouterr().out == "/tmp/plex-tui/config.toml\n"


def test_cli_prints_debug_log_path(monkeypatch, capsys):
    monkeypatch.setattr(cli, "debug_log_path", lambda: "/tmp/plex-tui/debug.log")

    assert cli.main(["--debug-log-path"]) == 0

    assert capsys.readouterr().out == "/tmp/plex-tui/debug.log\n"


def test_cli_prints_diagnostics(monkeypatch, capsys):
    config = AppConfig("http://plex", "token", "client-id")
    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(cli, "detect_mpv", lambda: ("/usr/bin/mpv", "mpv 0.40.0"))
    monkeypatch.setattr(
        cli,
        "render_app_diagnostics",
        lambda _config, _mpv_info: "App Diagnostics\nmpv: /usr/bin/mpv\n",
    )

    assert cli.main(["--diagnostics"]) == 0

    assert capsys.readouterr().out == "App Diagnostics\nmpv: /usr/bin/mpv\n\n"


def test_cli_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])

    assert exc.value.code == 0
    assert capsys.readouterr().out == f"plex-tui {__version__}\n"


def test_cli_runs_smoke(monkeypatch):
    called = False

    def fake_smoke_main() -> None:
        nonlocal called
        called = True

    import plextui.smoke

    monkeypatch.setattr(plextui.smoke, "main", fake_smoke_main)

    assert cli.main(["--smoke"]) == 0
    assert called


def test_cli_lists_libraries(monkeypatch, capsys):
    monkeypatch.setattr(cli, "PlexService", FakeCliService)
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig("http://plex", "token", "client-id"))

    assert cli.main(["libraries"]) == 0

    output = capsys.readouterr().out
    assert "KEY" in output
    assert "TYPE" in output
    assert "Movies" in output
    assert "TV Shows" in output


def test_cli_lists_libraries_as_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "PlexService", FakeCliService)
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig("http://plex", "token", "client-id"))

    assert cli.main(["libraries", "--json"]) == 0

    assert json.loads(capsys.readouterr().out) == [
        {"key": "1", "title": "Movies", "kind": "movie"},
        {"key": "2", "title": "TV Shows", "kind": "show"},
    ]


def test_cli_status_reports_ready_state(monkeypatch, capsys, tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("base_url = 'http://plex'\ntoken = 'token'\n", encoding="utf-8")
    monkeypatch.setattr(cli, "PlexService", FakeCliService)
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig("http://plex", "token", "client-id"))
    monkeypatch.setattr(cli, "config_path", lambda: config_file)
    monkeypatch.setattr(cli, "debug_log_path", lambda: tmp_path / "debug.log")
    monkeypatch.setattr(cli, "detect_mpv", lambda: ("/usr/bin/mpv", "mpv 0.40.0"))

    assert cli.main(["status"]) == 0

    output = capsys.readouterr().out
    assert "Ready          yes" in output
    assert "Configured     yes" in output
    assert "Connected      yes" in output
    assert "Server" in output
    assert "Libraries      2" in output
    assert "mpv            mpv 0.40.0" in output
    assert str(config_file) in output


def test_cli_status_reports_json(monkeypatch, capsys, tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("base_url = 'http://plex'\ntoken = 'token'\n", encoding="utf-8")
    monkeypatch.setattr(cli, "PlexService", FakeCliService)
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig("http://plex", "token", "client-id"))
    monkeypatch.setattr(cli, "config_path", lambda: config_file)
    monkeypatch.setattr(cli, "debug_log_path", lambda: tmp_path / "debug.log")
    monkeypatch.setattr(cli, "detect_mpv", lambda: ("/usr/bin/mpv", "mpv 0.40.0"))

    assert cli.main(["status", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ready"] is True
    assert payload["configured"] is True
    assert payload["connected"] is True
    assert payload["server"] == "Plex"
    assert payload["library_count"] == 2
    assert payload["mpv_available"] is True
    assert payload["paths"]["config_exists"] is True


def test_cli_status_reports_missing_config(monkeypatch, capsys, tmp_path):
    config_file = tmp_path / "missing.toml"
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig("", "", "client-id"))
    monkeypatch.setattr(cli, "config_path", lambda: config_file)
    monkeypatch.setattr(cli, "debug_log_path", lambda: tmp_path / "debug.log")
    monkeypatch.setattr(cli, "detect_mpv", lambda: ("/usr/bin/mpv", "mpv 0.40.0"))

    assert cli.main(["status"]) == 2

    output = capsys.readouterr().out
    assert "Ready          no" in output
    assert "Configured     no" in output
    assert "Config exists  no" in output
    assert "Error          missing Plex config" in output


def test_cli_lists_continue_watching(monkeypatch, capsys):
    monkeypatch.setattr(cli, "PlexService", FakeCliService)
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig("http://plex", "token", "client-id"))

    assert cli.main(["continue-watching", "--limit", "5"]) == 0

    output = capsys.readouterr().out
    assert "Movie" in output
    assert "50%" in output


def test_cli_lists_continue_watching_as_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "PlexService", FakeCliService)
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig("http://plex", "token", "client-id"))

    assert cli.main(["continue-watching", "--json"]) == 0

    assert json.loads(capsys.readouterr().out) == [
        {
            "key": "m1",
            "title": "Movie",
            "subtitle": "2024",
            "kind": "movie",
            "playable": True,
            "progress_percent": 50,
        }
    ]


def test_cli_searches_globally(monkeypatch, capsys):
    service = None

    class CapturingService(FakeCliService):
        def __init__(self, config: AppConfig) -> None:
            nonlocal service
            super().__init__(config)
            service = self

    monkeypatch.setattr(cli, "PlexService", CapturingService)
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig("http://plex", "token", "client-id"))

    assert cli.main(["search", "interstellar", "--limit", "3"]) == 0

    assert service is not None
    assert service.search_calls == [("interstellar", None, 0, 3)]
    assert "Interstellar" in capsys.readouterr().out


def test_cli_searches_discover(monkeypatch, capsys):
    service = None

    class CapturingService(FakeCliService):
        def __init__(self, config: AppConfig) -> None:
            nonlocal service
            super().__init__(config)
            service = self

    monkeypatch.setattr(cli, "PlexService", CapturingService)
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig("http://plex", "token", "client-id", account_token="account"))

    assert cli.main(["discover", "matrix", "--limit", "3"]) == 0

    assert service is not None
    assert service.discover_calls == [("matrix", 0, 3)]
    output = capsys.readouterr().out
    assert "Free Movie" in output
    assert "Tubi" in output


def test_cli_opens_discover_availability(monkeypatch, capsys):
    service = None
    opened = []

    class CapturingService(FakeCliService):
        def __init__(self, config: AppConfig) -> None:
            nonlocal service
            super().__init__(config)
            service = self

    monkeypatch.setattr(cli, "PlexService", CapturingService)
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig("http://plex", "token", "client-id", account_token="account"))
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url))

    assert cli.main(["discover-open", "matrix", "--index", "2", "--limit", "3"]) == 0

    assert service is not None
    assert service.discover_calls == [("matrix", 0, 3)]
    assert opened == ["https://tubitv.example/movie"]
    assert capsys.readouterr().out == "Opened: Free Movie - Tubi (free)\n"


def test_cli_discover_open_reports_missing_index(monkeypatch, capsys):
    monkeypatch.setattr(cli, "PlexService", FakeCliService)
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig("http://plex", "token", "client-id", account_token="account"))

    assert cli.main(["discover-open", "matrix", "--index", "9"]) == 2

    assert capsys.readouterr().err == "plex-tui: discover result index out of range: 9\n"


def test_cli_searches_library_by_title_as_json(monkeypatch, capsys):
    service = None

    class CapturingService(FakeCliService):
        def __init__(self, config: AppConfig) -> None:
            nonlocal service
            super().__init__(config)
            service = self

    monkeypatch.setattr(cli, "PlexService", CapturingService)
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig("http://plex", "token", "client-id"))

    assert cli.main(["search", "alien", "--library", "Movies", "--json"]) == 0

    assert service is not None
    assert service.search_calls == [("alien", service.movie_library, 0, 10)]
    assert json.loads(capsys.readouterr().out)[0]["title"] == "Interstellar"


def test_cli_search_reports_missing_library(monkeypatch, capsys):
    monkeypatch.setattr(cli, "PlexService", FakeCliService)
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig("http://plex", "token", "client-id"))

    assert cli.main(["search", "alien", "--library", "Music"]) == 2

    assert capsys.readouterr().err == "plex-tui: library not found: Music\n"


def test_cli_reports_connection_error(monkeypatch, capsys):
    class BrokenService:
        def __init__(self, _config: AppConfig) -> None:
            raise ValueError("missing Plex config")

    monkeypatch.setattr(cli, "PlexService", BrokenService)
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig("", "", "client-id"))

    assert cli.main(["libraries"]) == 2

    assert capsys.readouterr().err == "plex-tui: missing Plex config\n"
