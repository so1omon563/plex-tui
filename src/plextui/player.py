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
    process = subprocess.Popen(
        ["mpv", "--force-media-title=" + title, url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return PlayerHandle(title=title, process=process)


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
