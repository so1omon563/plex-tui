from __future__ import annotations

import os
import json
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


class PlayerError(RuntimeError):
    pass


@dataclass
class PlayerHandle:
    title: str
    subtitle_count: int
    stream_mode: str
    start_offset_ms: int
    socket_path: Path
    monitor: "ProgressMonitor"
    process: subprocess.Popen[bytes]

    @property
    def active(self) -> bool:
        return self.process.poll() is None


def play_with_mpv(item: Any) -> PlayerHandle:
    if shutil.which("mpv") is None:
        raise PlayerError("mpv was not found in PATH")

    item = full_metadata(item)
    subtitles = external_subtitle_urls(item)
    stream_kwargs = {}
    direct_url = direct_play_url(item)
    fallback_subtitle_id = selected_subtitle_stream_id(item) if not subtitles and not direct_url else None
    if fallback_subtitle_id is not None:
        stream_kwargs["subtitleStreamID"] = fallback_subtitle_id

    try:
        url = direct_url or item.getStreamURL(**stream_kwargs)
    except Exception as exc:
        raise PlayerError(f"could not get stream URL: {exc}") from exc

    title = getattr(item, "title", "Plex")
    start_offset = resume_offset_ms(item)
    socket_path = Path(tempfile.gettempdir()) / f"plex-tui-mpv-{os.getpid()}-{int(time.time() * 1000)}.sock"
    args = [
        "mpv",
        "--force-media-title=" + title,
        "--input-ipc-server=" + str(socket_path),
    ]
    if start_offset:
        args.append(f"--start={start_offset / 1000:.3f}")
    for subtitle in subtitles:
        args.append("--sub-file=" + subtitle)
    args.append(url)
    process = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    subtitle_count = len(subtitle_streams(item))
    stream_mode = "direct" if direct_url else "transcode"
    monitor = ProgressMonitor(item, process, socket_path, start_offset)
    monitor.start()
    return PlayerHandle(
        title=title,
        subtitle_count=subtitle_count,
        stream_mode=stream_mode,
        start_offset_ms=start_offset,
        socket_path=socket_path,
        monitor=monitor,
        process=process,
    )


class ProgressMonitor:
    def __init__(self, item: Any, process: subprocess.Popen[bytes], socket_path: Path, start_offset: int) -> None:
        self.item = item
        self.process = process
        self.socket_path = socket_path
        self.last_ms = start_offset
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
            return max(0, int(float(value) * 1000))
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
    if not socket_path.exists():
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            sock.connect(str(socket_path))
            payload = {"command": ["get_property", property_name]}
            sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            data = sock.recv(4096)
    except OSError:
        return None
    try:
        response = json.loads(data.decode("utf-8").splitlines()[0])
    except (IndexError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if response.get("error") != "success":
        return None
    return response.get("data")


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


def full_metadata(item: Any) -> Any:
    if not hasattr(item, "reload"):
        return item
    try:
        return item.reload()
    except Exception:
        return item


def external_subtitle_urls(item: Any) -> list[str]:
    urls: list[str] = []
    for part in iter_parts(item):
        for stream in part.subtitleStreams():
            key = getattr(stream, "key", None)
            if not key:
                continue
            server = getattr(stream, "_server", None) or getattr(part, "_server", None)
            if server is None:
                continue
            urls.append(server.url(key, includeToken=True))
    return urls


def direct_play_url(item: Any) -> str | None:
    if not has_embedded_subtitles(item):
        return None
    parts = iter_parts(item)
    if not parts:
        return None
    part = parts[0]
    key = getattr(part, "key", None)
    server = getattr(part, "_server", None)
    if not key or server is None:
        return None
    return server.url(key, includeToken=True)


def has_embedded_subtitles(item: Any) -> bool:
    embedded_codecs = {"pgs", "vobsub", "idx"}
    for stream in subtitle_streams(item):
        codec = str(getattr(stream, "codec", "")).lower()
        if codec in embedded_codecs and not getattr(stream, "key", None):
            return True
    return False


def selected_subtitle_stream_id(item: Any) -> int | None:
    streams = subtitle_streams(item)
    selected = [stream for stream in streams if getattr(stream, "selected", False)]
    candidates = selected or preferred_subtitle_streams(streams)
    if not candidates:
        return None
    return getattr(candidates[0], "id", None)


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
