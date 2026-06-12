from __future__ import annotations

import base64
import hashlib
import os
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from PIL import Image, ImageOps
from rich.text import Text

from .config import AppConfig, cache_path


MAX_IMAGE_BYTES = 12 * 1024 * 1024
ARTWORK_CACHE_LIMIT_BYTES = 100 * 1024 * 1024
NATIVE_IMAGE_ENV = "PLEX_TUI_ENABLE_NATIVE_IMAGES"
KITTY_PAYLOAD_CHUNK_SIZE = 4096


def fetch_artwork(raw: Any, path: str, config: AppConfig, width: int | None = None, height: int | None = None) -> bytes:
    cached = cached_artwork_path(path, config, width, height)
    if cached.exists():
        return cached.read_bytes()

    url = artwork_url(raw, path, config, width, height)
    request = Request(url, headers={"User-Agent": "plex-tui"})
    with urlopen(request, timeout=10) as response:
        status = getattr(response, "status", 200)
        if status != 200:
            raise OSError(f"artwork fetch failed: HTTP {status}")
        data = response.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise OSError("artwork image is too large")

    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    prune_artwork_cache()
    return data


def artwork_url(raw: Any, path: str, config: AppConfig, width: int | None = None, height: int | None = None) -> str:
    if width is not None and height is not None:
        return transcode_artwork_url(path, config, width, height)

    server = getattr(raw, "_server", None)
    if server is not None and hasattr(server, "url"):
        try:
            return str(server.url(path, includeToken=True))
        except Exception:
            pass

    if path.startswith("http://") or path.startswith("https://"):
        url = path
    else:
        url = f"{config.base_url.rstrip('/')}/{path.lstrip('/')}"
    return add_token(url, config.token)


def transcode_artwork_url(path: str, config: AppConfig, width: int, height: int) -> str:
    base_url = config.base_url.rstrip("/")
    query = urlencode({
        "width": max(1, width),
        "height": max(1, height),
        "minSize": 1,
        "upscale": 1,
        "url": path,
    })
    return add_token(f"{base_url}/photo/:/transcode?{query}", config.token)


def add_token(url: str, token: str) -> str:
    if not token:
        return url
    parts = urlsplit(url)
    query = parts.query
    separator = "&" if query else ""
    query = f"{query}{separator}{urlencode({'X-Plex-Token': token})}"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def cached_artwork_path(path: str, config: AppConfig, width: int | None = None, height: int | None = None) -> Path:
    source = f"{config.base_url}\0{path}"
    if width is not None or height is not None:
        source = f"{source}\0{width or ''}x{height or ''}"
    key = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return cache_path() / "artwork" / f"{key}.img"


def artwork_is_cached(path: str, config: AppConfig, width: int | None = None, height: int | None = None) -> bool:
    return cached_artwork_path(path, config, width, height).exists()


def prune_artwork_cache(limit_bytes: int = ARTWORK_CACHE_LIMIT_BYTES) -> None:
    directory = cache_path() / "artwork"
    if not directory.exists():
        return
    files = []
    total = 0
    try:
        for path in directory.iterdir():
            if not path.is_file():
                continue
            stat = path.stat()
            files.append((stat.st_mtime, stat.st_size, path))
            total += stat.st_size
    except OSError:
        return
    if total <= limit_bytes:
        return
    for _, size, path in sorted(files):
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        if total <= limit_bytes:
            break


def render_artwork(data: bytes, width: int = 28, max_height: int = 20) -> Text:
    image = load_image(data)
    image = resize_for_cells(image, width, max_height)

    text = Text()
    pixels = image.load()
    for y in range(0, image.height, 2):
        for x in range(image.width):
            top = pixels[x, y]
            bottom = pixels[x, y + 1] if y + 1 < image.height else top
            text.append("▀", style=f"{rgb(top)} on {rgb(bottom)}")
        if y + 2 < image.height:
            text.append("\n")
    return text


def render_protocol_artwork(data: bytes, renderer: str, width: int = 28, max_height: int = 20) -> object | None:
    resolved = resolve_protocol_renderer(renderer)
    if resolved == "kitty":
        return render_kitty_artwork(data, width=width, max_height=max_height)
    return None


def resolve_protocol_renderer(renderer: str) -> str:
    if not native_images_enabled():
        return "block"
    if renderer == "kitty":
        return "kitty"
    if renderer == "auto" and is_kitty_terminal():
        return "kitty"
    return "block"


def protocol_renderer_status(renderer: str) -> str:
    resolved = resolve_protocol_renderer(renderer)
    if resolved == "kitty":
        return "Kitty native images"
    if not native_images_enabled() and renderer in {"auto", "kitty"}:
        return "Block fallback; set PLEX_TUI_ENABLE_NATIVE_IMAGES=1 to enable native images"
    if renderer == "auto":
        return "Block fallback; Kitty terminal not detected"
    if renderer == "kitty":
        return "Block fallback; Kitty terminal not detected"
    return "Block art"


def render_kitty_artwork(data: bytes, width: int = 28, max_height: int = 20) -> Text:
    image = load_image(data)
    image = resize_for_cells(image, width, max_height)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    payload = base64.b64encode(buffer.getvalue()).decode("ascii")
    return Text("".join(kitty_graphics_commands(payload)))


def kitty_graphics_commands(payload: str) -> list[str]:
    chunks = [
        payload[index : index + KITTY_PAYLOAD_CHUNK_SIZE]
        for index in range(0, len(payload), KITTY_PAYLOAD_CHUNK_SIZE)
    ]
    if not chunks:
        return ["\033_Ga=T,f=100,q=2;\033\\"]
    if len(chunks) == 1:
        return [f"\033_Ga=T,f=100,q=2;{chunks[0]}\033\\"]

    commands = []
    for index, chunk in enumerate(chunks):
        if index == 0:
            prefix = "a=T,f=100,q=2,m=1"
        elif index == len(chunks) - 1:
            prefix = "m=0"
        else:
            prefix = "m=1"
        commands.append(f"\033_G{prefix};{chunk}\033\\")
    return commands


def native_images_enabled() -> bool:
    return os.environ.get(NATIVE_IMAGE_ENV) == "1"


def is_kitty_terminal() -> bool:
    return bool(os.environ.get("KITTY_WINDOW_ID") or "kitty" in os.environ.get("TERM", "").lower())


def load_image(data: bytes) -> Image.Image:
    return ImageOps.exif_transpose(Image.open(BytesIO(data))).convert("RGB")


def resize_for_cells(image: Image.Image, width: int, max_height: int) -> Image.Image:
    source_width, source_height = image.size
    if not source_width or not source_height:
        return Image.new("RGB", (1, 2), "#000000")

    width = max(1, width)
    max_height = max(1, max_height)
    pixel_height = min(max_height * 2, max(2, round(source_height / source_width * width * 2)))
    return ImageOps.contain(image, (width, pixel_height), Image.Resampling.LANCZOS)


def rgb(color: tuple[int, int, int]) -> str:
    return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
