from __future__ import annotations

from types import SimpleNamespace

from plextui.app import (
    BrowseState,
    LoadMoreRow,
    MediaGrid,
    MediaRow,
    context_hint,
    detail_artwork_enabled,
    effective_stream_preference_rows,
    format_offset,
    grid_status,
    media_row,
    media_rows,
    next_detail_artwork_mode,
    next_media_view,
    next_mpv_window_size,
    playback_exit_status,
    render_audio_playback_preference,
    render_details,
    render_help,
    render_picker_details,
    render_settings,
    render_subtitle_playback_preference,
    settings_rows,
    subtitle_preference_value,
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

    assert "Metadata" in rendered
    assert "Preferences" in rendered
    assert "Audio preference: jpn" in rendered
    assert "Subtitle mode: Preferred" in rendered
    assert "Artwork: available" in rendered
    assert "- Japanese (aac, 2ch, selected)" in rendered
    assert "- English (srt, selected)" in rendered
    assert "Summary text" in rendered


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
    assert subtitle_preference_value(config) == "eng"


def test_settings_rows_are_grouped_with_action_values():
    config = AppConfig(
        "http://plex",
        "token",
        "client-id",
        page_size=80,
        auto_load_threshold=20,
        mpv_window_size="1280x720",
    )

    labels = [getattr(row, "label_text") for row in settings_rows(config)]

    assert "[ Account ]" in labels
    assert "[ Streams ]" in labels
    assert "[ Playback ]" in labels
    assert "[ Artwork ]" in labels
    assert "[ Browsing ]" in labels
    assert "[ Diagnostics ]" in labels
    assert "mpv Window Size: 1280x720  [cycle]" in labels
    assert "Page Size: 80  [+10]" in labels
    assert "Auto-load Threshold: 20  [-5]" in labels


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


def test_render_subtitle_none_playback_status():
    config = AppConfig(
        base_url="http://plex",
        token="token",
        client_identifier="client-id",
        subtitle_mode="none",
    )

    assert render_subtitle_playback_preference(config, StreamChoice(0, "None")) == "subtitles none"


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
    assert "?: show help" in rendered


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

    assert "[resume 1m]" in row.label_text


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

    grid.set_selected_index(4)

    assert [item.key for item in grid.visible_page_items()] == ["4"]


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
