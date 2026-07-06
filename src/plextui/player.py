from __future__ import annotations

import os
import json
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .config import write_debug_log


class PlayerError(RuntimeError):
    pass


@dataclass
class PlayerHandle:
    title: str
    subtitle_count: int
    stream_mode: str
    start_offset_ms: int
    socket_path: Path
    command: list[str]
    monitor: "ProgressMonitor"
    process: subprocess.Popen[bytes]

    @property
    def active(self) -> bool:
        return self.process.poll() is None


@dataclass(frozen=True)
class StreamChoice:
    stream_id: int | None
    label: str
    stream: Any = None


TRANSCODE_QUALITY_OPTIONS: dict[str, tuple[str, int | None, str]] = {
    "original": ("Original", None, ""),
    "1080p_8": ("1080p 8 Mbps", 8000, "1920x1080"),
    "720p_4": ("720p 4 Mbps", 4000, "1280x720"),
    "480p_2": ("480p 2 Mbps", 2000, "720x480"),
}
TERMINAL_VIDEO_FILTERS = {
    "smooth": "fps=12,scale=480:-2",
    "balanced": "fps=15,scale=640:-2",
    "sharp": "fps=24,scale=960:-2",
}
MPV_NETWORK_CACHE_ARGS = [
    "--cache=yes",
    "--demuxer-max-bytes=128MiB",
    "--demuxer-readahead-secs=20",
    "--cache-pause=no",
]


def play_with_mpv(
    item: Any,
    subtitle_choice: StreamChoice | None = None,
    audio_choice: StreamChoice | None = None,
    window_size: str = "",
    playback_mode: str = "auto",
    playback_display: str = "external",
    terminal_video_output: str = "auto",
    terminal_video_profile: str = "smooth",
    transcode_quality: str = "original",
    resume: bool = True,
) -> PlayerHandle:
    if shutil.which("mpv") is None:
        log_debug("playback error: mpv was not found in PATH")
        raise PlayerError("mpv was not found in PATH. Install mpv and make sure it is available on PATH.")

    browse_item = item
    selected_start_offset = resume_offset_ms(item)
    item = full_metadata(item)
    selected_subtitle = resolve_subtitle_choice(item, subtitle_choice)
    selected_audio = resolve_audio_choice(item, audio_choice)
    subtitles = external_subtitle_urls(item, selected_subtitle)
    stream_kwargs = {}
    force_transcode = playback_mode == "transcode"
    direct_url = None if force_transcode else direct_play_url(item, selected_subtitle) or direct_play_url(browse_item, selected_subtitle)
    fallback_subtitle_id = selected_subtitle_stream_id(item, selected_subtitle) if not subtitles and not direct_url else None
    if fallback_subtitle_id is not None:
        stream_kwargs["subtitleStreamID"] = fallback_subtitle_id
    if selected_audio is not None:
        stream_kwargs["audioStreamID"] = getattr(selected_audio, "id", selected_audio)
    if force_transcode:
        stream_kwargs.update(transcode_quality_kwargs(transcode_quality))

    title = getattr(item, "title", None) or getattr(browse_item, "title", None) or "Plex"
    start_offset = (resume_offset_ms(item) or selected_start_offset) if resume else 0
    if start_offset and direct_url is None:
        stream_kwargs["offset"] = plex_stream_offset(start_offset)

    if is_online_metadata(item) and direct_url is None:
        log_debug("playback error: Plex lists this item but does not provide a playable VOD stream")
        raise PlayerError("Plex lists this item, but does not provide a playable stream for external players")
    try:
        url = direct_url or item.getStreamURL(**stream_kwargs)
    except Exception as exc:
        log_debug(f"playback error: could not get stream URL: {exc}")
        raise PlayerError(f"could not get stream URL from Plex: {exc}") from exc
    if not url:
        log_debug("playback error: Plex returned an empty stream URL")
        raise PlayerError("Plex returned an empty stream URL")
    if direct_url and is_drm_vod_stream(url):
        log_debug("playback error: Plex exposed a DRM-protected VOD stream")
        raise PlayerError("Plex lists this item, but does not provide a playable stream for external players")

    stream_mode = "direct" if direct_url else "transcode"
    monitor_base_offset = start_offset if stream_mode == "transcode" and stream_kwargs.get("offset") else 0
    socket_path = Path(tempfile.gettempdir()) / f"plex-tui-mpv-{os.getpid()}-{int(time.time() * 1000)}.sock"
    args = [
        "mpv",
        "--force-media-title=" + title,
        "--input-ipc-server=" + str(socket_path),
    ]
    args.extend(MPV_NETWORK_CACHE_ARGS)
    if playback_display == "terminal":
        args.extend(terminal_video_args(terminal_video_output, terminal_video_profile))
    else:
        args.extend(["--no-terminal", "--force-window=immediate", "--focus-on=all"])
    if start_offset and not monitor_base_offset:
        args.append(f"--start={start_offset / 1000:.3f}")
    if window_size and playback_display != "terminal":
        args.append(f"--autofit={window_size}")
    args.extend(direct_track_args(direct_url, item, selected_audio, selected_subtitle))
    for subtitle in subtitles:
        args.append("--sub-file=" + subtitle)
    args.append(url)
    command = sanitize_command(args)
    quality_label = transcode_quality_label(transcode_quality) if stream_mode == "transcode" else "original"
    log_debug(
        "launching mpv: "
        f"title={title!r} mode={stream_mode} "
        f"display={playback_display!r} "
        f"quality={quality_label!r} "
        f"audio={stream_debug_label(selected_audio)} "
        f"subtitle={stream_debug_label(selected_subtitle)} "
        f"args={command!r}"
    )
    stdin = stdout = stderr = None
    tty = None
    if playback_display == "terminal" and os.name != "nt":
        try:
            tty = Path("/dev/tty").open("r+b", buffering=0)
            stdin = stdout = stderr = tty
        except OSError as exc:
            log_debug(f"terminal playback warning: could not open /dev/tty: {exc}")
    elif playback_display != "terminal":
        stdin = subprocess.DEVNULL
    try:
        process = subprocess.Popen(
            args,
            stdin=stdin,
            stdout=stdout if playback_display == "terminal" else subprocess.DEVNULL,
            stderr=stderr if playback_display == "terminal" else subprocess.PIPE,
            start_new_session=playback_display != "terminal",
        )
    except OSError as exc:
        log_debug(f"playback error: failed to launch mpv: {exc}; args={command!r}")
        raise PlayerError(f"failed to launch mpv: {exc}") from exc
    finally:
        if tty is not None:
            tty.close()
    subtitle_count = active_subtitle_count(item, selected_subtitle)
    if playback_display != "terminal":
        log_mpv_stderr(process)
    monitor = ProgressMonitor(item, process, socket_path, start_offset, base_offset=monitor_base_offset)
    monitor.start()
    return PlayerHandle(
        title=title,
        subtitle_count=subtitle_count,
        stream_mode=stream_mode,
        start_offset_ms=start_offset,
        socket_path=socket_path,
        command=command,
        monitor=monitor,
        process=process,
    )


def log_mpv_stderr(process: subprocess.Popen[bytes]) -> None:
    if getattr(process, "stderr", None) is None:
        return

    def read_stderr() -> None:
        for raw_line in process.stderr or ():
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                write_debug_log(f"mpv: {redact_tokens(line)}")

    threading.Thread(target=read_stderr, name="plex-tui-mpv-stderr", daemon=True).start()


class ProgressMonitor:
    def __init__(
        self,
        item: Any,
        process: subprocess.Popen[bytes],
        socket_path: Path,
        start_offset: int,
        base_offset: int = 0,
    ) -> None:
        self.item = item
        self.process = process
        self.socket_path = socket_path
        self.last_ms = start_offset
        self.base_offset = base_offset
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="plex-tui-progress", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.report("stopped")

    def _run(self) -> None:
        deadline = time.time() + 5
        while time.time() < deadline and not self.socket_path.exists() and self.process.poll() is None:
            time.sleep(0.1)

        self.report("playing")
        last_report = 0.0
        while not self._stop.is_set() and self.process.poll() is None:
            ms = self.current_time_ms()
            if ms is not None:
                self.last_ms = ms
            now = time.time()
            if self.last_ms and now - last_report >= 10:
                self.report("playing")
                last_report = now
            time.sleep(2)

        if not self._stop.is_set():
            ms = self.current_time_ms()
            if ms is not None:
                self.last_ms = ms
            self.report("stopped")
        cleanup_socket(self.socket_path)

    def current_time_ms(self) -> int | None:
        value = mpv_get_property(self.socket_path, "time-pos")
        if value is None:
            return None
        try:
            return max(0, self.base_offset + int(float(value) * 1000))
        except (TypeError, ValueError):
            return None

    def report(self, state: str) -> None:
        if not self.last_ms:
            return
        try:
            self.item.updateProgress(self.last_ms, state=state)
            self.item.updateTimeline(self.last_ms, state=state)
        except Exception:
            return


def mpv_get_property(socket_path: Path, property_name: str) -> Any:
    response = mpv_command(socket_path, ["get_property", property_name])
    if not response or response.get("error") != "success":
        return None
    return response.get("data")


def mpv_set_property(socket_path: Path, property_name: str, value: Any) -> bool:
    response = mpv_command(socket_path, ["set_property", property_name, value])
    return bool(response and response.get("error") == "success")


def toggle_mpv_pause(handle: PlayerHandle) -> bool:
    if not handle.active:
        return False
    response = mpv_command(handle.socket_path, ["cycle", "pause"])
    return bool(response and response.get("error") == "success")


def seek_mpv(handle: PlayerHandle, seconds: int) -> bool:
    if not handle.active:
        return False
    response = mpv_command(handle.socket_path, ["seek", seconds, "relative+exact"])
    return bool(response and response.get("error") == "success")


def mpv_command(socket_path: Path, command: list[Any]) -> dict[str, Any] | None:
    if not socket_path.exists():
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            sock.connect(str(socket_path))
            payload = {"command": command}
            sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            data = sock.recv(4096)
    except OSError:
        return None
    try:
        response = json.loads(data.decode("utf-8").splitlines()[0])
    except (IndexError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return response


def cleanup_socket(socket_path: Path) -> None:
    try:
        socket_path.unlink(missing_ok=True)
    except OSError:
        return


def resume_offset_ms(item: Any) -> int:
    try:
        return max(0, int(getattr(item, "viewOffset", 0) or 0))
    except (TypeError, ValueError):
        return 0


def plex_stream_offset(milliseconds: int) -> int:
    return max(0, milliseconds // 1000)


def full_metadata(item: Any) -> Any:
    if is_online_metadata(item):
        online_item = online_vod_metadata(item)
        return online_item or item
    if not hasattr(item, "reload"):
        return item
    try:
        return item.reload()
    except Exception:
        return item


def online_vod_metadata(item: Any) -> Any | None:
    key = metadata_item_key(item)
    server = getattr(item, "_server", None)
    fetch_item = getattr(server, "fetchItem", None)
    if not key or not callable(fetch_item):
        return None
    old_baseurl = getattr(server, "_baseurl", None)
    try:
        server._baseurl = vod_provider_base(item, server)
        return fetch_item(key)
    except Exception:
        return None
    finally:
        if old_baseurl is not None:
            server._baseurl = old_baseurl


def metadata_item_key(item: Any) -> str:
    key = str(getattr(item, "key", "") or "")
    if key:
        return key
    details_key = str(getattr(item, "_details_key", "") or "").split("?", 1)[0]
    if details_key:
        return details_key
    guid = str(getattr(item, "guid", "") or "")
    if guid.startswith("plex://") and "/" in guid:
        return "/library/metadata/" + guid.rsplit("/", 1)[-1]
    return ""


def resolve_subtitle_choice(item: Any, choice: StreamChoice | None) -> Any:
    if choice is None:
        return None
    if choice.stream_id == 0:
        return 0
    return find_stream_by_id(subtitle_streams(item), choice.stream_id) or choice.stream


def resolve_audio_choice(item: Any, choice: StreamChoice | None) -> Any:
    if choice is None:
        return None
    return find_stream_by_id(audio_streams(item), choice.stream_id) or choice.stream


def transcode_quality_kwargs(value: str) -> dict[str, object]:
    _label, bitrate, resolution = TRANSCODE_QUALITY_OPTIONS.get(value, TRANSCODE_QUALITY_OPTIONS["original"])
    kwargs: dict[str, object] = {}
    if bitrate is not None:
        kwargs["maxVideoBitrate"] = bitrate
    if resolution:
        kwargs["videoResolution"] = resolution
    return kwargs


def transcode_quality_label(value: str) -> str:
    return TRANSCODE_QUALITY_OPTIONS.get(value, TRANSCODE_QUALITY_OPTIONS["original"])[0]


def external_subtitle_urls(item: Any, selected_subtitle: Any = None) -> list[str]:
    urls: list[str] = []
    if is_online_metadata(item):
        return urls
    if selected_subtitle == 0:
        return urls
    for part in iter_parts(item):
        for stream in part.subtitleStreams():
            if selected_subtitle is not None and not same_stream(stream, selected_subtitle):
                continue
            key = getattr(stream, "key", None)
            if not key:
                continue
            server = getattr(stream, "_server", None) or getattr(part, "_server", None)
            if server is None:
                continue
            urls.append(server.url(key, includeToken=True))
    return urls


def direct_play_url(item: Any, selected_subtitle: Any = None) -> str | None:
    return first_part_url(item)


def is_drm_vod_stream(url: str) -> bool:
    if "vod.provider.plex.tv" not in url:
        return False
    try:
        with urlopen(url, timeout=5) as response:
            text = response.read(4096).decode("utf-8", errors="replace").lower()
    except Exception:
        return False
    return "/cbcs/" in text or "method=sample-aes" in text


def first_part_url(item: Any) -> str | None:
    parts = iter_parts(item)
    if not parts:
        return None
    part = parts[0]
    key = getattr(part, "key", None)
    server = getattr(part, "_server", None)
    if not key or server is None:
        return None
    url = server.url(key, includeToken=True)
    if is_metadata_provider_server(server):
        vod_base = vod_provider_base(item, server)
        metadata_base = str(getattr(server, "_baseurl", "") or "").rstrip("/")
        if vod_base and metadata_base:
            url = url.replace(metadata_base, vod_base, 1)
    return url


def vod_provider_base(item: Any, fallback_server: Any) -> str:
    for candidate in (getattr(item, "_server", None), fallback_server):
        baseurl = str(getattr(candidate, "VOD", "") or "")
        if baseurl:
            return baseurl.rstrip("/")
    return "https://vod.provider.plex.tv"


def is_online_metadata(item: Any) -> bool:
    if is_metadata_provider_server(getattr(item, "_server", None)):
        return True
    parts = iter_parts(item)
    return bool(parts and is_metadata_provider_server(getattr(parts[0], "_server", None)))


def is_metadata_provider_server(server: Any) -> bool:
    baseurl = str(getattr(server, "_baseurl", "") or "")
    return "metadata.provider.plex.tv" in baseurl


def selected_subtitle_stream_id(item: Any, selected_subtitle: Any = None) -> int | None:
    if selected_subtitle == 0:
        return 0
    if selected_subtitle is not None:
        return getattr(selected_subtitle, "id", None)
    streams = subtitle_streams(item)
    selected = [stream for stream in streams if getattr(stream, "selected", False)]
    candidates = selected or preferred_subtitle_streams(streams)
    if not candidates:
        return None
    return getattr(candidates[0], "id", None)


def direct_track_args(
    direct_url: str | None,
    item: Any,
    selected_audio: Any = None,
    selected_subtitle: Any = None,
) -> list[str]:
    if not direct_url:
        return []
    args: list[str] = []
    if selected_audio is not None:
        track_id = mpv_track_id(audio_streams(item), selected_audio)
        if track_id is not None:
            args.append(f"--aid={track_id}")
    if selected_subtitle == 0:
        args.append("--sid=no")
    elif selected_subtitle is not None:
        track_id = mpv_track_id(subtitle_streams(item), selected_subtitle)
        if track_id is not None:
            args.append(f"--sid={track_id}")
    return args


def switch_mpv_stream(
    handle: PlayerHandle,
    item: Any,
    choice: StreamChoice,
    stream_type: str,
) -> bool:
    if not handle.active:
        return False
    if stream_type == "subtitle":
        if choice.stream_id == 0:
            return mpv_set_property(handle.socket_path, "sid", "no")
        if choice.stream_id is None:
            return mpv_set_property(handle.socket_path, "sid", "auto")
        track_id = mpv_track_id(subtitle_streams(full_metadata(item)), choice.stream)
        if track_id is None:
            return False
        return mpv_set_property(handle.socket_path, "sid", track_id)
    if stream_type == "audio":
        track_id = mpv_track_id(audio_streams(full_metadata(item)), choice.stream)
        if track_id is None:
            return False
        return mpv_set_property(handle.socket_path, "aid", track_id)
    return False


def mpv_track_id(streams: list[Any], selected_stream: Any) -> int | None:
    for index, stream in enumerate(streams, start=1):
        if same_stream(stream, selected_stream):
            return index
    return None


def preferred_subtitle_streams(streams: list[Any]) -> list[Any]:
    preferred_codecs = {"srt", "ass", "ssa", "vtt", "idx", "sub"}
    preferred = [
        stream
        for stream in streams
        if str(getattr(stream, "codec", "")).lower() in preferred_codecs
    ]
    return preferred or streams


def subtitle_streams(item: Any) -> list[Any]:
    streams: list[Any] = []
    for part in iter_parts(item):
        streams.extend(part.subtitleStreams())
    return streams


def active_subtitle_count(item: Any, selected_subtitle: Any = None) -> int:
    if selected_subtitle == 0:
        return 0
    if selected_subtitle is not None:
        return 1
    return len(subtitle_streams(item))


def audio_streams(item: Any) -> list[Any]:
    streams: list[Any] = []
    for part in iter_parts(item):
        streams.extend(part.audioStreams())
    return streams


def subtitle_choices(item: Any) -> list[StreamChoice]:
    item = full_metadata(item)
    choices = [StreamChoice(None, "Auto (Plex/default)"), StreamChoice(0, "None (disable subtitles)")]
    choices.extend(StreamChoice(getattr(stream, "id", None), stream_label(stream), stream) for stream in subtitle_streams(item))
    return choices


def audio_choices(item: Any) -> list[StreamChoice]:
    item = full_metadata(item)
    return [StreamChoice(getattr(stream, "id", None), stream_label(stream), stream) for stream in audio_streams(item)]


def stream_label(stream: Any) -> str:
    label = getattr(stream, "displayTitle", None) or getattr(stream, "language", None) or "Unknown"
    codec = getattr(stream, "codec", None)
    flags = []
    if getattr(stream, "selected", False):
        flags.append("selected")
    if getattr(stream, "forced", False):
        flags.append("forced")
    if getattr(stream, "hearingImpaired", False):
        flags.append("SDH")
    channels = getattr(stream, "channels", None)
    if channels:
        flags.append(f"{channels}ch")
    values = [str(codec)] if codec else []
    values.extend(flags)
    suffix = ", ".join(values)
    return f"{label} ({suffix})" if suffix else str(label)


def preferred_audio_choice(item: Any, preferred_language: str) -> StreamChoice | None:
    return preferred_stream_choice(audio_choices(item), preferred_language)


def preferred_subtitle_choice(item: Any, preferred_language: str, subtitle_mode: str) -> StreamChoice | None:
    if subtitle_mode == "none":
        return StreamChoice(0, "None (disable subtitles)")
    if subtitle_mode != "preferred" or not preferred_language:
        return None
    return preferred_stream_choice(subtitle_choices(item), preferred_language)


def preferred_stream_choice(choices: list[StreamChoice], preferred_language: str) -> StreamChoice | None:
    preferred = normalize_language(preferred_language)
    if not preferred:
        return None
    for choice in choices:
        if choice.stream is not None and stream_language_key(choice.stream) == preferred:
            return choice
    return None


def stream_language_key(stream: Any) -> str:
    for attr in ("languageCode", "language", "displayTitle"):
        value = normalize_language(getattr(stream, attr, ""))
        if value:
            return value
    return ""


def stream_language_label(stream: Any) -> str:
    for attr in ("language", "displayTitle", "languageCode"):
        value = str(getattr(stream, attr, "") or "").strip()
        if value:
            return value
    return "unknown"


def normalize_language(value: Any) -> str:
    return str(value or "").strip().lower()


def find_stream_by_id(streams: list[Any], stream_id: int | None) -> Any:
    if stream_id is None:
        return None
    for stream in streams:
        if getattr(stream, "id", None) == stream_id:
            return stream
    return None


def same_stream(left: Any, right: Any) -> bool:
    left_id = getattr(left, "id", None)
    right_id = getattr(right, "id", None)
    if left_id is not None and right_id is not None:
        return left_id == right_id
    return left is right


def iter_parts(item: Any) -> list[Any]:
    if hasattr(item, "iterParts"):
        return list(item.iterParts())
    parts: list[Any] = []
    for media in getattr(item, "media", []) or []:
        parts.extend(getattr(media, "parts", []) or [])
    return parts


def stop_mpv(handle: PlayerHandle | None) -> None:
    if handle is None or not handle.active:
        return
    handle.monitor.stop()
    try:
        if os.name != "nt":
            os.killpg(handle.process.pid, signal.SIGTERM)
        else:
            handle.process.terminate()
    except ProcessLookupError:
        return
    finally:
        cleanup_socket(handle.socket_path)


def sanitize_command(args: list[str]) -> list[str]:
    return [sanitize_arg(arg) for arg in args]


def terminal_video_args(output: str = "auto", profile: str = "smooth") -> list[str]:
    video_filter = TERMINAL_VIDEO_FILTERS.get(profile, TERMINAL_VIDEO_FILTERS["smooth"])
    selected_output = output if output in {"auto", "kitty", "sixel", "tct", "drm"} else "auto"
    if selected_output == "auto":
        selected_output = "kitty" if terminal_kitty_graphics_supported() else "tct"
    if selected_output in {"kitty", "sixel"}:
        return [
            f"--vo={selected_output}",
            "--terminal=yes",
            f"--vf={video_filter}",
            "--profile=sw-fast",
            "--really-quiet",
        ]
    if selected_output == "drm":
        return [
            "--vo=drm",
            "--terminal=yes",
            "--profile=sw-fast",
            "--really-quiet",
        ]
    size = shutil.get_terminal_size(fallback=(120, 40))
    width = max(40, size.columns)
    height = max(12, size.lines - 2)
    return [
        "--vo=tct",
        "--terminal=yes",
        "--vo-tct-buffering=frame",
        f"--vo-tct-width={width}",
        f"--vo-tct-height={height}",
        f"--vf={video_filter}",
        "--profile=sw-fast",
        "--really-quiet",
    ]


def terminal_kitty_graphics_supported() -> bool:
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    term = os.environ.get("TERM", "").lower()
    if os.environ.get("KITTY_WINDOW_ID") or os.environ.get("KITTY_PID"):
        return term_program == "kitty" or term.startswith("xterm-kitty")
    return term_program == "ghostty" or term.startswith("xterm-ghostty")


def sanitize_arg(arg: str) -> str:
    if arg.startswith("--sub-file="):
        return "--sub-file=" + sanitize_url(arg.removeprefix("--sub-file="))
    if "://" in arg:
        return sanitize_url(arg)
    return arg


def sanitize_url(url: str) -> str:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return url
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in {"token", "x-plex-token"}:
            query.append((key, "REDACTED"))
        else:
            query.append((key, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def stream_debug_label(stream: Any) -> str:
    if stream is None:
        return "auto"
    if stream == 0:
        return "none"
    label = getattr(stream, "displayTitle", None) or getattr(stream, "language", None) or getattr(stream, "id", None)
    return str(label or "unknown")


def log_debug(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    write_debug_log(f"{timestamp} {redact_tokens(message)}")


def redact_tokens(text: str) -> str:
    return re.sub(r"(?i)(x-plex-token|token)=([^&\s]+)", r"\1=REDACTED", text)
