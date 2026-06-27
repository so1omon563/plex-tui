from __future__ import annotations

from io import BytesIO
from subprocess import CompletedProcess, TimeoutExpired
from types import SimpleNamespace

from PIL import Image
from rich.align import Align
from rich.console import Console, Group
from rich.text import Text

from plextui.artwork import KittyImage
from plextui.app import (
    alphabet_group_label,
    alphabet_jump_index,
    alphabet_section_groups,
    BrowseState,
    ContinueWatchingRow,
    EmptyStateRow,
    LoadMoreRow,
    LibraryRow,
    LibraryMenuRow,
    MediaGrid,
    MediaRow,
    OnPlexRow,
    PlaylistsRow,
    PlaylistCreateRow,
    PlaylistTargetRow,
    PlexTuiApp,
    UI_GRID_DIM,
    UI_GRID_MUTED,
    UI_GRID_TITLE,
    UI_SELECTED_ACCENT,
    card_artwork_fetch_size,
    context_hint,
    current_detail_actions,
    detect_mpv,
    detail_artwork_enabled,
    DiscoverRow,
    effective_stream_preference_rows,
    format_offset,
    fuzzy_match_media,
    grid_card_height,
    grid_card_title_lines,
    grid_card_width,
    grid_geometry_for_size,
    grid_artwork_cache_key,
    grid_items_are_collection_cards,
    grid_page_key,
    grid_status,
    library_menu_rows,
    media_row,
    media_row_status,
    media_rows,
    next_detail_artwork_mode,
    next_artwork_renderer,
    next_grid_density,
    next_media_view,
    next_mpv_window_size,
    next_playback_display,
    next_playback_mode,
    next_terminal_video_profile,
    next_transcode_quality,
    playback_failure_hints,
    playback_exit_status,
    recent_debug_log_lines,
    render_audio_playback_preference,
    render_browse_status,
    render_card_artwork,
    render_app_diagnostics,
    render_debug_log_details,
    render_details,
    render_empty_state_details,
    render_error_state_details,
    render_help,
    render_loading_state_details,
    render_media_grid,
    render_media_grid_card,
    render_picker_details,
    render_playlist_create_details,
    render_playlist_picker_details,
    render_playlist_target_details,
    render_playback_details,
    render_playback_error_details,
    render_settings_change_details,
    render_settings_row_details,
    render_settings,
    render_playback_status,
    render_subtitle_playback_preference,
    settings_rows,
    sidebar_rows,
    subtitle_preference_value,
    ordered_libraries,
    visible_libraries,
    write_alphabet_jump_log,
    write_artwork_performance_log,
    write_performance_log,
)
from plextui.config import AppConfig
from plextui.models import LibraryItem, MediaDetails, MediaItem
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
        facts=["Movie"],
        metadata=[("Type", "movie"), ("Progress", "1m / 10m (11%)")],
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

    assert "Title\n\nMovie\n1m / 10m (11%)" in rendered
    assert "====" not in rendered
    assert "Movie" in rendered
    assert "Playback\nReady to play" in rendered
    assert "Resume from 1m / 10m (11%)" in rendered
    assert "Press p to play from beginning" in rendered
    assert "Press r to resume saved progress" in rendered
    assert "Press o to play optimized stream" in rendered
    assert "Press P to add to a playlist" in rendered
    assert "Catalog" in rendered
    assert "Technical" in rendered
    assert "Audio preference jpn" in rendered
    assert "Subtitles Preferred / eng" in rendered
    assert "Artwork: available" in rendered
    assert "Audio Tracks (1)" in rendered
    assert "Subtitle Tracks (1)" in rendered
    assert "- Japanese (aac, 2ch, selected)" in rendered
    assert "- English (srt, selected)" in rendered
    assert "Summary text" in rendered
    assert rendered.index("Summary") < rendered.index("Catalog")
    assert rendered.index("Catalog") < rendered.index("Technical")


def test_render_details_avoids_ready_to_play_for_online_provider_items():
    details = MediaDetails(
        title="Online Episode",
        kind="episode",
        facts=["Episode"],
        metadata=[("Type", "episode")],
        audio=[],
        subtitles=[],
        summary="",
        playable=True,
    )

    rendered = render_details(
        details,
        AppConfig("http://plex", "token", "client-id"),
        context_actions=("Availability: Listed by Plex; playable stream checked on play",),
    )

    assert "Listed by Plex; stream checked on play" in rendered
    assert "Ready to play" not in rendered


def test_render_details_skips_effective_playback_for_playlist_container():
    class RawPlaylist:
        TYPE = "playlist"
        title = "Test list"
        duration = 6_360_000

        def iterParts(self):
            raise AttributeError("'Playlist' object has no attribute 'media'")

    details = MediaDetails(
        title="Test list",
        kind="playlist",
        facts=["Playlist", "1h 46m"],
        metadata=[("Type", "playlist")],
        audio=[],
        subtitles=[],
        summary="",
        playable=False,
        artwork_path="/playlists/1/composite/1",
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
        raw=RawPlaylist(),
    )

    assert "Playback\nOpens more items" in rendered
    assert "Press Enter to open" in rendered
    assert "Effective Playback" not in rendered
    assert "Technical" in rendered
    assert rendered.index("Technical") < rendered.index("Streams")
    assert "Streams\nAudio:     none reported" in rendered
    assert "Subtitles: none reported" in rendered


def test_render_details_can_include_playlist_context_action():
    details = MediaDetails(
        title="Movie",
        kind="movie",
        facts=["Movie"],
        metadata=[("Type", "movie")],
        audio=[],
        subtitles=[],
        summary="",
        playable=True,
    )

    rendered = render_details(
        details,
        AppConfig("http://plex", "token", "client-id"),
        context_actions=("Playlist: Backspace/Delete removes from this playlist",),
    )

    assert "Press P to add to a playlist" in rendered
    assert "Playlist: Backspace/Delete removes from this playlist" in rendered


def test_render_details_can_show_discover_availability_action():
    class Raw:
        def streamingServices(self):
            return [SimpleNamespace(title="Plex", offerType="free", url="https://watch.plex.tv/movie")]

    item = MediaItem("Movie", "", "movie", "1", False, Raw())
    state = BrowseState("Discover: Movie", [item], source="discover")
    details = MediaDetails(
        title="Movie",
        kind="movie",
        facts=["Movie"],
        metadata=[("Type", "movie")],
        audio=[],
        subtitles=[],
        summary="",
        playable=False,
    )

    rendered = render_details(
        details,
        context_actions=("Availability: Enter opens provider link",),
    )

    assert "Opens availability provider" in rendered
    assert "Press Enter to choose or open" in rendered
    assert "Availability: Enter opens provider link" in rendered
    assert "Opens more items" not in rendered
    assert current_detail_actions(state, item) == ("Availability: Enter opens provider link",)


def test_render_details_can_show_missing_discover_availability():
    class Raw:
        def streamingServices(self):
            return []

    item = MediaItem("Movie", "", "movie", "1", False, Raw())
    state = BrowseState("Discover: Movie", [item], source="discover")
    details = MediaDetails(
        title="Movie",
        kind="movie",
        facts=["Movie"],
        metadata=[("Type", "movie")],
        audio=[],
        subtitles=[],
        summary="",
        playable=False,
    )

    rendered = render_details(
        details,
        context_actions=current_detail_actions(state, item),
    )

    assert "No availability provider" in rendered
    assert "Availability: No provider links found" in rendered
    assert "Opens more items" not in rendered
    assert current_detail_actions(state, item) == ("Availability: No provider links found",)


def test_render_details_promotes_episode_context_under_title():
    details = MediaDetails(
        title="Band of the Hawk",
        kind="episode",
        facts=["Episode", "1997", "23m", "in progress", "TV-MA", "Rating 7.4", "2 subtitles"],
        metadata=[
            ("Type", "episode"),
            ("Year", "1997"),
            ("Duration", "23m"),
            ("Status", "in progress"),
            ("Episode", "S01E02"),
            ("Content Rating", "TV-MA"),
            ("Rating", "7.4"),
            ("Show", "Berserk"),
            ("Season", "Season 1"),
        ],
        audio=[],
        subtitles=[],
        summary="",
        playable=True,
    )

    rendered = render_details(details)

    assert "Band of the Hawk\nBerserk - Season 1 - S01E02\n\nEpisode" in rendered
    assert "====" not in rendered
    assert "1997 • 23m • TV-MA" in rendered
    assert rendered.index("Berserk - Season 1 - S01E02") < rendered.index("Production")
    assert "in progress / S01E02" not in rendered
    assert "Episode Context" not in rendered
    assert "Show: Berserk" not in rendered
    assert "Season: Season 1" not in rendered
    catalog = rendered.split("Catalog\n", 1)[1].split("\n\n", 1)[0]
    assert "Episode: S01E02" not in catalog


def test_render_details_uses_clear_empty_states_and_wraps_summary():
    details = MediaDetails(
        title="A Long Movie Title That Should Stay Inside The Details Pane",
        kind="movie",
        facts=["Movie", "2024", "a very long studio name that should wrap with the facts line"],
        metadata=[],
        audio=[],
        subtitles=[],
        summary="This is a very long summary that should wrap into shorter lines instead of rendering as one long pane-breaking paragraph in the details view.",
        playable=False,
    )

    rendered = render_details(details)

    assert "Opens more items" in rendered
    assert "Press Enter to open" in rendered
    assert "No metadata reported" in rendered
    assert "Audio:     none reported" in rendered
    assert "Subtitles: none reported" in rendered
    assert all(len(line) <= 38 for line in rendered.splitlines())
    summary_lines = rendered.split("Summary\n", 1)[1].splitlines()
    assert len(summary_lines) > 1
    assert all(len(line) <= 38 for line in summary_lines if line)


def test_empty_loading_and_error_state_details_are_actionable():
    empty = render_empty_state_details("Continue Watching", "Nothing in progress", "Start playback from a library item.")
    loading = render_loading_state_details("Movies", "Loading library items from Plex.")
    error = render_error_state_details("Plex Error", "connection failed", "Config: /tmp/config.toml", "Relogin with Plex.")
    row = EmptyStateRow("Nothing in progress", "Start playback from a library item.")

    assert "Empty View" in empty
    assert "Nothing in progress" in empty
    assert "Next Step\nStart playback from a library item." in empty
    assert "✦ Loading\nMovies" in loading
    assert "Loading library items from Plex." in loading
    assert "Cause\nconnection failed" in error
    assert "Diagnostics\nConfig: /tmp/config.toml" in error
    assert context_hint(row) == "Start playback from a library item."


def test_render_details_limits_dense_stream_lists_and_wraps_rows():
    details = MediaDetails(
        title="Movie",
        kind="movie",
        facts=["Movie"],
        metadata=[("Studio", "A very long studio name that should wrap cleanly inside the details pane")],
        audio=[f"Audio Track {index} with a long descriptive label" for index in range(7)],
        subtitles=[f"Subtitle Track {index} with a long descriptive label" for index in range(6)],
        summary="",
        playable=True,
    )

    rendered = render_details(details)

    assert "Audio Tracks (7)" in rendered
    assert "Subtitle Tracks (6)" in rendered
    assert "... 2 more" in rendered
    assert "... 1 more" in rendered
    assert "Audio Track 5" not in rendered
    assert "Subtitle Track 5" not in rendered
    assert all(len(line) <= 38 for line in rendered.splitlines())


def test_render_settings_hides_tokens():
    config = AppConfig(
        base_url="http://plex",
        token="secret",
        account_token="account-secret",
        client_identifier="client-id",
    )

    rendered = render_settings(config)

    assert "secret" not in rendered
    assert "Server Token:  saved" in rendered
    assert "Account Token: saved" in rendered
    assert "Home Token:    saved" in rendered
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

    assert "Audio Preference:  jpn" in rendered
    assert "Subtitle Mode:     Preferred" in rendered
    assert "Subtitle Language: eng" in rendered
    assert "Artwork:          On" in rendered
    assert "Artwork Renderer: Block" in rendered
    assert "Details Artwork:  List only" in rendered
    assert "Media View:          List" in rendered
    assert "Theme:       textual-light" in rendered
    assert "mpv Window Size:   Default (80%)" in rendered
    assert "Playback Mode:     Auto / direct" in rendered
    assert "default" in rendered
    assert "Playback Display:  External mpv window" in rendered
    assert "Terminal Video:    Smooth (15 fps /" in rendered
    assert "Transcode Quality: Original" in rendered
    assert "Page Size:           250" in rendered
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

    assert "Account" in labels
    assert "Streams" in labels
    assert "Playback" in labels
    assert "Artwork" in labels
    assert "Browsing" in labels
    assert "Diagnostics" in labels
    assert "  Server: http://plex" in labels
    assert "  Home Token: not set" in labels
    assert "› Switch Plex profile  (run)" in labels
    assert "› Subtitle Mode: Auto  (cycle)" in labels
    assert "› Playback Mode: Auto / direct default  (cycle)" in labels
    assert "› Playback Display: External mpv window  (cycle)" in labels
    assert "› Start Over Prompt: Shown  (toggle)" in labels
    assert "› Terminal Video: Smooth (15 fps / 640px)  (cycle)" in labels
    assert "› Transcode Quality: Original  (cycle)" in labels
    assert "› mpv Window Size: 1280x720  (cycle)" in labels
    assert "› Set custom mpv window size  (edit)" in labels
    assert "› Library Enter: Library  (cycle)" in labels
    assert "› Playlists Sidebar: Shown  (toggle)" in labels
    assert "› Discover Sidebar: Shown  (toggle)" in labels
    assert "› On Plex Sidebar: Shown  (toggle)" in labels
    assert "› Discover Type: Movies & Shows  (cycle)" in labels
    assert "› Grid Density: Comfortable  (cycle)" in labels
    assert "› Artwork Renderer: Block  (cycle)" in labels
    assert "› Page Size: 80  (edit)" in labels
    assert "› Auto-load Threshold: 20  (edit)" in labels
    assert "› Grid Prefetch Pages: 4  (edit)" in labels
    assert "› Show recent debug log  (show)" in labels
    assert "› Show app diagnostics  (show)" in labels


def test_settings_rows_include_library_visibility_toggles():
    config = AppConfig(
        "http://plex",
        "token",
        "client-id",
        hidden_library_keys=("2",),
        library_order_keys=("2", "1"),
    )
    libraries = [
        LibraryItem("Movies", "1", "movie", object()),
        LibraryItem("TV", "2", "show", object()),
    ]

    labels = [getattr(row, "label_text") for row in settings_rows(config, libraries)]

    assert "Libraries" in labels
    assert "› TV: Hidden  (toggle)" in labels
    assert "› TV: Move up  (step)" in labels
    assert "› TV: Move down  (step)" in labels
    assert "› Movies: Visible  (toggle)" in labels
    assert "› Movies: Move up  (step)" in labels
    assert "› Movies: Move down  (step)" in labels
    assert labels.index("› TV: Hidden  (toggle)") < labels.index("› Movies: Visible  (toggle)")


def test_settings_rows_disambiguate_duplicate_library_names():
    config = AppConfig("http://plex", "token", "client-id")
    libraries = [
        LibraryItem("Movies", "1", "movie", object()),
        LibraryItem("Movies", "7", "movie", object()),
        LibraryItem("TV", "2", "show", object()),
    ]

    labels = [getattr(row, "label_text") for row in settings_rows(config, libraries)]

    assert "  Sidebar visibility: None" in labels
    assert "› Movies (movie #1): Visible  (toggle)" in labels
    assert "› Movies (movie #7): Visible  (toggle)" in labels
    assert "› TV: Visible  (toggle)" in labels


def test_visible_libraries_filters_hidden_keys():
    config = AppConfig(
        "http://plex",
        "token",
        "client-id",
        hidden_library_keys=("2", "missing"),
        library_order_keys=("2", "1"),
    )
    libraries = [
        LibraryItem("Movies", "1", "movie", object()),
        LibraryItem("TV", "2", "show", object()),
    ]

    assert [library.title for library in visible_libraries(libraries, config)] == ["Movies"]


def test_sidebar_rows_can_hide_optional_entrypoints():
    config = AppConfig(
        "http://plex",
        "token",
        "client-id",
        show_playlists=False,
        show_discover=False,
        show_on_plex=False,
    )
    libraries = [LibraryItem("Movies", "1", "movie", object())]

    rows = sidebar_rows(config, libraries)

    assert [type(row) for row in rows] == [ContinueWatchingRow, LibraryRow]
    assert rows[1].library.title == "Movies"


def test_sidebar_rows_can_show_on_plex_without_discover():
    config = AppConfig("http://plex", "token", "client-id", show_discover=False)
    libraries = [LibraryItem("Movies", "1", "movie", object())]

    rows = sidebar_rows(config, libraries)

    assert [type(row) for row in rows] == [ContinueWatchingRow, PlaylistsRow, OnPlexRow, LibraryRow]


def test_ordered_libraries_uses_saved_order_and_appends_new_libraries():
    config = AppConfig("http://plex", "token", "client-id", library_order_keys=("3", "1", "missing"))
    libraries = [
        LibraryItem("Movies", "1", "movie", object()),
        LibraryItem("TV", "2", "show", object()),
        LibraryItem("Music", "3", "artist", object()),
    ]

    assert [library.title for library in ordered_libraries(libraries, config)] == ["Music", "Movies", "TV"]


def test_settings_row_details_describe_action_types():
    config = AppConfig("http://plex", "token", "client", page_size=80, grid_density="comfortable")
    rows = settings_rows(config)
    grid_row = next(row for row in rows if getattr(row, "action", "") == "cycle_grid_density")
    library_enter_row = next(row for row in rows if getattr(row, "action", "") == "cycle_library_enter_action")
    clear_row = next(row for row in rows if getattr(row, "action", "") == "clear_audio")
    input_row = next(row for row in rows if getattr(row, "action", "") == "set_page_size")
    value_row = next(row for row in rows if getattr(row, "label_text", "").strip().startswith("Server:"))

    grid_details = render_settings_row_details(grid_row, config)
    assert "Setting Control" in grid_details
    assert "Grid Density" in grid_details
    assert "Type: cycle" in grid_details
    assert "Current grid density: Comfortable" in grid_details
    assert "Controls" in grid_details
    assert "Left/Right changes this setting without opening an input." in grid_details

    library_enter_details = render_settings_row_details(library_enter_row, config)
    assert "Library Enter" in library_enter_details
    assert "Current library Enter action: Library" in library_enter_details

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


def test_playback_quality_helpers_cycle_values():
    assert next_playback_mode("auto") == "transcode"
    assert next_playback_mode("transcode") == "auto"
    assert next_playback_display("external") == "terminal"
    assert next_playback_display("terminal") == "external"
    assert next_terminal_video_profile("smooth") == "balanced"
    assert next_terminal_video_profile("balanced") == "sharp"
    assert next_terminal_video_profile("sharp") == "smooth"
    assert next_terminal_video_profile("bad") == "smooth"
    assert next_transcode_quality("original") == "1080p_8"
    assert next_transcode_quality("1080p_8") == "720p_4"
    assert next_transcode_quality("720p_4") == "480p_2"
    assert next_transcode_quality("480p_2") == "original"
    assert next_transcode_quality("bad") == "original"


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
        "Playing Movie / resume 1:05 / mode direct / 2 subtitles / audio Japanese; subtitles English / "
        "controls c pause, z -10s, f +30s, x stop"
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
        playback_mode="transcode",
        transcode_quality="720p_4",
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
    assert "Playback preference: Force transcode" in rendered
    assert "Transcode quality: 720p 4 Mbps" in rendered
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

    assert effective_stream_preference_rows(Raw(), found) == [
        ("Playback Mode", "Auto / direct default"),
        ("Playback Display", "External mpv window"),
        ("Terminal Video", "Smooth (15 fps / 640px)"),
        ("Transcode Quality", "Original"),
        ("Audio", "Japanese"),
        ("Subtitles", "English"),
    ]
    assert effective_stream_preference_rows(Raw(), missing) == [
        ("Playback Mode", "Auto / direct default"),
        ("Playback Display", "External mpv window"),
        ("Terminal Video", "Smooth (15 fps / 640px)"),
        ("Transcode Quality", "Original"),
        ("Audio", "spa not found, Plex/default"),
        ("Subtitles", "fre not found, Plex/default"),
    ]
    assert effective_stream_preference_rows(Raw(), none) == [
        ("Playback Mode", "Auto / direct default"),
        ("Playback Display", "External mpv window"),
        ("Terminal Video", "Smooth (15 fps / 640px)"),
        ("Transcode Quality", "Original"),
        ("Audio", "Plex/default"),
        ("Subtitles", "none"),
    ]


def test_render_details_includes_effective_playback_rows():
    details = MediaDetails(
        title="Title",
        kind="movie",
        facts=["Movie"],
        metadata=[],
        audio=[],
        subtitles=[],
        summary="",
        playable=True,
    )

    rendered = render_details(details, AppConfig("http://plex", "token", "client", subtitle_mode="none"), object())

    assert "Effective Playback" in rendered
    assert "Subtitles:         none" in rendered


def test_picker_details_explain_global_save():
    rendered = render_picker_details("audio", StreamChoice(1, "Japanese"), AppConfig("http://plex", "token", "client"))

    assert "Current Selection" in rendered
    assert "Enter saves the highlighted track as the global preference" in rendered


def test_mpv_window_size_cycles_common_values():
    assert next_mpv_window_size("") == "80%"
    assert next_mpv_window_size("80%") == "90%"
    assert next_mpv_window_size("100%") == "1600x900"
    assert next_mpv_window_size("1920x1080") == ""
    assert next_mpv_window_size("1280x720") == ""


def test_grid_density_cycles_and_changes_card_width():
    assert next_grid_density("comfortable") == "large"
    assert next_grid_density("large") == "compact"
    assert next_grid_density("compact") == "comfortable"
    assert grid_card_width(AppConfig("http://plex", "token", "client", grid_density="compact")) < grid_card_width(
        AppConfig("http://plex", "token", "client", grid_density="large")
    )


def test_grid_artwork_cache_changes_with_render_size():
    item = MediaItem("Movie", "", "movie", "1", True, object(), artwork_path="/thumb")
    compact = AppConfig("http://plex", "token", "client", media_view="grid", grid_density="compact")
    large = AppConfig("http://plex", "token", "client", media_view="grid", grid_density="large")
    grid = MediaGrid()

    grid.set_items([item], selected_index=0, config=compact, columns=1)
    grid.set_artwork("1", "compact-art")

    assert grid_artwork_cache_key(item, compact) != grid_artwork_cache_key(item, large)

    grid.set_items([item], selected_index=0, config=large, columns=1)

    assert grid.artwork == {}


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


def test_collection_grid_geometry_uses_wider_navigation_cards():
    comfortable = AppConfig("http://plex", "token", "client", grid_density="comfortable")

    assert grid_geometry_for_size(138, 34, comfortable, collection_cards=True) == (4, 2)
    assert grid_card_width(comfortable, collection_card=True) > grid_card_width(comfortable)
    assert grid_card_height(comfortable, collection_card=True) == grid_card_height(comfortable) + 1


def test_collection_grid_titles_wrap_to_two_lines():
    config = AppConfig("http://plex", "token", "client", grid_density="compact")

    assert grid_card_title_lines("Recently Released Movies", config, collection_card=True) == [
        "Recently Released",
        "Movies",
    ]
    assert grid_card_title_lines("Recently Released Movies", config) == ["Recently Rel..."]


def test_card_artwork_fetch_size_uses_higher_resolution_for_kitty(monkeypatch):
    monkeypatch.setenv("KITTY_WINDOW_ID", "1")

    block = AppConfig("http://plex", "token", "client", grid_density="comfortable")
    kitty = AppConfig("http://plex", "token", "client", artwork_renderer="kitty", grid_density="comfortable")

    assert card_artwork_fetch_size(block) == (18, 18)
    assert card_artwork_fetch_size(kitty) == (216, 216)


def test_render_card_artwork_uses_per_line_renderables():
    image = Image.new("RGB", (2, 4), "#ff0000")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    rendered = render_card_artwork(buffer.getvalue(), AppConfig("http://plex", "token", "client", grid_density="compact"))

    assert isinstance(rendered, Group)
    assert all(isinstance(line, Text) for line in rendered.renderables)


def test_render_card_artwork_uses_kitty_placeholders_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("KITTY_WINDOW_ID", "1")
    monkeypatch.setattr("plextui.artwork.cache_path", lambda: tmp_path)
    monkeypatch.setattr("plextui.artwork.emit_kitty_graphics_commands", lambda commands: None)
    image = Image.new("RGB", (2, 4), "#ff0000")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    rendered = render_card_artwork(
        buffer.getvalue(),
        AppConfig("http://plex", "token", "client", artwork_renderer="kitty", grid_density="compact"),
    )

    assert isinstance(rendered, KittyImage)
    assert rendered.commands


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
    assert "Movie · 2024" in selected_text
    assert "▶ play" in selected_text
    assert "┏" not in selected_text
    assert "▶ play" not in unselected_text
    assert "playable" not in unselected_text
    assert "Movie · 2024" not in unselected_text


def test_grid_card_footer_shows_watch_progress():
    class PartialRaw:
        viewOffset = 300000
        duration = 600000

    media = MediaItem("Movie", "2024", "movie", "1", True, PartialRaw(), artwork_path="")

    selected = render_media_grid_card(media, True, AppConfig("http://plex", "token", "client"))
    unselected = render_media_grid_card(media, False, AppConfig("http://plex", "token", "client"))

    assert "[####----] 50%" in str(selected.renderables[3])
    assert "▶ resume [####----] 50%" in str(selected.renderables[3])
    assert "[####----] 50%" not in str(unselected.renderables[3])


def test_grid_card_styles_follow_visual_state_tokens():
    media = MediaItem("Movie", "2024", "movie", "1", True, object(), artwork_path="")

    selected = render_media_grid_card(media, True, AppConfig("http://plex", "token", "client"))
    unselected = render_media_grid_card(media, False, AppConfig("http://plex", "token", "client"))

    assert selected.renderables[1].style == f"bold {UI_SELECTED_ACCENT}"
    assert selected.renderables[2].style == UI_GRID_MUTED
    assert selected.renderables[3].style == f"bold {UI_SELECTED_ACCENT}"
    assert unselected.renderables[1].style == f"bold {UI_GRID_TITLE}"
    assert unselected.renderables[2].style == UI_GRID_MUTED
    assert unselected.renderables[3].style == UI_GRID_DIM


def test_grid_card_marks_container_items_as_openable():
    media = MediaItem("Season 1", "10 episodes", "season", "1", False, object(), artwork_path="")

    rendered = render_media_grid_card(media, False, AppConfig("http://plex", "token", "client"))
    rendered_text = "\n".join(str(renderable) for renderable in rendered.renderables)
    placeholder = rendered.renderables[0]

    assert "open" in rendered_text
    assert "10 episodes" in rendered_text
    assert not any("[season]" in str(line) for line in placeholder.renderables)
    assert any("┌────┐" in line.plain for line in placeholder.renderables)


def test_grid_card_uses_collection_glyph_for_hub_rows():
    media = MediaItem("Recently Added", "", "hub", "1", False, object(), artwork_path="")

    rendered = render_media_grid_card(media, False, AppConfig("http://plex", "token", "client"))
    rendered_text = "\n".join(str(renderable) for renderable in rendered.renderables)
    placeholder = rendered.renderables[0]

    assert not any("[hub]" in str(line) for line in placeholder.renderables)
    assert any("──┼──" in line.plain for line in placeholder.renderables)
    assert "open" in rendered_text


def test_collection_grid_card_allows_longer_two_line_title():
    media = MediaItem("Recently Released Movies", "", "hub", "1", False, object(), artwork_path="/hub/thumb")

    rendered = render_media_grid_card(media, True, AppConfig("http://plex", "token", "client", grid_density="compact"))
    title_text = "\n".join(line.plain for line in rendered.renderables[1:3])

    assert grid_items_are_collection_cards([media])
    assert "Recently Released" in title_text
    assert "Movies" in title_text
    assert "..." not in title_text


def test_show_grid_with_artwork_keeps_poster_card_layout():
    media = MediaItem("Berserk", "1997", "show", "1", False, object(), artwork_path="/show/thumb")

    assert not grid_items_are_collection_cards([media])


def test_render_media_grid_text_snapshot_distinguishes_missing_and_collection_art():
    config = AppConfig("http://plex", "token", "client", grid_density="compact")
    items = [
        MediaItem("Blade Runner", "1982", "movie", "movie-1", True, object(), artwork_path=""),
        MediaItem("Recently Added", "", "hub", "hub-1", False, object(), artwork_path=""),
    ]

    rendered = render_media_grid(items, "hub-1", config, columns=2)
    text = render_plain(rendered, width=80)

    assert "[no poster]" not in text
    assert "[hub]" not in text
    assert "Blade Runner" in text
    assert "Recently Added" in text
    assert "──┼──" in text
    assert "playable" not in text
    assert "▶ open" in text


def test_grid_rows_are_centered_in_media_pane():
    media = MediaItem("Movie", "2024", "movie", "1", True, object(), artwork_path="")
    rendered = render_media_grid([media], media.key, AppConfig("http://plex", "token", "client"), columns=2)

    assert isinstance(rendered.renderables[0], Align)


def test_collection_grid_rows_are_left_aligned_with_breathing_room():
    config = AppConfig("http://plex", "token", "client", grid_density="compact")
    items = [
        MediaItem("Continue Watching", "", "hub", "hub-1", False, object(), artwork_path=""),
        MediaItem("Recently Added", "", "hub", "hub-2", False, object(), artwork_path=""),
        MediaItem("Recommended", "", "hub", "hub-3", False, object(), artwork_path=""),
    ]

    rendered = render_media_grid(items, "hub-1", config, columns=2)

    assert not isinstance(rendered.renderables[0], Align)
    assert isinstance(rendered.renderables[1], Text)
    assert not isinstance(rendered.renderables[2], Align)


def test_category_collection_glyphs_vary_by_title_family():
    config = AppConfig("http://plex", "token", "client", grid_density="compact")
    action = render_media_grid_card(MediaItem("Action", "Category", "category", "1", False, object()), False, config)
    comedy = render_media_grid_card(MediaItem("Comedy", "Category", "category", "2", False, object()), False, config)

    action_art = "\n".join(line.plain for line in action.renderables[0].renderables)
    comedy_art = "\n".join(line.plain for line in comedy.renderables[0].renderables)
    action_text = "\n".join(str(renderable) for renderable in action.renderables)

    assert "╱╱" in action_art
    assert "○" in comedy_art
    assert action_art != comedy_art
    assert "Category  Category" not in action_text


def test_grid_card_placeholder_matches_artwork_height():
    media = MediaItem("Movie", "2024", "movie", "1", True, object(), artwork_path="")
    config = AppConfig("http://plex", "token", "client", grid_density="compact")

    rendered = render_media_grid_card(media, False, config)

    placeholder = rendered.renderables[0]
    assert isinstance(placeholder, Group)
    assert len(placeholder.renderables) == grid_card_height(config) - 3
    assert not any("[no poster]" in str(line) for line in placeholder.renderables)
    assert any("on #" in str(line.spans) for line in placeholder.renderables)


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
    assert "tab / shift+tab: switch libraries / media focus" in rendered
    assert "d: focus details directly" in rendered
    assert "v: toggle list/grid view" in rendered
    assert "left/right: move across grid cards" in rendered
    assert "p: play selected media from beginning" in rendered
    assert "r: resume selected media from saved progress" in rendered
    assert "o: play optimized transcode for slow streams" in rendered
    assert "w: mark selected media watched / unwatched" in rendered
    assert "Playlist Management" in rendered
    assert "enter on Playlists sidebar row: browse all playlists" in rendered
    assert "P: add selected media to an existing or new playlist" in rendered
    assert "u: toggle selected item for bulk playlist actions" in rendered
    assert "backspace/delete: remove selected item from the open playlist" in rendered
    assert "e: rename selected or open playlist" in rendered
    assert "D: confirm delete selected or open playlist" in rendered
    assert "backspace/delete: remove selected item from Continue Watching" in rendered
    assert "ctrl+r: reconnect / reload libraries" in rendered
    assert "PLEX_TUI_ARTWORK_LOG=1" in rendered
    assert "?: show help" in rendered


def test_playlist_picker_rows_and_details():
    media = MediaItem("Movie", "", "movie", "1", True, object())
    second = MediaItem("Second", "", "movie", "2", True, object())
    playlist = MediaItem("Favorites", "", "playlist", "p1", False, object())
    create_row = PlaylistCreateRow()
    target_row = PlaylistTargetRow(playlist)

    assert create_row.label_text == "New playlist..."
    assert target_row.label_text == "Favorites"
    assert context_hint(create_row) == "Playlists: Enter creates a new playlist"
    assert context_hint(target_row) == "Playlists: Enter adds selected media"
    assert "1 existing playlist" in render_playlist_picker_details(media, 1)
    assert "Create a playlist containing Movie" in render_playlist_create_details(media)
    assert "Add Movie to this playlist" in render_playlist_target_details(playlist, media)
    assert "Create a playlist containing 2 selected items" in render_playlist_create_details([media, second])
    assert "Add 2 selected items to this playlist" in render_playlist_target_details(playlist, [media, second])


def test_footer_shows_core_bindings_and_help_keeps_full_reference():
    shown = {binding.action for binding in PlexTuiApp.BINDINGS if binding.show}
    hidden = {binding.action for binding in PlexTuiApp.BINDINGS if not binding.show}
    shown_labels = {binding.action: binding.description for binding in PlexTuiApp.BINDINGS if binding.show}
    hidden_keys_by_action = {}
    for binding in PlexTuiApp.BINDINGS:
        if not binding.show:
            hidden_keys_by_action.setdefault(binding.action, set()).add(binding.key)
    rendered = render_help()

    assert shown == {
        "quit",
        "focus_search",
        "focus_global_search",
        "show_help",
        "toggle_media_view",
        "show_settings",
        "back_or_clear",
        "play_selected",
        "resume_selected",
    }
    assert shown_labels["play_selected"] == "Play from start"
    assert shown_labels["resume_selected"] == "Resume"
    assert "alternate_library_action" in hidden
    assert "add_to_playlist" in hidden
    assert "play_optimized" in hidden
    assert "toggle_bulk_selection" in hidden
    assert "rename_playlist" in hidden
    assert "delete_playlist" in hidden
    assert "toggle_watched" in hidden
    assert "remove_continue_watching" in hidden
    assert hidden_keys_by_action["remove_continue_watching"] == {"backspace", "delete"}
    assert hidden_keys_by_action["add_to_playlist"] == {"P"}
    assert hidden_keys_by_action["play_optimized"] == {"o"}
    assert hidden_keys_by_action["toggle_bulk_selection"] == {"u"}
    assert hidden_keys_by_action["rename_playlist"] == {"e"}
    assert hidden_keys_by_action["delete_playlist"] == {"D"}
    assert "audio_picker" in hidden
    assert "subtitle_picker" in hidden
    assert hidden_keys_by_action["toggle_playback_pause"] == {"c"}
    assert hidden_keys_by_action["seek_playback_backward"] == {"z"}
    assert hidden_keys_by_action["seek_playback_forward"] == {"f"}
    assert "a: choose and save audio preference" in rendered
    assert "s: choose and save subtitle preference" in rendered
    assert "o: play optimized transcode for slow streams" in rendered
    assert "c: pause / resume active mpv playback" in rendered
    assert "z: seek active playback back 10 seconds" in rendered
    assert "f: seek active playback forward 30 seconds" in rendered
    assert "ctrl+r: reconnect / reload libraries" in rendered


def test_focus_css_styles_all_panes():
    css = PlexTuiApp.CSS

    assert "#sidebar.focused-pane" in css
    assert "#sidebar.context-pane .context-row" in css
    assert "#main.focused-pane" in css
    assert "#details.focused-pane" in css
    assert css.count("border: solid $background;") == 3
    assert css.count("border: solid $primary;") == 3
    assert ".focused-pane .active-row" in css
    assert "background: $panel;" in css
    assert "background: $accent;" in css
    assert "color: $text;" in css


def test_set_status_skips_unchanged_text(monkeypatch):
    app = PlexTuiApp()
    updates = []
    status = SimpleNamespace(content="Ready", update=updates.append)
    monkeypatch.setattr(app, "query_one", lambda *args: status)

    app.set_status("Ready")
    app.set_status("Browsing")

    assert updates == ["Browsing"]


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


def test_fuzzy_match_media_ranks_typos_and_acronyms():
    items = [
        MediaItem("Blade Runner", "1982", "movie", "1", True, object()),
        MediaItem("Interstellar", "2014", "movie", "2", True, object()),
        MediaItem("The Lord of the Rings", "The Fellowship of the Ring", "movie", "3", True, object()),
        MediaItem("The Matrix", "1999", "movie", "4", True, object()),
    ]

    typo_matches = fuzzy_match_media("interstelar", items)
    acronym_matches = fuzzy_match_media("lotr", items)
    subtitle_matches = fuzzy_match_media("fellowship", items)

    assert [item.title for item in typo_matches[:2]] == ["Interstellar"]
    assert [item.title for item in acronym_matches[:2]] == ["The Lord of the Rings"]
    assert [item.title for item in subtitle_matches[:2]] == ["The Lord of the Rings"]


def test_alphabet_jump_index_moves_between_loaded_title_groups():
    items = [
        MediaItem("Alien", "", "movie", "1", True, object()),
        MediaItem("Aliens", "", "movie", "2", True, object()),
        MediaItem("Blade Runner", "", "movie", "3", True, object()),
        MediaItem("Casablanca", "", "movie", "4", True, object()),
        MediaItem("2001", "", "movie", "5", True, object()),
    ]

    assert alphabet_jump_index(items, 0, 1) == 2
    assert alphabet_jump_index(items, 2, 1) == 3
    assert alphabet_jump_index(items, 3, 1) == 4
    assert alphabet_jump_index(items, 4, 1) is None
    assert alphabet_jump_index(items, 3, -1) == 2
    assert alphabet_jump_index(items, 2, -1) == 0
    assert alphabet_jump_index(items, 0, -1) is None
    assert alphabet_group_label(items[4]) == "#"


def test_alphabet_jump_index_follows_loaded_section_order():
    items = [
        MediaItem("Alien", "", "movie", "1", True, object()),
        MediaItem("Casablanca", "", "movie", "2", True, object()),
        MediaItem("Blade Runner", "", "movie", "3", True, object()),
        MediaItem("Arrival", "", "movie", "4", True, object()),
        MediaItem("2001", "", "movie", "5", True, object()),
    ]

    assert alphabet_section_groups(items) == ["A", "C", "B", "A", "#"]
    assert alphabet_jump_index(items, 0, 1) == 1
    assert alphabet_jump_index(items, 1, -1) == 0
    assert alphabet_jump_index(items, 2, -1) == 1


def test_alphabet_jump_index_handles_duplicate_movie_sections():
    items = [
        MediaItem("*batteries not included", "", "movie", "1", True, object()),
        MediaItem("8MM", "", "movie", "2", True, object()),
        MediaItem("Abigail", "", "movie", "3", True, object()),
        MediaItem("Bad Taste", "", "movie", "4", True, object()),
    ]

    assert alphabet_section_groups(items) == ["B", "#", "A", "B"]
    assert alphabet_jump_index(items, 0, 1) == 1
    assert alphabet_jump_index(items, 1, 1) == 2
    assert alphabet_jump_index(items, 2, 1) == 3
    assert alphabet_jump_index(items, 3, -1) == 2


def test_alphabet_jump_index_prefers_plex_sort_title():
    items = [
        MediaItem("Jaws", "", "movie", "1", True, SimpleNamespace(titleSort="Jaws")),
        MediaItem("The Matrix", "", "movie", "2", True, SimpleNamespace(titleSort="Matrix, The")),
        MediaItem("Nope", "", "movie", "3", True, SimpleNamespace(titleSort="Nope")),
    ]

    assert alphabet_group_label(items[1]) == "M"
    assert alphabet_jump_index(items, 0, 1) == 1
    assert alphabet_jump_index(items, 1, 1) == 2
    assert alphabet_jump_index(items, 2, -1) == 1


def test_alphabet_jump_log_includes_sort_title_decision(monkeypatch):
    messages = []
    items = [
        MediaItem("Jaws", "", "movie", "1", True, SimpleNamespace(titleSort="Jaws")),
        MediaItem("The Matrix", "", "movie", "2", True, SimpleNamespace(titleSort="Matrix, The")),
    ]
    monkeypatch.setenv("PLEX_TUI_PERF_LOG", "1")
    monkeypatch.setattr("plextui.app.write_debug_log", messages.append)

    write_alphabet_jump_log(items, 0, 1, 1)

    assert messages
    assert "nav alphabet_jump direction=next" in messages[0]
    assert "current_title='Jaws'" in messages[0]
    assert "target_title='The Matrix'" in messages[0]
    assert "target_sort_title='Matrix, The'" in messages[0]
    assert "section_groups='J,M'" in messages[0]


def test_media_row_includes_progress_marker():
    class PartialRaw:
        viewOffset = 65000
        duration = 600000

    row = MediaRow(MediaItem("Movie", "2024", "movie", "1", True, PartialRaw()))

    assert row.label_text.startswith("▶ Movie")
    assert "Movie · Movie · 2024" in row.label_text
    assert "[#-------] 11%" in row.label_text


def test_media_row_marks_container_items():
    row = MediaRow(MediaItem("Show", "2 seasons", "show", "1", False, object()))

    assert row.label_text.startswith("› Show")
    assert "Show · TV Show · 2 seasons" in row.label_text


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
    class PartialRaw:
        viewOffset = 300000
        duration = 600000

    items = [
        MediaItem(f"Movie {index}", "2024", "movie", str(index), True, object(), artwork_path="/thumb")
        for index in range(12)
    ]
    items[2] = MediaItem("Partial", "2024", "movie", "2", True, PartialRaw(), artwork_path="/thumb")
    config = AppConfig("http://plex", "token", "client", media_view="grid")
    grid = MediaGrid()
    grid.set_items(items, selected_index=7, config=config, columns=2, rows=2)
    state = BrowseState("Movies", items, total=30)

    assert "item 8" in grid_status(grid, state)
    assert "page 2 of 3" in grid_status(grid, state)
    assert "12 of 30 loaded" in grid_status(grid, state)
    assert "1 in-progress item" in grid_status(grid, state)


def test_playlist_context_hints_status_and_details_action():
    item = MediaItem("Movie", "", "movie", "1", True, object(), artwork_path="/thumb")
    playlist = MediaItem("Favorites", "", "playlist", "p1", False, object())
    state = BrowseState("Favorites", [item], source="playlist", context_media=playlist, total=1)
    row = MediaRow(item)
    grid = MediaGrid()
    grid.set_items([item], selected_index=0, config=AppConfig("http://plex", "token", "client"), columns=1)

    assert current_detail_actions(state) == ("Playlist: Backspace/Delete removes from this playlist",)
    assert "Backspace/Delete removes selected item" in render_browse_status(state)
    assert "Backspace/Delete remove from playlist" in media_row_status(row, state)
    assert "Backspace/Delete remove from playlist" in grid_status(grid, state)


def test_context_hints_for_media_and_load_more():
    playable = MediaItem("Movie", "", "movie", "1", True, object())
    container = MediaItem("Show", "", "show", "2", False, object())
    grid = MediaGrid()
    grid.set_items([playable], selected_index=0, config=AppConfig("http://plex", "token", "client"), columns=1)
    settings = settings_rows(AppConfig("http://plex", "token", "client"))
    setting_action = next(row for row in settings if getattr(row, "action", "") == "cycle_grid_density")
    setting_value = next(row for row in settings if getattr(row, "label_text", "").strip().startswith("Server:"))

    assert context_hint(MediaRow(playable)) == (
        "Media: Enter selects / p play from beginning / r resume / o optimized / P playlist / w watched / a audio / s subtitles"
    )
    assert context_hint(MediaRow(container)) == "Media: Enter opens item"
    assert context_hint(MediaRow(MediaItem("Favorites", "", "playlist", "p1", False, object()))) == (
        "Media: Enter opens playlist / e rename / D delete"
    )
    assert context_hint(PlaylistsRow()) == "Libraries: Enter opens playlists"
    assert context_hint(grid) == (
        "Grid: Arrows/page select card / p play from beginning / r resume / o optimized / P playlist / w watched / a audio / s subtitles"
    )
    assert context_hint(LoadMoreRow(100, 200)) == "Media: Enter loads next page"
    assert context_hint(LibraryRow(LibraryItem("Movies", "1", "movie", object()))) == (
        "Libraries: Enter opens primary view / Space opens alternate view"
    )
    assert context_hint(LibraryMenuRow(LibraryItem("Movies", "1", "movie", object()), "library", "Library", "All items")) == (
        "Library: Enter opens browse mode"
    )
    assert context_hint(setting_action) == "Settings: Enter or Left-Right cycles"
    assert context_hint(setting_value) == "Settings: Current value"


def test_library_menu_rows_list_supported_entrypoints():
    library = LibraryItem("Movies", "1", "movie", object())

    rows = library_menu_rows(library)

    assert [row.entry for row in rows] == ["library", "recommended", "collections", "playlists", "categories"]
    assert [row.label_text for row in rows] == ["Library", "Recommended", "Collections", "Playlists", "Categories"]
    assert [row.display_text for row in rows] == [
        "▦ Library",
        "✦ Recommended",
        "◇ Collections",
        "▤ Playlists",
        "◈ Categories",
    ]


def render_plain(renderable: object, width: int = 100) -> str:
    console = Console(width=width, record=True, color_system=None)
    console.print(renderable)
    return console.export_text(styles=False)
