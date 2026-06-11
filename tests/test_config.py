from __future__ import annotations

from pathlib import Path

from plextui import config


def test_config_and_debug_paths_share_platformdirs_base(monkeypatch):
    monkeypatch.setattr(config, "user_config_dir", lambda app_name: f"/tmp/{app_name}")

    assert config.config_path() == Path("/tmp/plex-tui/config.toml")
    assert config.debug_log_path() == Path("/tmp/plex-tui/debug.log")
