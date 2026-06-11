from __future__ import annotations

import os
import shutil
import signal
import subprocess
from dataclasses import dataclass
from typing import Any


class PlayerError(RuntimeError):
    pass


@dataclass
class PlayerHandle:
    title: str
    subtitle_count: int
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
    fallback_subtitle_id = selected_subtitle_stream_id(item) if not subtitles else None
    if fallback_subtitle_id is not None:
        stream_kwargs["subtitleStreamID"] = fallback_subtitle_id

    try:
        url = item.getStreamURL(**stream_kwargs)
    except Exception as exc:
        raise PlayerError(f"could not get stream URL: {exc}") from exc

    title = getattr(item, "title", "Plex")
    args = ["mpv", "--force-media-title=" + title]
    for subtitle in subtitles:
        args.append("--sub-file=" + subtitle)
    args.append(url)
    process = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    subtitle_count = len(subtitles) + (1 if fallback_subtitle_id is not None else 0)
    return PlayerHandle(title=title, subtitle_count=subtitle_count, process=process)


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
    try:
        if os.name != "nt":
            os.killpg(handle.process.pid, signal.SIGTERM)
        else:
            handle.process.terminate()
    except ProcessLookupError:
        return
