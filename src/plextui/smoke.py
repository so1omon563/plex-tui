from __future__ import annotations

from .app import PlexTuiApp, format_offset
from .config import config_path


def main() -> None:
    app = PlexTuiApp()
    if not app.BINDINGS:
        raise SystemExit("missing key bindings")
    if format_offset(65_000) != "1:05":
        raise SystemExit("helper self-check failed")
    print(f"plex-tui smoke ok: {app.__class__.__name__}")
    print(f"config path: {config_path()}")


if __name__ == "__main__":
    main()
