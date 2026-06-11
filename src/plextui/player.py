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

    try:
        url = item.getStreamURL()
    except Exception as exc:
        raise PlayerError(f"could not get stream URL: {exc}") from exc

    title = getattr(item, "title", "Plex")
    subtitles = external_subtitle_urls(item)
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
    return PlayerHandle(title=title, subtitle_count=len(subtitles), process=process)


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
