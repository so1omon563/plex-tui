from __future__ import annotations

from io import BytesIO
from subprocess import CompletedProcess, TimeoutExpired
from types import SimpleNamespace

from PIL import Image
from rich.align import Align
from rich.console import Group
from rich.text import Text

from plextui.app import (
    BrowseState,
    LoadMoreRow,
    MediaGrid,
    MediaRow,
    PlexTuiApp,
    card_artwork_pixel_size,
    context_hint,
    detect_mpv,
    detail_artwork_enabled,
    effective_stream_preference_rows,
    format_offset,
    grid_card_height,
    grid_card_width,
    grid_geometry_for_size,
    grid_page_key,
    grid_status,
    media_row,
    media_rows,
    next_detail_artwork_mode,
    next_artwork_renderer,
    next_grid_density,
    next_media_view,
    next_mpv_window_size,
    playback_failure_hints,
    playback_exit_status,
    recent_debug_log_lines,
    render_audio_playback_preference,
    render_card_artwork,
    render_app_diagnostics,
    render_debug_log_details,
    render_details,
    render_help,
    render_media_grid,
    render_media_grid_card,
    render_picker_details,
    render_playback_details,
    render_playback_error_details,
    render_settings_change_details,
    render_settings_row_details,
    render_settings,
    render_playback_status,
    render_subtitle_playback_preference,
    settings_rows,
    subtitle_preference_value,
    write_artwork_performance_log,
    write_performance_log,
)
from plextui.config import AppConfig
from plextui.models import MediaDetails, MediaItem
from plextui.player import StreamChoice


def test_format_offset():
    assert format_offset(65000) == "1:05"
    assert format_offset(3_665_000) == "1:01:05"


def test_playback_exit_status_describes_process_state():
    assert playback_exit_status(SimpleNamespace(title="Movie", process=SimpleNamespace(poll=lambda: None))) is None
    assert playback_exit_status(SimpleNamespace(title="Movie", process=SimpleNamespace(poll=lambda: 0))) == "Playback ended: Movie"
    assert playback_exit_status(SimpleNamespace(title="Movie", process=SimpleNamespace(poll=lambda: 2))) == (
        "Playback exited with code 2: Movie"
    )
    assert playback_exit_status(SimpleNamespace(title="Movie", process=SimpleNamespace(poll=lambda: -15))) == (
        "Playback terminated by signal 15: Movie"
    )
    assert playback_exit_status(
        SimpleNamespace(title="Movie", process=SimpleNamespace(poll=lambda: 2)),
        "/tmp/debug.log",
    ) == (
        "Playback exited with code 2: Movie. Debug log: /tmp/debug.log"
    )


def test_render_details_includes_subtitles_and_summary():
    details = MediaDetails(
        title="Title",
        kind="movie",
        facts=["movie"],
        metadata=[("Type", "movie")],
        audio=["Japanese (aac, 2ch, selected)"],
        subtitles=["English (srt, selected)"],
        summary="Summary text",
        playable=True,
        artwork_path="/library/metadata/1/thumb",
    )

    rendered = render_details(
        details,
        AppConfig(
            base_url="http://plex",
            token="token",
            client_identifier="client-id",
            preferred_audio_language="jpn",
            preferred_subtitle_language="eng",
            subtitle_mode="preferred",
        ),
    )

    assert "Title\n--------" in rendered
    assert "movie" in rendered
    assert "Playback\nStatus: Ready to play" in rendered
    assert "Metadata" in rendered
    assert "Preferences" in rendered
    assert "Audio: jpn" in rendered
    assert "Subtitles: Preferred / eng" in rendered
    assert "Artwork: available" in rendered
    assert "- Japanese (aac, 2ch, selected)" in rendered
    assert "- English (srt, selected)" in rendered
    assert "Summary text" in rendered


def test_render_details_uses_clear_empty_states_and_wraps_summary():
    details = MediaDetails(
        title="Long Movie",
        kind="movie",
        facts=[],
        metadata=[],
        audio=[],
        subtitles=[],
        summary="This is a very long summary that should wrap into shorter lines instead of rendering as one long pane-breaking paragraph in the details view.",
        playable=False,
    )

    rendered = render_details(details)

    assert "Status: Opens more items" in rendered
    assert "No metadata reported" in rendered
    assert "No audio tracks reported" in rendered
    assert "No subtitle tracks reported" in rendered
    summary_lines = rendered.split("Summary\n", 1)[1].splitlines()
    assert len(summary_lines) > 1
    assert all(len(line) <= 76 for line in summary_lines if line)


def test_render_settings_hides_tokens():
    config = AppConfig(
        base_url="http://plex",
        token="secret",
        account_token="account-secret",
        client_identifier="client-id",
    )

    rendered = render_settings(config)

    assert "secret" not in rendered
    assert "Server Token: saved" in rendered
    assert "Account Token: saved" in rendered
    assert "Cache Path:" in rendered
    assert "Debug Log:" in rendered


def test_render_settings_includes_stream_preferences():
    config = AppConfig(
        base_url="http://plex",
        token="token",
        account_token="account-token",
        client_identifier="client-id",
        preferred_audio_language="jpn",
        preferred_subtitle_language="eng",
        subtitle_mode="preferred",
        theme="textual-light",
        page_size=250,
        auto_load_threshold=25,
        grid_prefetch_pages=4,
    )

    rendered = render_settings(config)

    assert "Audio Preference: jpn" in rendered
    assert "Subtitle Mode: Preferred" in rendered
    assert "Subtitle Language: eng" in rendered
    assert "Artwork: On" in rendered
    assert "Artwork Renderer: Block" in rendered
    assert "Details Artwork: List only" in rendered
    assert "Media View: List" in rendered
    assert "Theme: textual-light" in rendered
    assert "mpv Window Size: Default" in rendered
    assert "Page Size: 250" in rendered
    assert "Auto-load Threshold: 25" in rendered
    assert "Grid Prefetch Pages: 4" in rendered
    assert "Show recent debug log" in rendered
    assert "Show app diagnostics" in rendered
    assert subtitle_preference_value(config) == "eng"


def test_settings_rows_are_grouped_with_action_values():
    config = AppConfig(
        "http://plex",
        "token",
        "client-id",
        page_size=80,
        auto_load_threshold=20,
        grid_prefetch_pages=4,
        mpv_window_size="1280x720",
    )

    labels = [getattr(row, "label_text") for row in settings_rows(config)]

    assert "[ Account ]" in labels
    assert "[ Streams ]" in labels
    assert "[ Playback ]" in labels
    assert "[ Artwork ]" in labels
    assert "[ Browsing ]" in labels
    assert "[ Diagnostics ]" in labels
    assert "Subtitle Mode: Auto  [cycle]" in labels
    assert "mpv Window Size: 1280x720  [input]" in labels
    assert "Grid Density: Comfortable  [cycle]" in labels
    assert "Artwork Renderer: Block  [cycle]" in labels
    assert "Page Size: 80 (range 25-500, step 10, default 40)  [input]" in labels
    assert "Auto-load Threshold: 20 (range 1-100, step 5, default 10)  [input]" in labels
    assert "Grid Prefetch Pages: 4 (range 0-5, step 1, default 3)  [input]" in labels
    assert "Show recent debug log  [show]" in labels
    assert "Show app diagnostics  [show]" in labels


def test_settings_row_details_describe_action_types():
    config = AppConfig("http://plex", "token", "client", page_size=80, grid_density="comfortable")
    rows = settings_rows(config)
    grid_row = next(row for row in rows if getattr(row, "action", "") == "cycle_grid_density")
    clear_row = next(row for row in rows if getattr(row, "action", "") == "clear_audio")
    input_row = next(row for row in rows if getattr(row, "action", "") == "set_page_size")
    value_row = next(row for row in rows if getattr(row, "label_text", "").startswith("Server:"))

    grid_details = render_settings_row_details(grid_row, config)
    assert "Setting Control" in grid_details
    assert "Grid Density" in grid_details
    assert "Type: cycle" in grid_details
    assert "Current grid density: Comfortable" in grid_details
    assert "Controls" in grid_details
    assert "Left/Right changes this setting without opening an input." in grid_details

    confirm_details = render_settings_row_details(clear_row, config, pending_confirmation_action="clear_audio")
    assert "Confirm Action" in confirm_details
    assert "Status: armed" in confirm_details
    assert "Press Enter on this same row again to confirm." in confirm_details

    input_details = render_settings_row_details(input_row, config)
    assert "Numeric Setting" in input_details
    assert "Current value: 80" in input_details
    assert "Left/Right adjusts by one step" in input_details

    value_details = render_settings_row_details(value_row, config)
    assert "Current Setting" in value_details
    assert "does not change on Enter" in value_details


def test_settings_change_details_show_saved_value_and_next_controls():
    config = AppConfig("http://plex", "token", "client", grid_density="large")

    rendered = render_settings_change_details("cycle_grid_density", "Grid density", "Large", config)

    assert "Setting Saved" in rendered
    assert "Current value: Large" in rendered
    assert "Current grid density: Large" in rendered
    assert "The changed row remains selected." in rendered
    assert "cycle compact, comfortable, and large grid layouts" in rendered


def test_detail_artwork_mode_defaults_to_list_only():
    list_config = AppConfig("http://plex", "token", "client-id")
    grid_config = AppConfig("http://plex", "token", "client-id", media_view="grid")

    assert detail_artwork_enabled(list_config)
    assert not detail_artwork_enabled(grid_config)
    assert detail_artwork_enabled(AppConfig("http://plex", "token", "client-id", media_view="grid", detail_artwork_mode="on"))
    assert not detail_artwork_enabled(AppConfig("http://plex", "token", "client-id", detail_artwork_mode="off"))
    assert next_detail_artwork_mode("list_only") == "on"
    assert next_detail_artwork_mode("on") == "off"
    assert next_detail_artwork_mode("off") == "list_only"


def test_render_playback_preference_status():
    config = AppConfig(
        base_url="http://plex",
        token="token",
        client_identifier="client-id",
        preferred_audio_language="jpn",
        preferred_subtitle_language="eng",
        subtitle_mode="preferred",
    )

    assert render_audio_playback_preference(config, None) == "audio jpn not found, Plex/default"
    assert render_subtitle_playback_preference(config, None) == "subtitles eng not found, Plex/default"
    assert render_audio_playback_preference(config, StreamChoice(1, "Japanese")) == "audio Japanese"
    assert render_subtitle_playback_preference(config, StreamChoice(2, "English")) == "subtitles English"


def test_next_artwork_renderer_cycles_values():
    assert next_artwork_renderer("block") == "auto"
    assert next_artwork_renderer("auto") == "kitty"
    assert next_artwork_renderer("kitty") == "block"
    assert next_artwork_renderer("bad") == "block"


def test_render_playback_status_includes_active_launch_context():
    config = AppConfig(
        base_url="http://plex",
        token="token",
        client_identifier="client-id",
        preferred_audio_language="jpn",
        preferred_subtitle_language="eng",
        subtitle_mode="preferred",
    )
    player = SimpleNamespace(start_offset_ms=65_000, stream_mode="direct", subtitle_count=2)

    rendered = render_playback_status(
        "Movie",
        player,
        config,
        StreamChoice(1, "Japanese"),
        StreamChoice(2, "English"),
    )

    assert rendered == (
        "Playing Movie / resume 1:05 / mode direct / 2 subtitles / audio Japanese; subtitles English"
    )


def test_render_playback_details_includes_streams_and_diagnostics():
    config = AppConfig(
        base_url="http://plex",
        token="token",
        client_identifier="client-id",
        preferred_audio_language="jpn",
        preferred_subtitle_language="eng",
        subtitle_mode="preferred",
        mpv_window_size="1280x720",
    )
    player = SimpleNamespace(start_offset_ms=0, stream_mode="transcode", subtitle_count=1)

    rendered = render_playback_details(
        "Episode",
        player,
        config,
        StreamChoice(1, "Japanese"),
        StreamChoice(2, "English"),
    )

    assert "Playback" in rendered
    assert "Status: Playing" in rendered
    assert "Mode: transcode" in rendered
    assert "Resume: start" in rendered
    assert "Subtitles available: 1" in rendered
    assert "mpv window: 1280x720" in rendered
    assert "Audio: Japanese" in rendered
    assert "Subtitles: English" in rendered
    assert "Debug log:" in rendered
    assert "Show recent debug log" in rendered


def test_recent_debug_log_lines_handles_missing_empty_and_tail(tmp_path):
    missing = tmp_path / "missing.log"
    assert recent_debug_log_lines(missing) == []

    log = tmp_path / "debug.log"
    log.write_text("", encoding="utf-8")
    assert recent_debug_log_lines(log) == []

    log.write_text("\n".join(f"line {index}" for index in range(5)), encoding="utf-8")
    assert recent_debug_log_lines(log, max_lines=2) == ["line 3", "line 4"]
    assert recent_debug_log_lines(log, max_lines=0) == []


def test_render_debug_log_details_reports_recent_entries(tmp_path):
    log = tmp_path / "debug.log"
    log.write_text("first\nsecond\nthird\n", encoding="utf-8")

    rendered = render_debug_log_details(log, max_lines=2)

    assert "Recent Debug Log" in rendered
    assert f"Path: {log}" in rendered
    assert "Last 2 lines" in rendered
    assert "first" not in rendered
    assert "second" in rendered
    assert "third" in rendered


def test_render_debug_log_details_handles_missing_log(tmp_path):
    log = tmp_path / "debug.log"

    rendered = render_debug_log_details(log)

    assert "No debug log entries yet." in rendered
    assert f"Path: {log}" in rendered


def test_render_app_diagnostics_summarizes_runtime_state(monkeypatch, tmp_path):
    monkeypatch.setattr("plextui.app.config_path", lambda: tmp_path / "config.toml")
    monkeypatch.setattr("plextui.app.cache_path", lambda: tmp_path / "cache")
    monkeypatch.setattr("plextui.app.debug_log_path", lambda: tmp_path / "debug.log")
    config = AppConfig(
        "http://plex",
        "token",
        "client-id",
        account_token="account-token",
        preferred_audio_language="jpn",
        subtitle_mode="none",
        artwork_renderer="block",
        grid_density="large",
        page_size=80,
        auto_load_threshold=20,
        grid_prefetch_pages=4,
        mpv_window_size="1280x720",
    )

    rendered = render_app_diagnostics(config, ("/usr/bin/mpv", "mpv 0.40.0"))

    assert "App Diagnostics" in rendered
    assert "Version:" in rendered
    assert f"Config: {tmp_path / 'config.toml'}" in rendered
    assert "Server token: saved" in rendered
    assert "Account token: saved" in rendered
    assert "mpv: /usr/bin/mpv" in rendered
    assert "mpv version: mpv 0.40.0" in rendered
    assert "Audio preference: jpn" in rendered
    assert "Subtitle mode: None" in rendered
    assert "Grid density: Large" in rendered
    assert "Grid prefetch pages: 4" in rendered
    assert "Renderer status: Block art" in rendered


def test_render_app_diagnostics_includes_mpv_hints_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("plextui.app.config_path", lambda: tmp_path / "config.toml")
    monkeypatch.setattr("plextui.app.cache_path", lambda: tmp_path / "cache")
    monkeypatch.setattr("plextui.app.debug_log_path", lambda: tmp_path / "debug.log")
    config = AppConfig("http://plex", "token", "client-id")

    rendered = render_app_diagnostics(config, ("missing", "mpv was not found on PATH"))

    assert "App Diagnostics" in rendered
    assert "Install mpv:" in rendered
    assert "brew install mpv" in rendered
    assert "sudo apt install mpv" in rendered
    assert "sudo pacman -S mpv" in rendered


def test_detect_mpv_reports_missing_found_and_failed(monkeypatch):
    monkeypatch.setattr("plextui.app.shutil.which", lambda command: None)
    assert detect_mpv() == ("missing", "mpv was not found on PATH")

    monkeypatch.setattr("plextui.app.shutil.which", lambda command: "/usr/bin/mpv")
    monkeypatch.setattr(
        "plextui.app.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 0, stdout="mpv 0.40.0\nCopyright", stderr=""),
    )
    assert detect_mpv() == ("/usr/bin/mpv", "mpv 0.40.0")

    def timeout(*args, **kwargs):
        raise TimeoutExpired(args[0], 2)

    monkeypatch.setattr("plextui.app.subprocess.run", timeout)
    path, message = detect_mpv()
    assert path == "/usr/bin/mpv"
    assert "version check failed" in message


def test_render_playback_error_details_includes_recent_debug_log(tmp_path):
    log = tmp_path / "debug.log"
    log.write_text("launching mpv\nplayback error: failed\n", encoding="utf-8")

    rendered = render_playback_error_details("failed to launch mpv", log, max_lines=1)

    assert "Playback Error" in rendered
    assert "Cause" in rendered
    assert "failed to launch mpv" in rendered
    assert f"Debug log: {log}" in rendered
    assert "mpv launch command" in rendered
    assert "Suggested Next Steps" in rendered
    assert "mpv launch failed:" in rendered
    assert "launching mpv" not in rendered
    assert "playback error: failed" in rendered


def test_playback_failure_hints_cover_common_failures():
    missing = playback_failure_hints("mpv was not found in PATH")
    assert "Install mpv:" in missing
    assert "brew install mpv" in "\n".join(missing)

    plex = playback_failure_hints("could not get stream URL from Plex: 401")
    assert "Plex did not provide a stream URL:" in plex
    assert "saved token still works" in "\n".join(plex)

    empty = playback_failure_hints("Plex returned an empty stream URL")
    assert "Plex returned an empty stream URL:" in empty
    assert "Plex can play the item" in "\n".join(empty)

    subtitles = playback_failure_hints("playback error: failed loading --sub-file")
    assert "Subtitle playback may be involved:" in subtitles
    assert "Subtitle Mode: none" in "\n".join(subtitles)

    exited = playback_failure_hints("Playback exited with code 2: Movie")
    assert "mpv exited abnormally:" in exited
    assert "raw mpv output" in "\n".join(exited)


def test_effective_stream_preferences_report_found_missing_and_none():
    class Stream:
        def __init__(self, stream_id, label, language_code):
            self.id = stream_id
            self.displayTitle = label
            self.languageCode = language_code

    class Part:
        def audioStreams(self):
            return [Stream(1, "Japanese", "jpn")]

        def subtitleStreams(self):
            return [Stream(2, "English", "eng")]

    class Raw:
        def iterParts(self):
            return [Part()]

    found = AppConfig("http://plex", "token", "client", preferred_audio_language="jpn", preferred_subtitle_language="eng", subtitle_mode="preferred")
    missing = AppConfig("http://plex", "token", "client", preferred_audio_language="spa", preferred_subtitle_language="fre", subtitle_mode="preferred")
    none = AppConfig("http://plex", "token", "client", subtitle_mode="none")

    assert effective_stream_preference_rows(Raw(), found) == [("Audio", "Japanese"), ("Subtitles", "English")]
    assert effective_stream_preference_rows(Raw(), missing) == [
        ("Audio", "spa not found, Plex/default"),
        ("Subtitles", "fre not found, Plex/default"),
    ]
    assert effective_stream_preference_rows(Raw(), none) == [("Audio", "Plex/default"), ("Subtitles", "none")]


def test_render_details_includes_effective_playback_rows():
    details = MediaDetails(
        title="Title",
        kind="movie",
        facts=["movie"],
        metadata=[],
        audio=[],
        subtitles=[],
        summary="",
        playable=True,
    )

    rendered = render_details(details, AppConfig("http://plex", "token", "client", subtitle_mode="none"), object())

    assert "Effective Playback" in rendered
    assert "Subtitles: none" in rendered


def test_picker_details_explain_global_save():
    rendered = render_picker_details("audio", StreamChoice(1, "Japanese"), AppConfig("http://plex", "token", "client"))

    assert "Current Selection" in rendered
    assert "Enter saves the highlighted track as the global preference" in rendered


def test_mpv_window_size_cycles_common_values():
    assert next_mpv_window_size("") == "1280x720"
    assert next_mpv_window_size("1280x720") == "1600x900"
    assert next_mpv_window_size("80%") == ""


def test_grid_density_cycles_and_changes_card_width():
    assert next_grid_density("comfortable") == "large"
    assert next_grid_density("large") == "compact"
    assert next_grid_density("compact") == "comfortable"
    assert grid_card_width(AppConfig("http://plex", "token", "client", grid_density="compact")) < grid_card_width(
        AppConfig("http://plex", "token", "client", grid_density="large")
    )


def test_grid_geometry_uses_density_at_common_terminal_sizes():
    compact = AppConfig("http://plex", "token", "client", grid_density="compact")
    comfortable = AppConfig("http://plex", "token", "client", grid_density="comfortable")
    large = AppConfig("http://plex", "token", "client", grid_density="large")

    assert grid_geometry_for_size(58, 24, compact) == (2, 2)
    assert grid_geometry_for_size(58, 24, comfortable) == (2, 1)
    assert grid_geometry_for_size(58, 24, large) == (1, 1)
    assert grid_geometry_for_size(138, 34, compact) == (6, 3)
    assert grid_geometry_for_size(138, 34, comfortable) == (5, 2)
    assert grid_geometry_for_size(138, 34, large) == (4, 2)


def test_card_artwork_pixel_size_tracks_terminal_render_size():
    assert card_artwork_pixel_size(AppConfig("http://plex", "token", "client", grid_density="comfortable")) == (18, 18)
    assert card_artwork_pixel_size(AppConfig("http://plex", "token", "client", grid_density="large")) == (24, 24)


def test_render_card_artwork_uses_per_line_renderables():
    image = Image.new("RGB", (2, 4), "#ff0000")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    rendered = render_card_artwork(buffer.getvalue(), AppConfig("http://plex", "token", "client", grid_density="compact"))

    assert isinstance(rendered, Group)
    assert all(isinstance(line, Text) for line in rendered.renderables)


def test_render_subtitle_none_playback_status():
    config = AppConfig(
        base_url="http://plex",
        token="token",
        client_identifier="client-id",
        subtitle_mode="none",
    )

    assert render_subtitle_playback_preference(config, StreamChoice(0, "None")) == "subtitles none"


def test_grid_card_selected_style_uses_marker_without_heavy_border():
    media = MediaItem("Movie", "2024", "movie", "1", True, object(), artwork_path="")

    selected = render_media_grid_card(media, True, AppConfig("http://plex", "token", "client"))
    unselected = render_media_grid_card(media, False, AppConfig("http://plex", "token", "client"))

    selected_text = "\n".join(str(renderable) for renderable in selected.renderables)
    unselected_text = "\n".join(str(renderable) for renderable in unselected.renderables)
    assert "Movie" in selected_text
    assert "▶ selected" in selected_text
    assert "┏" not in selected_text
    assert "▶ selected" not in unselected_text


def test_grid_rows_are_centered_in_media_pane():
    media = MediaItem("Movie", "2024", "movie", "1", True, object(), artwork_path="")
    rendered = render_media_grid([media], media.key, AppConfig("http://plex", "token", "client"), columns=2)

    assert isinstance(rendered.renderables[0], Align)


def test_grid_card_placeholder_matches_artwork_height():
    media = MediaItem("Movie", "2024", "movie", "1", True, object(), artwork_path="")
    config = AppConfig("http://plex", "token", "client", grid_density="compact")

    rendered = render_media_grid_card(media, False, config)

    placeholder = rendered.renderables[0]
    assert isinstance(placeholder, Group)
    assert len(placeholder.renderables) == grid_card_height(config) - 3
    assert any("[no poster]" in str(line) for line in placeholder.renderables)


def test_grid_card_text_and_placeholder_are_card_width():
    media = MediaItem("A Movie", "2024", "movie", "1", True, object(), artwork_path="")
    config = AppConfig("http://plex", "token", "client", grid_density="compact")

    rendered = render_media_grid_card(media, True, config)

    width = grid_card_width(config)
    placeholder = rendered.renderables[0]
    assert all(len(line.plain) == width for line in placeholder.renderables)
    assert len(rendered.renderables[1].plain) == width
    assert len(rendered.renderables[2].plain) == width
    assert len(rendered.renderables[3].plain) == width


def test_grid_card_copies_cached_artwork_renderable():
    media = MediaItem("Movie", "2024", "movie", "1", True, object(), artwork_path="/thumb")
    artwork = Group(Text("line 1"), Text("line 2"))

    rendered = render_media_grid_card(media, False, AppConfig("http://plex", "token", "client"), {"1": artwork})

    assert isinstance(rendered.renderables[0], Group)
    assert rendered.renderables[0] is not artwork
    assert rendered.renderables[0].renderables[0] is not artwork.renderables[0]
    assert rendered.renderables[0].renderables[0].plain.strip() == "line 1"


def test_render_help_groups_key_bindings():
    rendered = render_help()

    assert "Navigation" in rendered
    assert "Search" in rendered
    assert "Playback" in rendered
    assert "Streams" in rendered
    assert "Settings" in rendered
    assert "Paths" in rendered
    assert "Debug log:" in rendered
    assert "v: toggle list/grid view" in rendered
    assert "left/right: move across grid cards" in rendered
    assert "PLEX_TUI_ARTWORK_LOG=1" in rendered
    assert "?: show help" in rendered


def test_performance_log_requires_perf_env(monkeypatch):
    messages = []
    monkeypatch.delenv("PLEX_TUI_PERF_LOG", raising=False)
    monkeypatch.setattr("plextui.app.write_debug_log", messages.append)

    write_performance_log("event", 0.0, "detail")

    assert messages == []


def test_artwork_performance_log_requires_artwork_env(monkeypatch):
    messages = []
    monkeypatch.setenv("PLEX_TUI_PERF_LOG", "1")
    monkeypatch.delenv("PLEX_TUI_ARTWORK_LOG", raising=False)
    monkeypatch.setattr("plextui.app.write_debug_log", messages.append)

    write_artwork_performance_log("grid_render", 0.0, "items=1")
    assert messages == []

    monkeypatch.setenv("PLEX_TUI_ARTWORK_LOG", "1")
    write_artwork_performance_log("grid_render", 0.0, "items=1")
    assert len(messages) == 1
    assert "perf grid_render" in messages[0]


def test_media_rows_returns_list_rows():
    items = [
        MediaItem(f"Movie {index}", "2024", "movie", str(index), True, object(), artwork_path="/thumb")
        for index in range(5)
    ]
    config = AppConfig(
        base_url="http://plex",
        token="token",
        client_identifier="client-id",
        media_view="grid",
    )

    rows, selected_row = media_rows(items, config, selected_index=3)

    assert len(rows) == 5
    assert selected_row == 3
    assert isinstance(rows[0], MediaRow)
    assert next_media_view("list") == "grid"
    assert next_media_view("grid") == "list"


def test_media_row_includes_progress_marker():
    class PartialRaw:
        viewOffset = 65000
        duration = 600000

    row = MediaRow(MediaItem("Movie", "2024", "movie", "1", True, PartialRaw()))

    assert row.label_text.startswith("▶ Movie")
    assert "[resume 1m]" in row.label_text


def test_media_row_marks_container_items():
    row = MediaRow(MediaItem("Show", "2 seasons", "show", "1", False, object()))

    assert row.label_text.startswith("› Show")


def test_media_grid_tracks_selection_and_visible_page():
    items = [
        MediaItem(f"Movie {index}", "2024", "movie", str(index), True, object(), artwork_path="/thumb")
        for index in range(5)
    ]
    config = AppConfig("http://plex", "token", "client", media_view="grid")
    grid = MediaGrid()

    grid.set_items(items, selected_index=3, config=config, columns=2, rows=2)
    grid.set_artwork("3", "art")

    assert grid.selected_media is not None
    assert grid.selected_media.key == "3"
    assert grid.artwork["3"] == "art"
    assert [item.key for item in grid.visible_page_items()] == ["0", "1", "2", "3"]
    assert [item.key for item in grid.visible_page_items(page_offset=1)] == ["4"]
    assert grid_page_key(grid.visible_page_items()) == ("0", "1", "2", "3")

    grid.set_selected_index(4)

    assert [item.key for item in grid.visible_page_items()] == ["4"]


def test_media_grid_visible_handles_unmounted_app():
    assert not PlexTuiApp().media_grid_visible()


def test_media_grid_page_status_counts_loaded_items():
    items = [
        MediaItem(f"Movie {index}", "2024", "movie", str(index), True, object(), artwork_path="/thumb")
        for index in range(12)
    ]
    config = AppConfig("http://plex", "token", "client", media_view="grid")
    grid = MediaGrid()
    grid.set_items(items, selected_index=7, config=config, columns=2, rows=2)
    state = BrowseState("Movies", items, total=30)

    assert "item 8" in grid_status(grid, state)
    assert "page 2 of 3" in grid_status(grid, state)
    assert "12 of 30 loaded" in grid_status(grid, state)


def test_context_hints_for_media_and_load_more():
    playable = MediaItem("Movie", "", "movie", "1", True, object())
    grid = MediaGrid()
    grid.set_items([playable], selected_index=0, config=AppConfig("http://plex", "token", "client"), columns=1)

    assert context_hint(MediaRow(playable)) == "Enter selects item / p plays / a audio / s subtitles"
    assert context_hint(grid) == "Arrows/page select card / p plays / a audio / s subtitles"
    assert context_hint(LoadMoreRow(100, 200)) == "Enter loads next page"
