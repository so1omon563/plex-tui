from __future__ import annotations

import os
import stat
import tomllib
from pathlib import Path

import pytest

from plextui import config


def test_config_and_debug_paths_share_platformdirs_base(monkeypatch):
    monkeypatch.setattr(config, "user_config_dir", lambda app_name: f"/tmp/{app_name}")
    monkeypatch.setattr(config, "user_cache_dir", lambda app_name: f"/tmp/cache/{app_name}")

    assert config.config_path() == Path("/tmp/plex-tui/config.toml")
    assert config.cache_path() == Path("/tmp/cache/plex-tui")
    assert config.debug_log_path() == Path("/tmp/plex-tui/debug.log")


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission modes")
def test_config_permissions_are_owner_only_and_repaired(tmp_path, monkeypatch):
    config_file = tmp_path / "config" / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: config_file)
    saved = config.AppConfig("http://plex", "placeholder-token", "client")

    previous_umask = os.umask(0o022)
    try:
        config.save_config(saved)
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(config_file.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(config_file.stat().st_mode) == 0o600

    config_file.parent.chmod(0o755)
    config_file.chmod(0o644)

    assert config.load_config() == saved
    assert stat.S_IMODE(config_file.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(config_file.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission modes")
def test_debug_log_permissions_are_owner_only_and_repaired(tmp_path, monkeypatch):
    log = tmp_path / "config" / "debug.log"
    backup = tmp_path / "config" / "debug.log.1"
    monkeypatch.setattr(config, "debug_log_path", lambda: log)
    monkeypatch.setattr(config, "DEBUG_LOG_MAX_BYTES", 20)

    previous_umask = os.umask(0o022)
    try:
        config.write_debug_log("first message")
        config.write_debug_log("second message")
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(log.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600

    log.parent.chmod(0o755)
    log.chmod(0o644)
    backup.chmod(0o644)
    config.write_debug_log("third message")

    assert stat.S_IMODE(log.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


def test_debug_log_rotates_to_one_bounded_backup(tmp_path, monkeypatch):
    log = tmp_path / "debug.log"
    monkeypatch.setattr(config, "debug_log_path", lambda: log)
    monkeypatch.setattr(config, "DEBUG_LOG_MAX_BYTES", 20)

    config.write_debug_log("first message")
    config.write_debug_log("second message")

    backup = tmp_path / "debug.log.1"
    assert backup.read_text(encoding="utf-8") == "first message\n"
    assert log.read_text(encoding="utf-8") == "second message\n"

    config.write_debug_log("third message")

    assert backup.read_text(encoding="utf-8") == "second message\n"
    assert log.read_text(encoding="utf-8") == "third message\n"
    assert list(tmp_path.glob("debug.log.*")) == [backup]


def test_debug_log_caps_single_oversized_entries(tmp_path, monkeypatch):
    log = tmp_path / "debug.log"
    backup = tmp_path / "debug.log.1"
    monkeypatch.setattr(config, "debug_log_path", lambda: log)
    monkeypatch.setattr(config, "DEBUG_LOG_MAX_BYTES", 32)

    config.write_debug_log("x" * 200)
    config.write_debug_log("y" * 200)

    assert log.stat().st_size <= 32
    assert backup.stat().st_size <= 32
    assert log.read_bytes().endswith(config.DEBUG_LOG_TRUNCATION_MARKER)
    assert backup.read_bytes().endswith(config.DEBUG_LOG_TRUNCATION_MARKER)


def test_config_example_parses_and_uses_known_fields():
    example = Path("config.example.toml").read_text(encoding="utf-8")
    raw = tomllib.loads(example)

    assert set(raw) <= {
        "base_url",
        "token",
        "client_identifier",
        "account_token",
        "home_account_token",
        "active_profile_title",
        "server_identifier",
        "preferred_audio_language",
        "preferred_subtitle_language",
        "subtitle_mode",
        "mpv_window_size",
        "playback_mode",
        "playback_display",
        "terminal_video_output",
        "terminal_video_profile",
        "transcode_quality",
        "page_size",
        "auto_load_threshold",
        "grid_prefetch_pages",
        "hidden_library_keys",
        "library_order_keys",
        "show_playlists",
        "show_discover",
        "discover_media_type",
        "confirm_start_over",
        "artwork_mode",
        "artwork_renderer",
        "detail_artwork_mode",
        "grid_density",
        "media_view",
        "library_enter_action",
        "theme",
    }
    assert raw["base_url"]
    assert raw["token"]
    assert raw["client_identifier"]
    assert 'library_enter_action = "library"' in example


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
            'playback_mode = "bad"',
            'playback_display = "bad"',
            'terminal_video_output = "bad"',
            'terminal_video_profile = "bad"',
            'transcode_quality = "bad"',
            'page_size = "5"',
            'auto_load_threshold = "500"',
            'grid_prefetch_pages = "20"',
            'discover_media_type = "all"',
            "",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "config_path", lambda: config_file)
    monkeypatch.setattr(config, "debug_log_path", lambda: debug_file)

    loaded = config.load_config()

    assert loaded.subtitle_mode == "auto"
    assert loaded.mpv_window_size == ""
    assert loaded.playback_mode == "auto"
    assert loaded.playback_display == "external"
    assert loaded.terminal_video_output == "auto"
    assert loaded.terminal_video_profile == "smooth"
    assert loaded.transcode_quality == "original"
    assert loaded.page_size == config.DEFAULT_PAGE_SIZE
    assert loaded.auto_load_threshold == config.DEFAULT_AUTO_LOAD_THRESHOLD
    assert loaded.grid_prefetch_pages == config.DEFAULT_GRID_PREFETCH_PAGES
    assert loaded.discover_media_type == "movies_shows"
    log = debug_file.read_text(encoding="utf-8")
    assert "invalid subtitle_mode" in log
    assert "invalid mpv_window_size" in log
    assert "invalid playback_mode" in log
    assert "invalid playback_display" in log
    assert "invalid terminal_video_output" in log
    assert "invalid terminal_video_profile" in log
    assert "invalid transcode_quality" in log
    assert "invalid page_size" in log
    assert "invalid auto_load_threshold" in log
    assert "invalid grid_prefetch_pages" in log
    assert "invalid discover_media_type 'all'" in log


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
            'library_enter_action = "menu"',
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
    assert loaded.library_enter_action == "library"
    assert "invalid library_enter_action" in debug_file.read_text(encoding="utf-8")
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


def test_optional_plex_features_default_hidden(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '\n'.join([
            'base_url = "http://plex"',
            'token = "token"',
            'client_identifier = "client"',
            "",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "config_path", lambda: config_file)

    loaded = config.load_config()

    assert loaded.show_playlists is True
    assert loaded.show_discover is False
    assert loaded.show_on_plex is False
    assert loaded.show_on_plex_live is False


def test_enabled_optional_plex_features_round_trip(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: config_file)

    saved = config.AppConfig(
        "http://plex",
        "token",
        "client",
        show_discover=True,
        show_on_plex=True,
        show_on_plex_live=True,
    )
    config.save_config(saved)
    loaded = config.load_config()
    text = config_file.read_text(encoding="utf-8")

    assert loaded.show_discover is True
    assert loaded.show_on_plex is True
    assert loaded.show_on_plex_live is True
    assert "show_discover = true" in text
    assert "show_on_plex = true" in text
    assert "show_on_plex_live = true" in text


def test_mpv_window_size_round_trips_through_config(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: config_file)

    saved = config.AppConfig("http://plex", "token", "client", mpv_window_size="1280x720")
    config.save_config(saved)
    loaded = config.load_config()

    assert loaded.mpv_window_size == "1280x720"
    assert 'mpv_window_size = "1280x720"' in config_file.read_text(encoding="utf-8")


def test_playback_quality_settings_round_trip(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: config_file)

    saved = config.AppConfig(
        "http://plex",
        "token",
        "client",
        playback_mode="transcode",
        playback_display="terminal",
        terminal_video_output="kitty",
        terminal_video_profile="balanced",
        transcode_quality="720p_4",
    )
    config.save_config(saved)
    loaded = config.load_config()

    assert loaded.playback_mode == "transcode"
    assert loaded.playback_display == "terminal"
    assert loaded.terminal_video_output == "kitty"
    assert loaded.terminal_video_profile == "balanced"
    assert loaded.transcode_quality == "720p_4"
    text = config_file.read_text(encoding="utf-8")
    assert 'playback_mode = "transcode"' in text
    assert 'playback_display = "terminal"' in text
    assert 'terminal_video_output = "kitty"' in text
    assert 'terminal_video_profile = "balanced"' in text
    assert 'transcode_quality = "720p_4"' in text


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
        library_order_keys=("7", "2"),
        grid_density="large",
        server_identifier="server-a",
        hidden_library_keys_server_identifier="server-a",
        library_order_keys_server_identifier="server-a",
        show_playlists=False,
        show_discover=False,
        show_on_plex=False,
        show_on_plex_live=False,
        discover_media_type="show",
        confirm_start_over=False,
    )
    config.save_config(saved)
    loaded = config.load_config()

    assert loaded.page_size == 250
    assert loaded.auto_load_threshold == 25
    assert loaded.grid_prefetch_pages == 4
    assert loaded.hidden_library_keys == ("2", "7")
    assert loaded.library_order_keys == ("7", "2")
    assert loaded.hidden_library_keys_server_identifier == "server-a"
    assert loaded.library_order_keys_server_identifier == "server-a"
    assert loaded.grid_density == "large"
    assert loaded.show_playlists is False
    assert loaded.show_discover is False
    assert loaded.show_on_plex is False
    assert loaded.show_on_plex_live is False
    assert loaded.discover_media_type == "show"
    assert loaded.confirm_start_over is False
    text = config_file.read_text(encoding="utf-8")
    assert "page_size = 250" in text
    assert "auto_load_threshold = 25" in text
    assert "grid_prefetch_pages = 4" in text
    assert 'hidden_library_keys = "2,7"' in text
    assert 'library_order_keys = "7,2"' in text
    assert 'hidden_library_keys_server_identifier = "server-a"' in text
    assert 'library_order_keys_server_identifier = "server-a"' in text
    assert 'grid_density = "large"' in text
    assert "show_playlists = false" in text
    assert "show_discover" not in text
    assert "show_on_plex" not in text
    assert "show_on_plex_live" not in text
    assert 'discover_media_type = "show"' in text
    assert "confirm_start_over = false" in text


def test_home_account_token_only_saves_when_different_from_active_profile(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: config_file)

    config.save_config(config.AppConfig("http://plex", "server", "client", account_token="home", home_account_token="home"))
    assert "home_account_token" not in config_file.read_text(encoding="utf-8")

    saved = config.AppConfig(
        "http://plex",
        "server",
        "client",
        account_token="kid",
        home_account_token="home",
        active_profile_title="Kid",
        server_identifier="server-id",
    )
    config.save_config(saved)
    loaded = config.load_config()

    text = config_file.read_text(encoding="utf-8")
    assert 'account_token = "kid"' in text
    assert 'home_account_token = "home"' in text
    assert 'active_profile_title = "Kid"' in text
    assert 'server_identifier = "server-id"' in text
    assert loaded.account_token == "kid"
    assert loaded.home_account_token == "home"
    assert loaded.active_profile_title == "Kid"
    assert loaded.server_identifier == "server-id"


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


def test_legacy_library_preferences_attach_to_saved_server(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '\n'.join([
            'base_url = "http://plex"',
            'token = "token"',
            'client_identifier = "client"',
            'server_identifier = "server-a"',
            'hidden_library_keys = "2"',
            'library_order_keys = "2,1"',
            "",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "config_path", lambda: config_file)

    loaded = config.load_config()

    assert loaded.hidden_library_keys_server_identifier == "server-a"
    assert loaded.library_order_keys_server_identifier == "server-a"
    assert loaded.current_hidden_library_keys == ("2",)
    assert loaded.current_library_order_keys == ("2", "1")


def test_library_order_keys_parse_unique_csv_values(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '\n'.join([
            'base_url = "http://plex"',
            'token = "token"',
            'client_identifier = "client"',
            'library_order_keys = " 7,2,7, ,1 "',
            "",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "config_path", lambda: config_file)

    loaded = config.load_config()

    assert loaded.library_order_keys == ("7", "2", "1")


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
