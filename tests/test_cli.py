from __future__ import annotations

import pytest

from plextui import __version__
from plextui import __main__ as cli
from plextui.config import AppConfig


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
