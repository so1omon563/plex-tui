from __future__ import annotations

import pytest

from plextui import __version__
from plextui import __main__ as cli


def test_cli_prints_config_path(monkeypatch, capsys):
    monkeypatch.setattr(cli, "config_path", lambda: "/tmp/plex-tui/config.toml")

    assert cli.main(["--config-path"]) == 0

    assert capsys.readouterr().out == "/tmp/plex-tui/config.toml\n"


def test_cli_prints_debug_log_path(monkeypatch, capsys):
    monkeypatch.setattr(cli, "debug_log_path", lambda: "/tmp/plex-tui/debug.log")

    assert cli.main(["--debug-log-path"]) == 0

    assert capsys.readouterr().out == "/tmp/plex-tui/debug.log\n"


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
