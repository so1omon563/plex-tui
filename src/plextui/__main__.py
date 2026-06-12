from __future__ import annotations

import argparse
from collections.abc import Sequence

from . import __version__
from .app import detect_mpv, render_app_diagnostics
from .config import config_path, debug_log_path, load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Browse Plex from a terminal UI.")
    parser.add_argument("--version", action="version", version=f"plex-tui {__version__}")
    parser.add_argument("--config-path", action="store_true", help="print the active config file path and exit")
    parser.add_argument("--debug-log-path", action="store_true", help="print the debug log path and exit")
    parser.add_argument("--diagnostics", action="store_true", help="print app diagnostics and exit")
    parser.add_argument("--smoke", action="store_true", help="run the built-in smoke check and exit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.config_path:
        print(config_path())
        return 0
    if args.debug_log_path:
        print(debug_log_path())
        return 0
    if args.diagnostics:
        print(render_app_diagnostics(load_config(), detect_mpv()))
        return 0
    if args.smoke:
        from .smoke import main as smoke_main

        smoke_main()
        return 0

    from .app import PlexTuiApp

    PlexTuiApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
