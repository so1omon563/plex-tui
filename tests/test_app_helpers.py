from __future__ import annotations

from plextui.app import format_offset, render_details, render_settings
from plextui.config import AppConfig
from plextui.models import MediaDetails


def test_format_offset():
    assert format_offset(65000) == "1:05"
    assert format_offset(3_665_000) == "1:01:05"


def test_render_details_includes_subtitles_and_summary():
    details = MediaDetails(
        title="Title",
        kind="movie",
        facts=["movie"],
        metadata=[("Type", "movie")],
        subtitles=["English (srt, selected)"],
        summary="Summary text",
        playable=True,
    )

    rendered = render_details(details)

    assert "Metadata" in rendered
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
