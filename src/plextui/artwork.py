from __future__ import annotations

import base64
import hashlib
import os
import sys
import threading
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from PIL import Image, ImageOps
from rich.measure import Measurement
from rich.segment import Segment
from rich.style import Style
from rich.text import Text

from .config import AppConfig, cache_path, write_debug_log


MAX_IMAGE_BYTES = 12 * 1024 * 1024
ARTWORK_CACHE_LIMIT_BYTES = 100 * 1024 * 1024
KITTY_PAYLOAD_CHUNK_SIZE = 4096
KITTY_CELL_WIDTH_PX = 12
KITTY_CELL_HEIGHT_PX = 24
KITTY_TRANSMIT_LOCK = threading.Lock()
KITTY_PLACEHOLDER = "\U0010eeee"
KITTY_PLACEHOLDER_DIACRITICS = tuple(chr(codepoint) for codepoint in (
    0x0305, 0x030D, 0x030E, 0x0310, 0x0312, 0x033D, 0x033E, 0x033F,
    0x0346, 0x034A, 0x034B, 0x034C, 0x0350, 0x0351, 0x0352, 0x0357,
    0x035B, 0x0363, 0x0364, 0x0365, 0x0366, 0x0367, 0x0368, 0x0369,
    0x036A, 0x036B, 0x036C, 0x036D, 0x036E, 0x036F, 0x0483, 0x0484,
    0x0485, 0x0486, 0x0487, 0x0592, 0x0593, 0x0594, 0x0595, 0x0597,
))


@dataclass(frozen=True)
class KittyImage:
    commands: tuple[str, ...]
    lines: tuple[str, ...]
    image_id: int
    columns: int
    left_padding: int = 0
    right_padding: int = 0

    @property
    def plain(self) -> str:
        padding_left = " " * self.left_padding
        padding_right = " " * self.right_padding
        return "\n".join(f"{padding_left}{line}{padding_right}" for line in self.lines)

    def copy(self) -> "KittyImage":
        return self

    def padded(self, left: int, right: int) -> "KittyImage":
        return replace(
            self,
            left_padding=self.left_padding + max(0, left),
            right_padding=self.right_padding + max(0, right),
        )

    def __rich_console__(self, console: object, options: object) -> object:
        del console, options
        style = Style(color=f"#{self.image_id:06x}")
        left = " " * self.left_padding
        right = " " * self.right_padding
        for index, line in enumerate(self.lines):
            if left:
                yield Segment(left)
            yield Segment(line, style)
            if right:
                yield Segment(right)
            if index < len(self.lines) - 1:
                yield Segment.line()

    def __rich_measure__(self, console: object, options: object) -> Measurement:
        del console, options
        width = self.left_padding + self.columns + self.right_padding
        return Measurement(width, width)


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
    if resolved != "kitty":
        write_kitty_artwork_log(
            f"kitty renderer skipped requested={renderer!r} resolved={resolved!r} "
            f"env={kitty_environment_status()}"
        )
        return None
    return render_kitty_artwork(data, width=width, max_height=max_height, transmit=True)


def resolve_protocol_renderer(renderer: str) -> str:
    if renderer == "kitty":
        return "kitty"
    if renderer == "auto" and kitty_graphics_supported():
        return "kitty"
    return "block"


def protocol_renderer_status(renderer: str) -> str:
    resolved = resolve_protocol_renderer(renderer)
    if resolved == "kitty":
        return "Kitty native images via Unicode placeholders"
    if renderer == "auto":
        return "Block art; Kitty-compatible terminal not detected"
    if renderer == "kitty":
        return "Kitty native images via Unicode placeholders"
    return "Block art"


def kitty_graphics_supported() -> bool:
    return bool(os.environ.get("KITTY_WINDOW_ID") or os.environ.get("KITTY_PID") or ghostty_terminal_detected())


def ghostty_terminal_detected() -> bool:
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    term = os.environ.get("TERM", "").lower()
    return term_program == "ghostty" or term.startswith("xterm-ghostty")


def kitty_environment_status() -> str:
    fields = [
        f"KITTY_WINDOW_ID={int(bool(os.environ.get('KITTY_WINDOW_ID')))}",
        f"KITTY_PID={int(bool(os.environ.get('KITTY_PID')))}",
        f"TERM_PROGRAM={os.environ.get('TERM_PROGRAM', '')!r}",
        f"TERM_PROGRAM_VERSION={os.environ.get('TERM_PROGRAM_VERSION', '')!r}",
        f"TERM={os.environ.get('TERM', '')!r}",
        f"COLORTERM={os.environ.get('COLORTERM', '')!r}",
    ]
    return ",".join(fields)


def render_kitty_artwork(data: bytes, width: int = 28, max_height: int = 20, transmit: bool = False) -> KittyImage:
    image = load_image(data)
    columns, rows = kitty_cell_dimensions(image, width, max_height)
    image = resize_for_kitty_cells(image, columns, rows)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    payload = base64.b64encode(buffer.getvalue()).decode("ascii")
    image_id = kitty_image_id(buffer.getvalue(), columns, rows)
    commands = kitty_graphics_commands(payload, image_id=image_id, columns=columns, rows=rows)
    if transmit:
        emit_kitty_graphics_commands(commands)
    return KittyImage(
        commands=tuple(commands),
        lines=tuple(kitty_placeholder_lines(image_id, columns, rows)),
        image_id=image_id,
        columns=columns,
    )


def kitty_pixel_size(width: int, max_height: int) -> tuple[int, int]:
    return max(1, width) * KITTY_CELL_WIDTH_PX, max(1, max_height) * KITTY_CELL_HEIGHT_PX


def kitty_cell_dimensions(image: Image.Image, width: int, max_height: int) -> tuple[int, int]:
    source_width, source_height = image.size
    width = max(1, width)
    max_height = max(1, max_height)
    if not source_width or not source_height:
        return 1, 1
    rows = min(max_height, max(1, round(source_height / source_width * width)))
    return width, rows


def kitty_graphics_commands(
    payload: str,
    image_id: int | None = None,
    columns: int | None = None,
    rows: int | None = None,
) -> list[str]:
    placement = ""
    if image_id is not None:
        placement = f",i={image_id},U=1,c={max(1, columns or 1)},r={max(1, rows or 1)}"
    chunks = [
        payload[index : index + KITTY_PAYLOAD_CHUNK_SIZE]
        for index in range(0, len(payload), KITTY_PAYLOAD_CHUNK_SIZE)
    ]
    if not chunks:
        return [f"\033_Ga=T,f=100,q=2{placement};\033\\"]
    if len(chunks) == 1:
        return [f"\033_Ga=T,f=100,q=2{placement};{chunks[0]}\033\\"]

    commands = []
    for index, chunk in enumerate(chunks):
        if index == 0:
            prefix = f"a=T,f=100,q=2{placement},m=1"
        elif index == len(chunks) - 1:
            prefix = "m=0"
        else:
            prefix = "m=1"
        commands.append(f"\033_G{prefix};{chunk}\033\\")
    return commands


def emit_kitty_graphics_commands(commands: list[str]) -> None:
    payload = "".join(commands).encode("ascii")
    with KITTY_TRANSMIT_LOCK:
        emit_kitty_graphics_payload(payload)


def emit_kitty_graphics_payload(payload: bytes) -> None:
    target = "none"
    try:
        fd = os.open("/dev/tty", os.O_WRONLY | os.O_NOCTTY)
    except OSError:
        fd = None
    if fd is not None:
        try:
            write_all(fd, payload)
            target = "/dev/tty"
            return
        except OSError:
            target = "/dev/tty-failed"
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
            write_kitty_artwork_log(f"kitty transmit bytes={len(payload)} target={target}")
    try:
        stdout = getattr(sys, "__stdout__", sys.stdout)
        buffer = getattr(stdout, "buffer", None)
        if buffer is not None:
            buffer.write(payload)
            buffer.flush()
        else:
            stdout.write(payload.decode("ascii"))
            stdout.flush()
        target = "__stdout__"
    except OSError:
        target = "__stdout__-failed"
    finally:
        write_kitty_artwork_log(f"kitty transmit bytes={len(payload)} target={target}")


def write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    written = 0
    while written < len(payload):
        count = os.write(fd, view[written:])
        if count <= 0:
            raise OSError("short write to terminal")
        written += count


def kitty_image_id(data: bytes, columns: int, rows: int) -> int:
    digest = hashlib.sha256(data + f"\0{columns}x{rows}".encode("ascii")).digest()
    return int.from_bytes(digest[:3], "big") or 1


def kitty_placeholder_lines(image_id: int, columns: int, rows: int) -> list[str]:
    if columns >= len(KITTY_PLACEHOLDER_DIACRITICS) or rows >= len(KITTY_PLACEHOLDER_DIACRITICS):
        raise ValueError("Kitty placeholder dimensions exceed supported diacritics")
    high_byte = image_id >> 24
    high = KITTY_PLACEHOLDER_DIACRITICS[high_byte] if high_byte else ""
    lines = []
    for row in range(rows):
        row_mark = KITTY_PLACEHOLDER_DIACRITICS[row]
        cells = [
            f"{KITTY_PLACEHOLDER}{row_mark}{KITTY_PLACEHOLDER_DIACRITICS[column]}{high}"
            for column in range(columns)
        ]
        lines.append("".join(cells))
    return lines


def write_kitty_artwork_log(message: str) -> None:
    if os.environ.get("PLEX_TUI_ARTWORK_LOG") != "1":
        return
    write_debug_log(message)


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


def resize_for_kitty_cells(image: Image.Image, width: int, max_height: int) -> Image.Image:
    max_width_px, max_height_px = kitty_pixel_size(width, max_height)
    return ImageOps.contain(image, (max_width_px, max_height_px), Image.Resampling.LANCZOS)


def rgb(color: tuple[int, int, int]) -> str:
    return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
