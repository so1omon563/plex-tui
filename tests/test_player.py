from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from plextui.player import ProgressMonitor, StreamChoice, play_with_mpv


class Server:
    def url(self, key: str, includeToken: bool = False) -> str:
        return "http://plex" + key


class Proc:
    def poll(self):
        return None


class SubtitleStream:
    key = "/library/streams/1"
    id = 1
    selected = False
    codec = "srt"
    displayTitle = "English"
    _server = Server()


class AudioStream:
    key = None
    id = 42
    selected = False
    codec = "aac"
    displayTitle = "Japanese"
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


def test_playback_applies_selected_streams_and_resume_offset():
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
    assert "--start=65.000" in args
    assert "--sub-file=http://plex/library/streams/1" in args
    assert item.kwargs == {"audioStreamID": 42}


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
