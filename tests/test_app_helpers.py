from __future__ import annotations

from plextui.app import (
    format_offset,
    render_audio_playback_preference,
    render_details,
    render_settings,
    render_subtitle_playback_preference,
    subtitle_preference_value,
)
from plextui.config import AppConfig
from plextui.models import MediaDetails
from plextui.player import StreamChoice


def test_format_offset():
    assert format_offset(65000) == "1:05"
    assert format_offset(3_665_000) == "1:01:05"


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


def test_render_settings_includes_stream_preferences():
    config = AppConfig(
        base_url="http://plex",
        token="token",
        account_token="account-token",
        client_identifier="client-id",
        preferred_audio_language="jpn",
        preferred_subtitle_language="eng",
        subtitle_mode="preferred",
    )

    rendered = render_settings(config)

    assert "Audio Preference: jpn" in rendered
    assert "Subtitle Mode: Preferred" in rendered
    assert "Subtitle Language: eng" in rendered
    assert subtitle_preference_value(config) == "eng"


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


def test_render_subtitle_none_playback_status():
    config = AppConfig(
        base_url="http://plex",
        token="token",
        client_identifier="client-id",
        subtitle_mode="none",
    )

    assert render_subtitle_playback_preference(config, StreamChoice(0, "None")) == "subtitles none"
