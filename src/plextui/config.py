from __future__ import annotations

import os
import re
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir


APP_NAME = "plex-tui"
DEFAULT_PAGE_SIZE = 40
MIN_PAGE_SIZE = 25
MAX_PAGE_SIZE = 500
DEFAULT_AUTO_LOAD_THRESHOLD = 10
MIN_AUTO_LOAD_THRESHOLD = 1
MAX_AUTO_LOAD_THRESHOLD = 100


@dataclass(frozen=True)
class AppConfig:
    base_url: str
    token: str
    client_identifier: str
    account_token: str = ""
    preferred_audio_language: str = ""
    preferred_subtitle_language: str = ""
    subtitle_mode: str = "auto"
    artwork_mode: str = "on"
    artwork_renderer: str = "block"
    detail_artwork_mode: str = "list_only"
    grid_density: str = "comfortable"
    media_view: str = "list"
    theme: str = "textual-dark"
    mpv_window_size: str = ""
    page_size: int = DEFAULT_PAGE_SIZE
    auto_load_threshold: int = DEFAULT_AUTO_LOAD_THRESHOLD


def config_path() -> Path:
    return Path(user_config_dir(APP_NAME)) / "config.toml"


def cache_path() -> Path:
    return Path(user_cache_dir(APP_NAME))


def debug_log_path() -> Path:
    return Path(user_config_dir(APP_NAME)) / "debug.log"


def load_config() -> AppConfig:
    data: dict[str, str] = {}
    path = config_path()
    if path.exists():
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
        data = {k: str(v) for k, v in raw.items() if isinstance(v, str | int)}

    base_url = os.environ.get("PLEX_TUI_BASE_URL") or data.get("base_url", "")
    token = os.environ.get("PLEX_TUI_TOKEN") or data.get("token", "")
    client_identifier = data.get("client_identifier") or f"plex-tui-{uuid.uuid4()}"
    account_token = data.get("account_token", "")
    preferred_audio_language = data.get("preferred_audio_language", "")
    preferred_subtitle_language = data.get("preferred_subtitle_language", "")
    subtitle_mode = data.get("subtitle_mode", "auto")
    if subtitle_mode not in {"auto", "none", "preferred"}:
        write_debug_log(f"invalid subtitle_mode {subtitle_mode!r}; using 'auto'")
        subtitle_mode = "auto"
    artwork_mode = data.get("artwork_mode", "on")
    if artwork_mode not in {"on", "off"}:
        write_debug_log(f"invalid artwork_mode {artwork_mode!r}; using 'on'")
        artwork_mode = "on"
    artwork_renderer = data.get("artwork_renderer", "block")
    if artwork_renderer not in {"block", "auto", "kitty"}:
        write_debug_log(f"invalid artwork_renderer {artwork_renderer!r}; using 'block'")
        artwork_renderer = "block"
    detail_artwork_mode = data.get("detail_artwork_mode", "list_only")
    if detail_artwork_mode not in {"list_only", "on", "off"}:
        write_debug_log(f"invalid detail_artwork_mode {detail_artwork_mode!r}; using 'list_only'")
        detail_artwork_mode = "list_only"
    grid_density = data.get("grid_density", "comfortable")
    if grid_density not in {"compact", "comfortable", "large"}:
        write_debug_log(f"invalid grid_density {grid_density!r}; using 'comfortable'")
        grid_density = "comfortable"
    media_view = data.get("media_view", "list")
    if media_view == "poster":
        write_debug_log("media_view 'poster' is deprecated; using 'list'")
        media_view = "list"
    if media_view not in {"list", "grid"}:
        write_debug_log(f"invalid media_view {media_view!r}; using 'list'")
        media_view = "list"
    theme = data.get("theme", "textual-dark")
    mpv_window_size = data.get("mpv_window_size", "")
    if mpv_window_size and not valid_mpv_window_size(mpv_window_size):
        write_debug_log(f"invalid mpv_window_size {mpv_window_size!r}; using default")
        mpv_window_size = ""
    page_size = bounded_int(
        data.get("page_size", ""),
        DEFAULT_PAGE_SIZE,
        MIN_PAGE_SIZE,
        MAX_PAGE_SIZE,
        "page_size",
    )
    auto_load_threshold = bounded_int(
        data.get("auto_load_threshold", ""),
        DEFAULT_AUTO_LOAD_THRESHOLD,
        MIN_AUTO_LOAD_THRESHOLD,
        MAX_AUTO_LOAD_THRESHOLD,
        "auto_load_threshold",
    )
    return AppConfig(
        base_url=base_url.strip(),
        token=token.strip(),
        client_identifier=client_identifier.strip(),
        account_token=account_token.strip(),
        preferred_audio_language=preferred_audio_language.strip(),
        preferred_subtitle_language=preferred_subtitle_language.strip(),
        subtitle_mode=subtitle_mode.strip(),
        artwork_mode=artwork_mode.strip(),
        artwork_renderer=artwork_renderer.strip(),
        detail_artwork_mode=detail_artwork_mode.strip(),
        grid_density=grid_density.strip(),
        media_view=media_view.strip(),
        theme=theme.strip() or "textual-dark",
        mpv_window_size=mpv_window_size.strip(),
        page_size=page_size,
        auto_load_threshold=auto_load_threshold,
    )


def save_config(config: AppConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f'base_url = "{_toml_escape(config.base_url)}"',
        f'token = "{_toml_escape(config.token)}"',
        f'client_identifier = "{_toml_escape(config.client_identifier)}"',
    ]
    if config.account_token:
        lines.append(f'account_token = "{_toml_escape(config.account_token)}"')
    if config.preferred_audio_language:
        lines.append(f'preferred_audio_language = "{_toml_escape(config.preferred_audio_language)}"')
    if config.preferred_subtitle_language:
        lines.append(f'preferred_subtitle_language = "{_toml_escape(config.preferred_subtitle_language)}"')
    if config.subtitle_mode != "auto":
        lines.append(f'subtitle_mode = "{_toml_escape(config.subtitle_mode)}"')
    if config.artwork_mode != "on":
        lines.append(f'artwork_mode = "{_toml_escape(config.artwork_mode)}"')
    if config.artwork_renderer != "block":
        lines.append(f'artwork_renderer = "{_toml_escape(config.artwork_renderer)}"')
    if config.detail_artwork_mode != "list_only":
        lines.append(f'detail_artwork_mode = "{_toml_escape(config.detail_artwork_mode)}"')
    if config.grid_density != "comfortable":
        lines.append(f'grid_density = "{_toml_escape(config.grid_density)}"')
    if config.media_view != "list":
        lines.append(f'media_view = "{_toml_escape(config.media_view)}"')
    if config.theme != "textual-dark":
        lines.append(f'theme = "{_toml_escape(config.theme)}"')
    if config.mpv_window_size:
        lines.append(f'mpv_window_size = "{_toml_escape(config.mpv_window_size)}"')
    if config.page_size != DEFAULT_PAGE_SIZE:
        lines.append(f"page_size = {config.page_size}")
    if config.auto_load_threshold != DEFAULT_AUTO_LOAD_THRESHOLD:
        lines.append(f"auto_load_threshold = {config.auto_load_threshold}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def valid_mpv_window_size(value: str) -> bool:
    return bool(re.fullmatch(r"(?:\d{2,5}x\d{2,5}|\d{1,3}%x\d{1,3}%|\d{1,3}%)", value.strip()))


def bounded_int(value: str, default: int, minimum: int, maximum: int, name: str) -> int:
    if value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        write_debug_log(f"invalid {name} {value!r}; using {default}")
        return default
    if parsed < minimum or parsed > maximum:
        write_debug_log(f"invalid {name} {value!r}; using {default}")
        return default
    return parsed


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def write_debug_log(message: str) -> None:
    try:
        path = debug_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{message}\n")
    except OSError:
        return
