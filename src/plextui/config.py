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
DEFAULT_GRID_PREFETCH_PAGES = 3
MIN_GRID_PREFETCH_PAGES = 0
MAX_GRID_PREFETCH_PAGES = 5
PLAYBACK_MODES = {"auto", "transcode"}
PLAYBACK_DISPLAYS = {"external", "terminal"}
TERMINAL_VIDEO_PROFILES = {"smooth", "balanced", "sharp"}
TRANSCODE_QUALITIES = {"original", "1080p_8", "720p_4", "480p_2"}
DEFAULT_MPV_WINDOW_SIZE = "80%"
LIBRARY_ENTER_ACTIONS = {"library", "browse_modes"}
DISCOVER_MEDIA_TYPES = {"movies_shows", "movie", "show", "all"}


@dataclass(frozen=True)
class AppConfig:
    base_url: str
    token: str
    client_identifier: str
    account_token: str = ""
    home_account_token: str = ""
    preferred_audio_language: str = ""
    preferred_subtitle_language: str = ""
    subtitle_mode: str = "auto"
    artwork_mode: str = "on"
    artwork_renderer: str = "block"
    detail_artwork_mode: str = "list_only"
    grid_density: str = "comfortable"
    media_view: str = "list"
    library_enter_action: str = "library"
    theme: str = "textual-dark"
    mpv_window_size: str = ""
    playback_mode: str = "auto"
    playback_display: str = "external"
    terminal_video_profile: str = "smooth"
    transcode_quality: str = "original"
    page_size: int = DEFAULT_PAGE_SIZE
    auto_load_threshold: int = DEFAULT_AUTO_LOAD_THRESHOLD
    grid_prefetch_pages: int = DEFAULT_GRID_PREFETCH_PAGES
    hidden_library_keys: tuple[str, ...] = ()
    library_order_keys: tuple[str, ...] = ()
    show_playlists: bool = True
    show_discover: bool = True
    show_on_plex: bool = True
    discover_media_type: str = "movies_shows"
    confirm_start_over: bool = True


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
    home_account_token = data.get("home_account_token", "")
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
    library_enter_action = data.get("library_enter_action", "library")
    if library_enter_action not in LIBRARY_ENTER_ACTIONS:
        write_debug_log(f"invalid library_enter_action {library_enter_action!r}; using 'library'")
        library_enter_action = "library"
    theme = data.get("theme", "textual-dark")
    mpv_window_size = data.get("mpv_window_size", "")
    if mpv_window_size and not valid_mpv_window_size(mpv_window_size):
        write_debug_log(f"invalid mpv_window_size {mpv_window_size!r}; using default")
        mpv_window_size = ""
    playback_mode = data.get("playback_mode", "auto")
    if playback_mode not in PLAYBACK_MODES:
        write_debug_log(f"invalid playback_mode {playback_mode!r}; using 'auto'")
        playback_mode = "auto"
    playback_display = data.get("playback_display", "external")
    if playback_display not in PLAYBACK_DISPLAYS:
        write_debug_log(f"invalid playback_display {playback_display!r}; using 'external'")
        playback_display = "external"
    terminal_video_profile = data.get("terminal_video_profile", "smooth")
    if terminal_video_profile not in TERMINAL_VIDEO_PROFILES:
        write_debug_log(f"invalid terminal_video_profile {terminal_video_profile!r}; using 'smooth'")
        terminal_video_profile = "smooth"
    transcode_quality = data.get("transcode_quality", "original")
    if transcode_quality not in TRANSCODE_QUALITIES:
        write_debug_log(f"invalid transcode_quality {transcode_quality!r}; using 'original'")
        transcode_quality = "original"
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
    grid_prefetch_pages = bounded_int(
        data.get("grid_prefetch_pages", ""),
        DEFAULT_GRID_PREFETCH_PAGES,
        MIN_GRID_PREFETCH_PAGES,
        MAX_GRID_PREFETCH_PAGES,
        "grid_prefetch_pages",
    )
    hidden_library_keys = csv_values(data.get("hidden_library_keys", ""))
    library_order_keys = csv_values(data.get("library_order_keys", ""))
    show_playlists = bool_value(data.get("show_playlists", "true"), True, "show_playlists")
    show_discover = bool_value(data.get("show_discover", "true"), True, "show_discover")
    show_on_plex = bool_value(data.get("show_on_plex", "true"), True, "show_on_plex")
    confirm_start_over = bool_value(data.get("confirm_start_over", "true"), True, "confirm_start_over")
    discover_media_type = data.get("discover_media_type", "movies_shows")
    if discover_media_type not in DISCOVER_MEDIA_TYPES:
        write_debug_log(f"invalid discover_media_type {discover_media_type!r}; using 'movies_shows'")
        discover_media_type = "movies_shows"
    return AppConfig(
        base_url=base_url.strip(),
        token=token.strip(),
        client_identifier=client_identifier.strip(),
        account_token=account_token.strip(),
        home_account_token=home_account_token.strip(),
        preferred_audio_language=preferred_audio_language.strip(),
        preferred_subtitle_language=preferred_subtitle_language.strip(),
        subtitle_mode=subtitle_mode.strip(),
        artwork_mode=artwork_mode.strip(),
        artwork_renderer=artwork_renderer.strip(),
        detail_artwork_mode=detail_artwork_mode.strip(),
        grid_density=grid_density.strip(),
        media_view=media_view.strip(),
        library_enter_action=library_enter_action.strip(),
        theme=theme.strip() or "textual-dark",
        mpv_window_size=mpv_window_size.strip(),
        playback_mode=playback_mode.strip(),
        playback_display=playback_display.strip(),
        terminal_video_profile=terminal_video_profile.strip(),
        transcode_quality=transcode_quality.strip(),
        page_size=page_size,
        auto_load_threshold=auto_load_threshold,
        grid_prefetch_pages=grid_prefetch_pages,
        hidden_library_keys=hidden_library_keys,
        library_order_keys=library_order_keys,
        show_playlists=show_playlists,
        show_discover=show_discover,
        show_on_plex=show_on_plex,
        discover_media_type=discover_media_type,
        confirm_start_over=confirm_start_over,
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
    if config.home_account_token and config.home_account_token != config.account_token:
        lines.append(f'home_account_token = "{_toml_escape(config.home_account_token)}"')
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
    if config.library_enter_action != "library":
        lines.append(f'library_enter_action = "{_toml_escape(config.library_enter_action)}"')
    if config.theme != "textual-dark":
        lines.append(f'theme = "{_toml_escape(config.theme)}"')
    if config.mpv_window_size:
        lines.append(f'mpv_window_size = "{_toml_escape(config.mpv_window_size)}"')
    if config.playback_mode != "auto":
        lines.append(f'playback_mode = "{_toml_escape(config.playback_mode)}"')
    if config.playback_display != "external":
        lines.append(f'playback_display = "{_toml_escape(config.playback_display)}"')
    if config.terminal_video_profile != "smooth":
        lines.append(f'terminal_video_profile = "{_toml_escape(config.terminal_video_profile)}"')
    if config.transcode_quality != "original":
        lines.append(f'transcode_quality = "{_toml_escape(config.transcode_quality)}"')
    if config.page_size != DEFAULT_PAGE_SIZE:
        lines.append(f"page_size = {config.page_size}")
    if config.auto_load_threshold != DEFAULT_AUTO_LOAD_THRESHOLD:
        lines.append(f"auto_load_threshold = {config.auto_load_threshold}")
    if config.grid_prefetch_pages != DEFAULT_GRID_PREFETCH_PAGES:
        lines.append(f"grid_prefetch_pages = {config.grid_prefetch_pages}")
    if config.hidden_library_keys:
        lines.append(f'hidden_library_keys = "{_toml_escape(",".join(config.hidden_library_keys))}"')
    if config.library_order_keys:
        lines.append(f'library_order_keys = "{_toml_escape(",".join(config.library_order_keys))}"')
    if not config.show_playlists:
        lines.append("show_playlists = false")
    if not config.show_discover:
        lines.append("show_discover = false")
    if not config.show_on_plex:
        lines.append("show_on_plex = false")
    if not config.confirm_start_over:
        lines.append("confirm_start_over = false")
    if config.discover_media_type != "movies_shows":
        lines.append(f'discover_media_type = "{_toml_escape(config.discover_media_type)}"')
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


def csv_values(value: str) -> tuple[str, ...]:
    values = []
    seen = set()
    for raw in value.split(","):
        item = raw.strip()
        if item and item not in seen:
            values.append(item)
            seen.add(item)
    return tuple(values)


def bool_value(value: str, default: bool, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    write_debug_log(f"invalid {name} {value!r}; using {default}")
    return default


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
