from __future__ import annotations

import subprocess
from os import terminal_size
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from plextui.player import (
    _log_mpv_stderr,
    direct_play_url,
    full_metadata,
    is_drm_vod_stream,
    media_version_choices,
    PlayerError,
    ProgressMonitor,
    StreamChoice,
    plex_stream_offset,
    play_with_mpv,
    preferred_audio_choice,
    preferred_subtitle_choice,
    log_debug,
    sanitize_command,
    seek_mpv,
    switch_mpv_stream,
    toggle_mpv_pause,
)


@pytest.fixture(autouse=True)
def debug_log_path(tmp_path, monkeypatch):
    path = tmp_path / "debug.log"
    monkeypatch.setattr("plextui.config.debug_log_path", lambda: path)
    return path


class Server:
    _baseurl = "http://plex"

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
    assert "--no-terminal" not in args
    assert "--force-window=immediate" in args
    assert "--focus-on=all" not in args
    assert popen.call_args.kwargs["stdout"] == subprocess.PIPE
    assert popen.call_args.kwargs["stderr"] == subprocess.STDOUT
    assert "--cache=yes" in args
    assert "--demuxer-max-bytes=128MiB" in args
    assert "--demuxer-readahead-secs=20" in args
    assert "--cache-pause=no" in args
    assert "--start=65.000" in args
    assert "--sub-file=http://plex/library/streams/1" in args
    assert "--aid=1" in args
    assert "--sid=1" in args
    assert args[-1] == "http://plex/library/parts/1/file.mkv"
    assert handle.stream_mode == "direct"
    assert not hasattr(item, "kwargs")
    assert "launching mpv" in debug_log_path.read_text(encoding="utf-8")


def test_playback_disables_tls_verification_for_plex_direct_urls():
    class PlexDirectServer(Server):
        _baseurl = "https://host.plex.direct:8443"

        def url(self, key: str, includeToken: bool = False) -> str:
            return self._baseurl + key

    class PlexDirectPart(Part):
        _server = PlexDirectServer()

    class PlexDirectItem(Item):
        def iterParts(self):
            return [PlexDirectPart()]

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        play_with_mpv(PlexDirectItem())

    args = popen.call_args.args[0]
    assert "--tls-verify=no" in args
    assert args[-1] == "https://host.plex.direct:8443/library/parts/1/file.mkv"


def test_playback_can_start_from_beginning_instead_of_resuming():
    item = Item()

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        handle = play_with_mpv(item, resume=False)

    args = popen.call_args.args[0]
    assert handle.start_offset_ms == 0
    assert "--start=65.000" not in args
    assert args[-1] == "http://plex/library/parts/1/file.mkv"
    assert handle.stream_mode == "direct"
    assert not hasattr(item, "kwargs")


def test_direct_playback_merges_all_split_media_parts():
    class SplitPart(Part):
        def __init__(self, key):
            self.key = key

        def subtitleStreams(self):
            return []

        def audioStreams(self):
            return []

    class SplitItem(Item):
        def iterParts(self):
            return [
                SplitPart("/library/parts/1/cd1.mkv"),
                SplitPart("/library/parts/2/cd2.mkv"),
            ]

        def getStreamURL(self, **kwargs):
            raise AssertionError("split direct playback should not request a transcode URL")

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        handle = play_with_mpv(SplitItem())

    args = popen.call_args.args[0]
    assert "--merge-files" in args
    assert "--start=65.000" in args
    assert args[-2:] == [
        "http://plex/library/parts/1/cd1.mkv",
        "http://plex/library/parts/2/cd2.mkv",
    ]
    assert handle.monitor.base_offset == 0
    with patch("plextui.player.mpv_get_property", return_value=72.5):
        assert handle.monitor.current_time_ms() == 72_500


def test_multipart_transcode_is_rejected_before_launch():
    class SplitItem(Item):
        def iterParts(self):
            return [Part(), Part()]

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.subprocess.Popen") as popen,
        pytest.raises(PlayerError, match="not supported in transcode mode"),
    ):
        play_with_mpv(SplitItem(), playback_mode="transcode")

    popen.assert_not_called()


def test_multipart_playback_rejects_an_unaddressable_part_before_launch():
    class MissingPart(Part):
        key = None

    class SplitItem(Item):
        def iterParts(self):
            return [Part(), MissingPart()]

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.subprocess.Popen") as popen,
        pytest.raises(PlayerError, match="direct access to every Plex media part"),
    ):
        play_with_mpv(SplitItem())

    popen.assert_not_called()


def test_media_version_picker_labels_and_plays_selected_part():
    class VersionPart(Part):
        def __init__(self, part_id, key, filename, audio, subtitle):
            self.id = part_id
            self.key = key
            self.file = filename
            self.audio = audio
            self.subtitle = subtitle

        def audioStreams(self):
            return [self.audio]

        def subtitleStreams(self):
            return [self.subtitle]

    class VersionMedia:
        container = "mkv"

        def __init__(self, resolution, bitrate, part):
            self.videoResolution = resolution
            self.bitrate = bitrate
            self.parts = [part]

    class MultiVersionItem(Item):
        stream_calls = []

        def __init__(self):
            old_audio = MagicMock(id=42, languageCode="jpn")
            old_subtitle = MagicMock(id=1, languageCode="eng", key=None)
            new_audio = MagicMock(id=84, languageCode="jpn")
            new_subtitle = MagicMock(id=2, languageCode="eng", key=None)
            self.media = [
                VersionMedia(
                    "sd",
                    1870,
                    VersionPart(
                        25020,
                        "/library/parts/25020/old.mkv",
                        "/media/Old Bluray.mkv",
                        old_audio,
                        old_subtitle,
                    ),
                ),
                VersionMedia(
                    "480",
                    1835,
                    VersionPart(
                        25033,
                        "/library/parts/25033/new.mkv",
                        "/media/New SDTV.mkv",
                        new_audio,
                        new_subtitle,
                    ),
                ),
            ]

        def iterParts(self):
            return [part for media in self.media for part in media.parts]

        def getStreamURL(self, **kwargs):
            self.stream_calls.append(kwargs)
            return "http://plex/transcode.m3u8"

    item = MultiVersionItem()
    choices = media_version_choices(item)

    assert [choice.part_id for choice in choices] == ["25020", "25033"]
    assert choices[1].label == "480p · 1.8 Mbps · MKV · New SDTV.mkv"

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        play_with_mpv(item)

    assert popen.call_args.args[0][-1] == "http://plex/library/parts/25020/old.mkv"
    assert "--merge-files" not in popen.call_args.args[0]

    old_part = item.media[0].parts[0]
    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        play_with_mpv(
            item,
            audio_choice=StreamChoice(42, "Japanese", old_part.audio),
            subtitle_choice=StreamChoice(1, "English", old_part.subtitle),
            version_part_id=choices[1].part_id,
        )

    assert popen.call_args.args[0][-1] == "http://plex/library/parts/25033/new.mkv"
    assert "--aid=1" in popen.call_args.args[0]
    assert "--sid=1" in popen.call_args.args[0]

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()),
    ):
        play_with_mpv(
            item,
            audio_choice=StreamChoice(42, "Japanese", old_part.audio),
            subtitle_choice=StreamChoice(1, "English", old_part.subtitle),
            playback_mode="transcode",
            version_part_id=choices[1].part_id,
        )

    assert item.stream_calls[-1]["mediaIndex"] == 1
    assert item.stream_calls[-1]["partIndex"] == 0
    assert item.stream_calls[-1]["audioStreamID"] == 84
    assert item.stream_calls[-1]["subtitleStreamID"] == 2


def test_selected_media_version_keeps_all_split_parts():
    class VersionPart(Part):
        def __init__(self, part_id, key):
            self.id = part_id
            self.key = key

        def subtitleStreams(self):
            return []

        def audioStreams(self):
            return []

    class VersionMedia:
        def __init__(self, *parts):
            self.parts = list(parts)

    class MultiVersionItem(Item):
        def __init__(self):
            self.media = [
                VersionMedia(VersionPart(10, "/library/parts/10/other.mkv")),
                VersionMedia(
                    VersionPart(20, "/library/parts/20/cd1.mkv"),
                    VersionPart(21, "/library/parts/21/cd2.mkv"),
                ),
            ]

        def iterParts(self):
            return [part for media in self.media for part in media.parts]

    item = MultiVersionItem()

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        play_with_mpv(item, version_part_id="20")

    args = popen.call_args.args[0]
    assert "--merge-files" in args
    assert args[-2:] == [
        "http://plex/library/parts/20/cd1.mkv",
        "http://plex/library/parts/21/cd2.mkv",
    ]
    assert "http://plex/library/parts/10/other.mkv" not in args


def test_media_version_playback_requires_successful_metadata_reload():
    class StaleVersionItem(Item):
        media = [MagicMock(parts=[MagicMock(id=25033)])]

        def reload(self):
            raise RuntimeError("server unavailable")

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        pytest.raises(PlayerError, match="could not refresh selected media version"),
    ):
        play_with_mpv(StaleVersionItem(), version_part_id="25033")


def test_playback_rejects_media_version_removed_after_picker_opened():
    item = Item()
    item.media = []

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        pytest.raises(PlayerError, match="no longer available"),
    ):
        play_with_mpv(item, version_part_id="missing")


def test_online_metadata_playback_uses_part_url():
    class OnlineServer(Server):
        _baseurl = "https://metadata.provider.plex.tv"

    class OnlinePart(Part):
        _server = OnlineServer()

    class OnlineItem(Item):
        _server = Server()

        def getStreamURL(self, **kwargs):
            raise AssertionError("online metadata playback should prefer the part URL")

        def iterParts(self):
            return [OnlinePart()]

    item = OnlineItem()

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        handle = play_with_mpv(item)

    args = popen.call_args.args[0]
    assert args[-1] == "http://plex/library/parts/1/file.mkv"
    assert not any(arg.startswith("--sub-file=") for arg in args)
    assert handle.stream_mode == "direct"


def test_online_metadata_playback_uses_browse_part_after_reload_loses_parts():
    class OnlineServer(Server):
        _baseurl = "https://metadata.provider.plex.tv"

    class OnlinePart(Part):
        _server = OnlineServer()

    class FullItem(Item):
        _server = OnlineServer()

    class BrowseItem(Item):
        def reload(self):
            return FullItem()

        def iterParts(self):
            return [OnlinePart()]

    item = BrowseItem()

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        handle = play_with_mpv(item)

    args = popen.call_args.args[0]
    assert args[-1] == "http://plex/library/parts/1/file.mkv"
    assert handle.stream_mode == "direct"


def test_online_metadata_direct_url_uses_vod_provider_host():
    class OnlineServer:
        _baseurl = "https://metadata.provider.plex.tv"
        VOD = "https://vod.provider.plex.tv"

        def url(self, key: str, includeToken: bool = False) -> str:
            token = "?X-Plex-Token=token" if includeToken else ""
            return self._baseurl + key + token

    class OnlinePart(Part):
        key = "/library/parts/provider-hls.m3u8"
        _server = OnlineServer()

    class OnlineItem(Item):
        _server = OnlineServer()

        def iterParts(self):
            return [OnlinePart()]

    assert direct_play_url(OnlineItem()) == (
        "https://vod.provider.plex.tv/library/parts/provider-hls.m3u8?X-Plex-Token=token"
    )


def test_online_metadata_full_metadata_fetches_from_vod_provider_and_restores_server():
    class OnlineServer:
        _baseurl = "https://metadata.provider.plex.tv"

        def __init__(self):
            self.fetch_baseurls = []

        def fetchItem(self, key: str):
            self.fetch_baseurls.append((self._baseurl, key))
            return type("FullItem", (), {"title": "Episode", "_server": self})()

    class OnlineItem(Item):
        key = "/library/metadata/episode-1"

        def __init__(self):
            self._server = OnlineServer()

    item = OnlineItem()
    full = full_metadata(item)

    assert full.title == "Episode"
    assert item._server.fetch_baseurls == [
        ("https://vod.provider.plex.tv", "/library/metadata/episode-1")
    ]
    assert item._server._baseurl == "https://metadata.provider.plex.tv"


def test_online_metadata_without_vod_stream_raises_player_error():
    class OnlineServer:
        _baseurl = "https://metadata.provider.plex.tv"

    class OnlineItem(Item):
        title = "Special"
        _server = OnlineServer()

        def reload(self):
            raise AssertionError("online metadata without VOD media should not reload")

        def iterParts(self):
            return []

        def getStreamURL(self, **kwargs):
            raise AssertionError("unavailable online metadata should not request transcode")

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen") as popen,
    ):
        with pytest.raises(PlayerError, match="does not provide a playable stream"):
            play_with_mpv(OnlineItem())

    popen.assert_not_called()


def test_drm_vod_stream_detection(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            return b"#EXTM3U\nhttps://vod-content.plexvideos.com/streams/id/session/cbcs/stream.m3u8"

    monkeypatch.setattr("plextui.player.urlopen", lambda *args, **kwargs: Response())

    assert is_drm_vod_stream("https://vod.provider.plex.tv/library/parts/item-hls.m3u8")


def test_non_drm_vod_stream_detection(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            return b"#EXTM3U\nhttps://vod-content.plexvideos.com/streams/id/plain/stream.m3u8"

    monkeypatch.setattr("plextui.player.urlopen", lambda *args, **kwargs: Response())

    assert not is_drm_vod_stream("https://vod.provider.plex.tv/library/parts/item-hls.m3u8")


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
    assert args[-1] == "http://plex/library/parts/1/file.mkv"
    assert handle.stream_mode == "direct"
    assert not hasattr(item.full_item, "kwargs")


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


def test_terminal_playback_uses_tct_and_terminal_output():
    item = Item()
    tty = MagicMock()

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch.dict("plextui.player.os.environ", {}, clear=True),
        patch("plextui.player.shutil.get_terminal_size", return_value=terminal_size((100, 30))),
        patch("plextui.player.Path.open", return_value=tty) as tty_open,
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        play_with_mpv(item, window_size="1280x720", playback_display="terminal")

    args = popen.call_args.args[0]
    kwargs = popen.call_args.kwargs
    assert "--vo=tct" in args
    assert "--terminal=yes" in args
    assert "--no-terminal" not in args
    assert "--force-window=immediate" not in args
    assert "--focus-on=all" not in args
    assert "--vo-tct-buffering=frame" in args
    assert "--vo-tct-width=100" in args
    assert "--vo-tct-height=28" in args
    assert "--vf=fps=12,scale=480:-2" in args
    assert "--profile=sw-fast" in args
    assert "--really-quiet" in args
    assert "--autofit=1280x720" not in args
    tty_open.assert_any_call("r+b", buffering=0)
    assert kwargs["stdin"] is tty
    assert kwargs["stdout"] is tty
    assert kwargs["stderr"] is tty
    assert kwargs["start_new_session"] is False
    tty.close.assert_called_once()


def test_terminal_playback_prefers_kitty_video_when_supported():
    item = Item()
    tty = MagicMock()

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch.dict("plextui.player.os.environ", {"TERM_PROGRAM": "ghostty"}, clear=True),
        patch("plextui.player.Path.open", return_value=tty),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        play_with_mpv(item, playback_display="terminal", terminal_video_profile="sharp")

    args = popen.call_args.args[0]
    assert "--vo=kitty" in args
    assert "--terminal=yes" in args
    assert "--vf=fps=24,scale=960:-2" in args
    assert "--vo=tct" not in args
    assert not any(arg.startswith("--vo-tct-") for arg in args)


def test_terminal_playback_balanced_profile_scales_terminal_video():
    item = Item()
    tty = MagicMock()

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch.dict("plextui.player.os.environ", {"KITTY_WINDOW_ID": "1", "TERM": "xterm-kitty"}, clear=True),
        patch("plextui.player.Path.open", return_value=tty),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        play_with_mpv(item, playback_display="terminal", terminal_video_profile="balanced")

    args = popen.call_args.args[0]
    assert "--vo=kitty" in args
    assert "--vf=fps=15,scale=640:-2" in args


def test_terminal_playback_can_force_tct_when_kitty_is_supported():
    item = Item()
    tty = MagicMock()

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch.dict("plextui.player.os.environ", {"KITTY_WINDOW_ID": "1", "TERM": "xterm-kitty"}, clear=True),
        patch("plextui.player.Path.open", return_value=tty),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        play_with_mpv(item, playback_display="terminal", terminal_video_output="tct")

    args = popen.call_args.args[0]
    assert "--vo=tct" in args
    assert "--vo=kitty" not in args
    assert "--vo-tct-buffering=frame" in args


def test_terminal_playback_can_force_kitty_without_kitty_env():
    item = Item()
    tty = MagicMock()

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch.dict("plextui.player.os.environ", {}, clear=True),
        patch("plextui.player.Path.open", return_value=tty),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        play_with_mpv(item, playback_display="terminal", terminal_video_output="kitty")

    args = popen.call_args.args[0]
    assert "--vo=kitty" in args
    assert "--vo=tct" not in args


def test_terminal_playback_can_force_sixel_output():
    item = Item()
    tty = MagicMock()

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.Path.open", return_value=tty),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        play_with_mpv(item, playback_display="terminal", terminal_video_output="sixel")

    args = popen.call_args.args[0]
    assert "--vo=sixel" in args
    assert "--vf=fps=12,scale=480:-2" in args


def test_terminal_playback_can_force_drm_output():
    item = Item()
    tty = MagicMock()

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.Path.open", return_value=tty),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()) as popen,
    ):
        play_with_mpv(item, playback_display="terminal", terminal_video_output="drm")

    args = popen.call_args.args[0]
    assert "--vo=drm" in args
    assert "--terminal=yes" in args
    assert not any(arg.startswith("--vf=") for arg in args)


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
    assert handle.stream_mode == "direct"
    assert "--sid=no" in args
    assert "--start=65.000" in args
    assert not hasattr(item, "kwargs")
    assert not any(arg.startswith("--sub-file=") for arg in args)


def test_progress_monitor_reports_progress_and_timeline():
    item = Item()
    monitor = ProgressMonitor(item, Proc(), Path("/tmp/no-socket"), 0)
    monitor.last_ms = 123000

    monitor.report("playing")

    assert item.progress == (123000, "playing")
    assert item.timeline == (123000, "playing")


def test_progress_monitor_adds_base_offset_to_transcode_time():
    item = Item()
    monitor = ProgressMonitor(item, Proc(), Path("/tmp/socket"), 65000, base_offset=65000)

    with patch("plextui.player.mpv_get_property", return_value=12.5):
        assert monitor.current_time_ms() == 77500


def test_plex_stream_offset_converts_milliseconds_to_seconds():
    assert plex_stream_offset(65_999) == 65
    assert plex_stream_offset(-1) == 0


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
    assert "--start=65.000" in args
    assert "--aid=1" in args
    assert "--sid=1" in args


def test_switch_mpv_stream_sets_audio_track():
    item = Item()
    handle = type(
        "Handle",
        (),
        {
            "active": True,
            "socket_path": Path("/tmp/socket"),
        },
    )()
    audio = Part().audioStreams()[0]

    with patch("plextui.player.mpv_set_property", return_value=True) as set_property:
        assert switch_mpv_stream(handle, item, StreamChoice(42, "Japanese", audio), "audio")

    set_property.assert_called_once_with(Path("/tmp/socket"), "aid", 1)


def test_switch_mpv_stream_can_disable_subtitles():
    item = Item()
    handle = type(
        "Handle",
        (),
        {
            "active": True,
            "socket_path": Path("/tmp/socket"),
        },
    )()

    with patch("plextui.player.mpv_set_property", return_value=True) as set_property:
        assert switch_mpv_stream(handle, item, StreamChoice(0, "None"), "subtitle")

    set_property.assert_called_once_with(Path("/tmp/socket"), "sid", "no")


def test_toggle_mpv_pause_sends_cycle_pause():
    handle = type("Handle", (), {"active": True, "socket_path": Path("/tmp/socket")})()

    with patch("plextui.player.mpv_command", return_value={"error": "success"}) as command:
        assert toggle_mpv_pause(handle)

    command.assert_called_once_with(Path("/tmp/socket"), ["cycle", "pause"])


def test_seek_mpv_sends_relative_seek():
    handle = type("Handle", (), {"active": True, "socket_path": Path("/tmp/socket")})()

    with patch("plextui.player.mpv_command", return_value={"error": "success"}) as command:
        assert seek_mpv(handle, -10)

    command.assert_called_once_with(Path("/tmp/socket"), ["seek", -10, "relative+exact"])


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
        "offset": 65,
    }
    assert not any(arg.startswith("--sid=") for arg in args)
    assert "--start=65.000" not in args


def test_force_transcode_original_quality_omits_quality_kwargs():
    item = Item()

    with (
        patch("plextui.player.shutil.which", return_value="/usr/bin/mpv"),
        patch("plextui.player.ProgressMonitor.start"),
        patch("plextui.player.subprocess.Popen", return_value=Proc()),
    ):
        handle = play_with_mpv(item, playback_mode="transcode", transcode_quality="original")

    assert handle.stream_mode == "transcode"
    assert item.kwargs == {"offset": 65}


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


def test_debug_log_redaction_keeps_sanitized_command_list_readable(debug_log_path):
    log_debug(
        "launching mpv: args="
        f"{['mpv', '--sub-file=http://plex/sub.srt?X-Plex-Token=secret', 'http://plex/video.mkv']!r}"
    )

    text = debug_log_path.read_text(encoding="utf-8")
    assert "secret" not in text
    assert "--sub-file=http://plex/sub.srt?X-Plex-Token=REDACTED', 'http://plex/video.mkv'" in text


def test_mpv_stderr_logs_output_and_nonzero_exit(debug_log_path):
    class FailedProc:
        stderr = [b"[ffmpeg] HTTP error 403\n"]

        def wait(self, timeout=None):
            return 4

    _log_mpv_stderr(FailedProc())

    text = debug_log_path.read_text(encoding="utf-8")
    assert "mpv: [ffmpeg] HTTP error 403" in text
    assert "mpv exited with status 4" in text


def test_mpv_stdout_logs_output_and_nonzero_exit(debug_log_path):
    class FailedProc:
        stdout = [b"Error parsing option focus-on (option not found)\n"]
        stderr = None

        def wait(self, timeout=None):
            return 2

    _log_mpv_stderr(FailedProc(), FailedProc.stdout)

    text = debug_log_path.read_text(encoding="utf-8")
    assert "mpv: Error parsing option focus-on" in text
    assert "mpv exited with status 2" in text


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
            play_with_mpv(EmptyUrlItem(), playback_mode="transcode")
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
