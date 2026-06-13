from __future__ import annotations

import tomllib
from pathlib import Path

from plextui import config


def test_config_and_debug_paths_share_platformdirs_base(monkeypatch):
    monkeypatch.setattr(config, "user_config_dir", lambda app_name: f"/tmp/{app_name}")
    monkeypatch.setattr(config, "user_cache_dir", lambda app_name: f"/tmp/cache/{app_name}")

    assert config.config_path() == Path("/tmp/plex-tui/config.toml")
    assert config.cache_path() == Path("/tmp/cache/plex-tui")
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
        "mpv_window_size",
        "page_size",
        "auto_load_threshold",
        "grid_prefetch_pages",
        "hidden_library_keys",
        "artwork_mode",
        "artwork_renderer",
        "detail_artwork_mode",
        "grid_density",
        "media_view",
        "theme",
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
            'mpv_window_size = "huge"',
            'page_size = "5"',
            'auto_load_threshold = "500"',
            'grid_prefetch_pages = "20"',
            "",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "config_path", lambda: config_file)
    monkeypatch.setattr(config, "debug_log_path", lambda: debug_file)

    loaded = config.load_config()

    assert loaded.subtitle_mode == "auto"
    assert loaded.mpv_window_size == ""
    assert loaded.page_size == config.DEFAULT_PAGE_SIZE
    assert loaded.auto_load_threshold == config.DEFAULT_AUTO_LOAD_THRESHOLD
    assert loaded.grid_prefetch_pages == config.DEFAULT_GRID_PREFETCH_PAGES
    log = debug_file.read_text(encoding="utf-8")
    assert "invalid subtitle_mode" in log
    assert "invalid mpv_window_size" in log
    assert "invalid page_size" in log
    assert "invalid auto_load_threshold" in log
    assert "invalid grid_prefetch_pages" in log


def test_invalid_artwork_settings_log_and_normalize(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    debug_file = tmp_path / "debug.log"
    config_file.write_text(
        '\n'.join([
            'base_url = "http://plex"',
            'token = "token"',
            'client_identifier = "client"',
            'artwork_mode = "maybe"',
            'artwork_renderer = "sixel"',
            'detail_artwork_mode = "always"',
            'grid_density = "huge"',
            'media_view = "tiles"',
            "",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "config_path", lambda: config_file)
    monkeypatch.setattr(config, "debug_log_path", lambda: debug_file)

    loaded = config.load_config()

    assert loaded.artwork_mode == "on"
    assert loaded.artwork_renderer == "block"
    assert loaded.detail_artwork_mode == "list_only"
    assert loaded.grid_density == "comfortable"
    assert loaded.media_view == "list"
    log = debug_file.read_text(encoding="utf-8")
    assert "invalid artwork_mode" in log
    assert "invalid artwork_renderer" in log
    assert "invalid detail_artwork_mode" in log
    assert "invalid grid_density" in log
    assert "invalid media_view" in log


def test_theme_round_trips_through_config(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: config_file)

    saved = config.AppConfig("http://plex", "token", "client", theme="textual-light")
    config.save_config(saved)
    loaded = config.load_config()

    assert loaded.theme == "textual-light"
    assert 'theme = "textual-light"' in config_file.read_text(encoding="utf-8")


def test_mpv_window_size_round_trips_through_config(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: config_file)

    saved = config.AppConfig("http://plex", "token", "client", mpv_window_size="1280x720")
    config.save_config(saved)
    loaded = config.load_config()

    assert loaded.mpv_window_size == "1280x720"
    assert 'mpv_window_size = "1280x720"' in config_file.read_text(encoding="utf-8")


def test_browsing_performance_settings_round_trip(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: config_file)

    saved = config.AppConfig(
        "http://plex",
        "token",
        "client",
        page_size=250,
        auto_load_threshold=25,
        grid_prefetch_pages=4,
        hidden_library_keys=("2", "7"),
        grid_density="large",
    )
    config.save_config(saved)
    loaded = config.load_config()

    assert loaded.page_size == 250
    assert loaded.auto_load_threshold == 25
    assert loaded.grid_prefetch_pages == 4
    assert loaded.hidden_library_keys == ("2", "7")
    assert loaded.grid_density == "large"
    text = config_file.read_text(encoding="utf-8")
    assert "page_size = 250" in text
    assert "auto_load_threshold = 25" in text
    assert "grid_prefetch_pages = 4" in text
    assert 'hidden_library_keys = "2,7"' in text
    assert 'grid_density = "large"' in text


def test_hidden_library_keys_parse_unique_csv_values(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '\n'.join([
            'base_url = "http://plex"',
            'token = "token"',
            'client_identifier = "client"',
            'hidden_library_keys = " 2,7,2, ,9 "',
            "",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "config_path", lambda: config_file)

    loaded = config.load_config()

    assert loaded.hidden_library_keys == ("2", "7", "9")


def test_deprecated_poster_view_normalizes_to_list(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    debug_file = tmp_path / "debug.log"
    config_file.write_text(
        '\n'.join([
            'base_url = "http://plex"',
            'token = "token"',
            'client_identifier = "client"',
            'media_view = "poster"',
            "",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "config_path", lambda: config_file)
    monkeypatch.setattr(config, "debug_log_path", lambda: debug_file)

    loaded = config.load_config()

    assert loaded.media_view == "list"
    assert "deprecated" in debug_file.read_text(encoding="utf-8")
