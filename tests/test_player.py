from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from plextui.player import (
    PlayerError,
    ProgressMonitor,
    StreamChoice,
    play_with_mpv,
    preferred_audio_choice,
    preferred_subtitle_choice,
    log_debug,
    sanitize_command,
)


@pytest.fixture(autouse=True)
def debug_log_path(tmp_path, monkeypatch):
    path = tmp_path / "debug.log"
    monkeypatch.setattr("plextui.config.debug_log_path", lambda: path)
    return path


class Server:
    def url(self, key: str, includeToken: bool = False) -> str:
        return "http://plex" + key


class Proc:
    def poll(self):
        return None


class SubtitleStream:
    key = "/library/streams/1"
    id = 1
    index = 2
    selected = False
    codec = "srt"
    displayTitle = "English"
    language = "English"
    languageCode = "eng"
    _server = Server()


class AudioStream:
    key = None
    id = 42
    index = 1
    selected = False
    codec = "aac"
    displayTitle = "Japanese"
    language = "Japanese"
    languageCode = "jpn"
    channels = 2


class Part:
    key = "/library/parts/1/file.mkv"
    _server = Server()

    def subtitleStreams(self):
        return [SubtitleStream()]

    def audioStreams(self):
        return [AudioStream()]


class Item:
    title = "Movie"
    viewOffset = 65000
    duration = 600000
    ratingKey = "1"
    key = "/library/metadata/1"

    def reload(self):
        return self

    def getStreamURL(self, **kwargs):
        self.kwargs = kwargs
        return "http://plex/video.m3u8"

    def iterParts(self):
        return [Part()]

    def updateProgress(self, time, state="stopped"):
        self.progress = (time, state)

    def updateTimeline(self, time, state="stopped"):
        self.timeline = (time, state)


def test_playback_applies_selected_streams_and_resume_offset(debug_log_path):
    item = Item()
    subtitle = Part().subtitleStreams()[0]
    audio = Part().audioStreams()[0]

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        handle = play_with_mpv(
            item,
            subtitle_choice=StreamChoice(1, "English", subtitle),
            audio_choice=StreamChoice(42, "Japanese", audio),
        )

    args = popen.call_args.args[0]
    assert handle.start_offset_ms == 65000
    assert handle.command[0] == "mpv"
    assert "--start=65.000" in args
    assert "--sub-file=http://plex/library/streams/1" in args
    assert item.kwargs == {"audioStreamID": 42}
    assert "launching mpv" in debug_log_path.read_text(encoding="utf-8")


def test_playback_keeps_selected_resume_offset_when_reload_omits_it():
    class FullItem(Item):
        viewOffset = 0

    class BrowseItem(Item):
        def __init__(self):
            self.full_item = FullItem()

        def reload(self):
            return self.full_item

    item = BrowseItem()

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        handle = play_with_mpv(item)

    args = popen.call_args.args[0]
    assert handle.start_offset_ms == 65000
    assert "--start=65.000" in args
    assert item.full_item.kwargs == {}


def test_playback_applies_configured_mpv_window_size():
    item = Item()

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        play_with_mpv(item, window_size="1280x720")

    args = popen.call_args.args[0]
    assert "--autofit=1280x720" in args


def test_subtitle_none_disables_subtitle_selection():
    item = Item()

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        handle = play_with_mpv(item, subtitle_choice=StreamChoice(0, "None"))

    args = popen.call_args.args[0]
    assert handle.subtitle_count == 0
    assert item.kwargs == {"subtitleStreamID": 0}
    assert not any(arg.startswith("--sub-file=") for arg in args)


def test_progress_monitor_reports_progress_and_timeline():
    item = Item()
    monitor = ProgressMonitor(item, Proc(), Path("/tmp/no-socket"), 0)
    monitor.last_ms = 123000

    monitor.report("playing")

    assert item.progress == (123000, "playing")
    assert item.timeline == (123000, "playing")


def test_direct_play_gets_mpv_track_hints_for_embedded_streams():
    class EmbeddedSubtitle(SubtitleStream):
        key = None
        codec = "vobsub"
        index = 3

    class EmbeddedPart(Part):
        def subtitleStreams(self):
            return [EmbeddedSubtitle()]

    class EmbeddedItem(Item):
        def iterParts(self):
            return [EmbeddedPart()]

    item = EmbeddedItem()
    subtitle = EmbeddedPart().subtitleStreams()[0]
    audio = EmbeddedPart().audioStreams()[0]

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        handle = play_with_mpv(
            item,
            subtitle_choice=StreamChoice(1, "English", subtitle),
            audio_choice=StreamChoice(42, "Japanese", audio),
        )

    args = popen.call_args.args[0]
    assert handle.stream_mode == "direct"
    assert "--aid=1" in args
    assert "--sid=1" in args


def test_force_transcode_bypasses_direct_play_and_applies_quality():
    class EmbeddedSubtitle(SubtitleStream):
        key = None
        codec = "vobsub"
        index = 3

    class EmbeddedPart(Part):
        def subtitleStreams(self):
            return [EmbeddedSubtitle()]

    class EmbeddedItem(Item):
        def iterParts(self):
            return [EmbeddedPart()]

    item = EmbeddedItem()
    subtitle = EmbeddedPart().subtitleStreams()[0]

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        handle = play_with_mpv(
            item,
            subtitle_choice=StreamChoice(1, "English", subtitle),
            playback_mode="transcode",
            transcode_quality="720p_4",
        )

    args = popen.call_args.args[0]
    assert handle.stream_mode == "transcode"
    assert item.kwargs == {
        "subtitleStreamID": 1,
        "maxVideoBitrate": 4000,
        "videoResolution": "1280x720",
    }
    assert not any(arg.startswith("--sid=") for arg in args)


def test_force_transcode_original_quality_omits_quality_kwargs():
    item = Item()

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()),
    ):
        handle = play_with_mpv(item, playback_mode="transcode", transcode_quality="original")

    assert handle.stream_mode == "transcode"
    assert item.kwargs == {}


def test_preferred_choices_match_stream_language():
    item = Item()

    audio = preferred_audio_choice(item, "jpn")
    subtitle = preferred_subtitle_choice(item, "eng", "preferred")
    disabled = preferred_subtitle_choice(item, "eng", "none")
    auto = preferred_subtitle_choice(item, "eng", "auto")

    assert audio is not None
    assert audio.stream_id == 42
    assert subtitle is not None
    assert subtitle.stream_id == 1
    assert disabled is not None
    assert disabled.stream_id == 0
    assert auto is None


def test_sanitize_command_redacts_token_urls():
    command = sanitize_command([
        "mpv",
        "--sub-file=http://plex/sub.srt?X-Plex-Token=secret&download=1",
        "http://plex/video.mkv?token=secret&quality=10",
    ])

    assert command == [
        "mpv",
        "--sub-file=http://plex/sub.srt?X-Plex-Token=REDACTED&download=1",
        "http://plex/video.mkv?token=REDACTED&quality=10",
    ]


def test_debug_log_redacts_token_text(debug_log_path):
    log_debug("failed url=http://plex/video?X-Plex-Token=secret&other=1")

    text = debug_log_path.read_text(encoding="utf-8")
    assert "secret" not in text
    assert "X-Plex-Token=REDACTED" in text


def test_playback_errors_when_mpv_missing():
    with patch("plextui.player.shutil.which", return_value=None):
        try:
            play_with_mpv(Item())
        except PlayerError as exc:
            assert "Install mpv" in str(exc)
        else:
            raise AssertionError("expected PlayerError")


def test_playback_errors_on_empty_stream_url():
    class EmptyUrlItem(Item):
        def getStreamURL(self, **kwargs):
            return ""

    with patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"):
        try:
            play_with_mpv(EmptyUrlItem())
        except PlayerError as exc:
            assert "empty stream URL" in str(exc)
        else:
            raise AssertionError("expected PlayerError")


def test_playback_errors_on_mpv_launch_failure():
    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.subprocess.Popen", side_effect=OSError("boom")),
    ):
        try:
            play_with_mpv(Item())
        except PlayerError as exc:
            assert "failed to launch mpv" in str(exc)
        else:
            raise AssertionError("expected PlayerError")
