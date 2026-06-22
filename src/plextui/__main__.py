from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .app import detect_mpv, render_app_diagnostics
from .config import config_path, debug_log_path, load_config
from .models import LibraryItem, MediaItem
from .plex_service import PlexService, availability_urls, kind_label, progress_percent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Browse Plex from a terminal UI.")
    parser.add_argument("--version", action="version", version=f"plex-tui {__version__}")
    parser.add_argument("--config-path", action="store_true", help="print the active config file path and exit")
    parser.add_argument("--debug-log-path", action="store_true", help="print the debug log path and exit")
    parser.add_argument("--diagnostics", action="store_true", help="print app diagnostics and exit")
    parser.add_argument("--smoke", action="store_true", help="run the built-in smoke check and exit")
    subparsers = parser.add_subparsers(dest="command")

    libraries = subparsers.add_parser("libraries", help="list configured Plex libraries")
    libraries.add_argument("--json", action="store_true", help="print JSON output")

    status = subparsers.add_parser("status", help="check Plex and playback readiness")
    status.add_argument("--json", action="store_true", help="print JSON output")

    continue_watching = subparsers.add_parser("continue-watching", help="list Continue Watching items")
    continue_watching.add_argument("--limit", type=positive_int, default=10, help="maximum items to print")
    continue_watching.add_argument("--json", action="store_true", help="print JSON output")

    discover = subparsers.add_parser("discover", help="search Plex Discover and free streaming results")
    discover.add_argument("query", help="search query")
    discover.add_argument("--limit", type=positive_int, default=10, help="maximum items to print")
    discover.add_argument("--json", action="store_true", help="print JSON output")

    discover_open = subparsers.add_parser("discover-open", help="open a Plex Discover availability URL")
    discover_open.add_argument("query", help="search query")
    discover_open.add_argument("--index", type=positive_int, default=1, help="1-based result index to open")
    discover_open.add_argument("--service-index", type=positive_int, default=1, help="1-based availability index to open")
    discover_open.add_argument("--limit", type=positive_int, default=10, help="maximum results to search")

    search = subparsers.add_parser("search", help="search Plex without opening the TUI")
    search.add_argument("query", help="search query")
    search.add_argument("--library", help="library key or title to search within")
    search.add_argument("--limit", type=positive_int, default=10, help="maximum items to print")
    search.add_argument("--json", action="store_true", help="print JSON output")
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
    if args.command == "libraries":
        return command_libraries(args.json)
    if args.command == "status":
        return command_status(args.json)
    if args.command == "continue-watching":
        return command_continue_watching(args.limit, args.json)
    if args.command == "discover":
        return command_discover(args.query, args.limit, args.json)
    if args.command == "discover-open":
        return command_discover_open(args.query, args.index, args.service_index, args.limit)
    if args.command == "search":
        return command_search(args.query, args.library, args.limit, args.json)

    from .app import PlexTuiApp

    PlexTuiApp().run()
    return 0


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def command_libraries(json_output: bool = False) -> int:
    service = connect_service()
    if service is None:
        return 2
    libraries = service.libraries()
    if json_output:
        print(json.dumps([library_payload(library) for library in libraries], indent=2))
    else:
        print_libraries(libraries)
    return 0


def command_status(json_output: bool = False) -> int:
    status = status_payload()
    if json_output:
        print(json.dumps(status, indent=2))
    else:
        print_status(status)
    return 0 if status["ready"] else 2


def command_continue_watching(limit: int, json_output: bool = False) -> int:
    service = connect_service()
    if service is None:
        return 2
    page = service.continue_watching_page(0, limit)
    if json_output:
        print(json.dumps([media_payload(item) for item in page.items], indent=2))
    else:
        print_media_items(page.items)
    return 0


def command_discover(query: str, limit: int, json_output: bool = False) -> int:
    service = connect_service()
    if service is None:
        return 2
    try:
        page = service.discover_page(query, 0, limit)
    except Exception as exc:
        print(f"plex-tui: {exc}", file=sys.stderr)
        return 2
    if json_output:
        print(json.dumps([media_payload(item) for item in page.items], indent=2))
    else:
        print_media_items(page.items)
    return 0


def command_discover_open(query: str, index: int, service_index: int, limit: int) -> int:
    service = connect_service()
    if service is None:
        return 2
    try:
        page = service.discover_page(query, 0, limit)
        item = page.items[index - 1]
    except IndexError:
        print(f"plex-tui: discover result index out of range: {index}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"plex-tui: {exc}", file=sys.stderr)
        return 2
    urls = availability_urls(item.raw)
    try:
        label, url = urls[service_index - 1]
    except IndexError:
        print(f"plex-tui: availability index out of range: {service_index}", file=sys.stderr)
        return 2
    webbrowser.open(url)
    print(f"Opened: {item.title} - {label}")
    return 0


def command_search(query: str, library: str | None, limit: int, json_output: bool = False) -> int:
    service = connect_service()
    if service is None:
        return 2
    library_item = None
    if library:
        library_item = find_library(service.libraries(), library)
        if library_item is None:
            print(f"plex-tui: library not found: {library}", file=sys.stderr)
            return 2
    page = service.search_page(query, library_item, 0, limit)
    if json_output:
        print(json.dumps([media_payload(item) for item in page.items], indent=2))
    else:
        print_media_items(page.items)
    return 0


def connect_service() -> PlexService | None:
    try:
        return PlexService(load_config())
    except Exception as exc:
        print(f"plex-tui: {exc}", file=sys.stderr)
        return None


def status_payload() -> dict[str, Any]:
    path = config_path()
    config = load_config()
    mpv_path, mpv_version = detect_mpv()
    payload: dict[str, Any] = {
        "ready": False,
        "configured": bool(config.base_url and config.token),
        "connected": False,
        "server": "",
        "library_count": 0,
        "mpv_available": mpv_path != "missing",
        "mpv": {
            "path": mpv_path,
            "version": mpv_version,
        },
        "paths": {
            "config": str(path),
            "config_exists": Path(path).exists(),
            "debug_log": str(debug_log_path()),
        },
        "error": "",
    }
    if not payload["configured"]:
        payload["error"] = "missing Plex config"
        return payload
    try:
        service = PlexService(config)
        libraries = service.libraries()
    except Exception as exc:
        payload["error"] = str(exc)
        return payload
    payload["connected"] = True
    payload["server"] = service.friendly_name
    payload["library_count"] = len(libraries)
    payload["ready"] = bool(payload["mpv_available"])
    if not payload["ready"]:
        payload["error"] = "mpv was not found on PATH"
    return payload


def print_status(status: dict[str, Any]) -> None:
    rows = [
        ("Ready", yes_no(bool(status["ready"]))),
        ("Configured", yes_no(bool(status["configured"]))),
        ("Connected", yes_no(bool(status["connected"]))),
        ("Server", str(status["server"]) or "-"),
        ("Libraries", str(status["library_count"])),
        ("mpv", status["mpv"]["version"] if status["mpv_available"] else "missing"),
        ("Config", str(status["paths"]["config"])),
        ("Config exists", yes_no(bool(status["paths"]["config_exists"]))),
        ("Debug log", str(status["paths"]["debug_log"])),
    ]
    if status["error"]:
        rows.append(("Error", str(status["error"])))
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"{label.ljust(width)}  {value}")


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def find_library(libraries: list[LibraryItem], value: str) -> LibraryItem | None:
    normalized = value.casefold()
    for library in libraries:
        if library.key == value or library.title.casefold() == normalized:
            return library
    return None


def print_libraries(libraries: list[LibraryItem]) -> None:
    print_rows(
        ["KEY", "TYPE", "TITLE"],
        [(library.key, kind_label(library.kind), library.title) for library in libraries],
    )


def print_media_items(items: list[MediaItem]) -> None:
    print_rows(
        ["TYPE", "PROGRESS", "TITLE", "DETAILS"],
        [
            (
                kind_label(item.kind),
                media_progress(item),
                item.title,
                item.subtitle,
            )
            for item in items
        ],
    )


def print_rows(headers: list[str], rows: list[tuple[str, ...]]) -> None:
    if not rows:
        print("(none)")
        return
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def library_payload(library: LibraryItem) -> dict[str, str]:
    return {
        "key": library.key,
        "title": library.title,
        "kind": library.kind,
    }


def media_payload(item: MediaItem) -> dict[str, Any]:
    return {
        "key": item.key,
        "title": item.title,
        "subtitle": item.subtitle,
        "kind": item.kind,
        "playable": item.playable,
        "progress_percent": progress_percent(item.raw),
    }


def media_progress(item: MediaItem) -> str:
    percent = progress_percent(item.raw)
    return f"{percent}%" if percent else ""


if __name__ == "__main__":
    raise SystemExit(main())
