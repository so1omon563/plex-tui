from __future__ import annotations

import shutil
import subprocess
from typing import Any


class PlayerError(RuntimeError):
    pass


def play_with_mpv(item: Any) -> None:
    if shutil.which("mpv") is None:
        raise PlayerError("mpv was not found in PATH")

    try:
        url = item.getStreamURL()
    except Exception as exc:
        raise PlayerError(f"could not get stream URL: {exc}") from exc

    title = getattr(item, "title", "Plex")
    subprocess.Popen(
        ["mpv", "--force-media-title=" + title, url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
