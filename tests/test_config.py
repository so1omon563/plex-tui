from __future__ import annotations

import tomllib
from pathlib import Path

from plextui import config


def test_config_and_debug_paths_share_platformdirs_base(monkeypatch):
    monkeypatch.setattr(config, "user_config_dir", lambda app_name: f"/tmp/{app_name}")

    assert config.config_path() == Path("/tmp/plex-tui/config.toml")
    assert config.debug_log_path() == Path("/tmp/plex-tui/debug.log")


def test_config_example_parses_and_uses_known_fields():
    raw = tomllib.loads(Path("config.example.toml").read_text(encoding="utf-8"))

    assert set(raw) <= {
        "base_url",
        "token",
        "client_identifier",
        "account_token",
        "preferred_audio_language",
        "preferred_subtitle_language",
        "subtitle_mode",
    }
    assert raw["base_url"]
    assert raw["token"]
    assert raw["client_identifier"]


def test_invalid_subtitle_mode_logs_and_normalizes(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    debug_file = tmp_path / "debug.log"
    config_file.write_text(
        '\n'.join([
            'base_url = "http://plex"',
            'token = "token"',
            'client_identifier = "client"',
            'subtitle_mode = "bad"',
            "",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "config_path", lambda: config_file)
    monkeypatch.setattr(config, "debug_log_path", lambda: debug_file)

    loaded = config.load_config()

    assert loaded.subtitle_mode == "auto"
    assert "invalid subtitle_mode" in debug_file.read_text(encoding="utf-8")
