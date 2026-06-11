from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from PIL import Image, ImageOps
from rich.text import Text

from .config import AppConfig, cache_path


MAX_IMAGE_BYTES = 12 * 1024 * 1024


def fetch_artwork(raw: Any, path: str, config: AppConfig) -> bytes:
    cached = cached_artwork_path(path, config)
    if cached.exists():
        return cached.read_bytes()

    url = artwork_url(raw, path, config)
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
    return data


def artwork_url(raw: Any, path: str, config: AppConfig) -> str:
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


def add_token(url: str, token: str) -> str:
    if not token:
        return url
    parts = urlsplit(url)
    query = parts.query
    separator = "&" if query else ""
    query = f"{query}{separator}{urlencode({'X-Plex-Token': token})}"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def cached_artwork_path(path: str, config: AppConfig) -> Path:
    key = hashlib.sha256(f"{config.base_url}\0{path}".encode("utf-8")).hexdigest()
    return cache_path() / "artwork" / f"{key}.img"


def render_artwork(data: bytes, width: int = 28, max_height: int = 20) -> Text:
    image = Image.open(BytesIO(data))
    image = ImageOps.exif_transpose(image).convert("RGB")
    source_width, source_height = image.size
    if not source_width or not source_height:
        return Text()

    pixel_height = min(max_height * 2, max(2, round(source_height / source_width * width * 2)))
    image = ImageOps.contain(image, (width, pixel_height), Image.Resampling.LANCZOS)

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


def rgb(color: tuple[int, int, int]) -> str:
    return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
