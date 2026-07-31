from __future__ import annotations

import base64
import fcntl
import hashlib
import os
import sys
import tempfile
import threading
import time
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
# ponytail: q=2 has no acknowledgement; use response tracking if 60s is too short for delayed terminals.
KITTY_PENDING_FILE_SECONDS = 60
# ponytail: cap retained terminal IDs; retire the LRU image if one session exceeds this.
KITTY_IMAGE_RESERVATION_LIMIT = 4096
KITTY_TRANSMIT_LOCK = threading.RLock()
KITTY_SESSION_IMAGE_IDS: dict[str, int] = {}
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
    if path.startswith("http://") or path.startswith("https://"):
        return path

    if width is not None and height is not None:
        return transcode_artwork_url(path, config, width, height)

    server = getattr(raw, "_server", None)
    if server is not None and hasattr(server, "url"):
        try:
            return str(server.url(path, includeToken=True))
        except Exception:
            pass

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
    source = f"external\0{path}" if path.startswith(("http://", "https://")) else f"{config.base_url}\0{path}"
    if width is not None or height is not None:
        source = f"{source}\0{width or ''}x{height or ''}"
    key = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return cache_path() / "artwork" / f"{key}.img"


def artwork_is_cached(path: str, config: AppConfig, width: int | None = None, height: int | None = None) -> bool:
    return cached_artwork_path(path, config, width, height).exists()


def prune_artwork_cache(
    limit_bytes: int = ARTWORK_CACHE_LIMIT_BYTES,
    *,
    protected_path: Path | None = None,
) -> None:
    with KITTY_TRANSMIT_LOCK:
        files = []
        total = 0
        kitty_directory = cache_path() / "kitty"
        for directory in (cache_path() / "artwork", kitty_directory):
            if not directory.exists():
                continue
            for path in directory.iterdir():
                try:
                    if directory == kitty_directory and path.name.startswith(".id"):
                        continue
                    if not path.is_file():
                        continue
                    stat = path.stat()
                    files.append((stat.st_mtime, stat.st_size, path))
                    total += stat.st_size
                except OSError:
                    continue
        if total <= limit_bytes:
            return
        for modified, size, path in sorted(files):
            if path == protected_path:
                continue
            if path.parent == kitty_directory and time.time() - modified < KITTY_PENDING_FILE_SECONDS:
                continue
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
    return kitty_terminal_detected() or ghostty_terminal_detected()


def kitty_terminal_detected() -> bool:
    if not (os.environ.get("KITTY_WINDOW_ID") or os.environ.get("KITTY_PID")):
        return False
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    term = os.environ.get("TERM", "").lower()
    return term_program == "kitty" or term.startswith("xterm-kitty")


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
    image_data = buffer.getvalue()
    if transmit:
        with KITTY_TRANSMIT_LOCK:
            image_path, image_id = kitty_protocol_image_path(image_data, columns, rows)
            commands = kitty_graphics_file_commands(
                image_path,
                image_id=image_id,
                columns=columns,
                rows=rows,
            )
            emit_kitty_graphics_commands(commands)
    else:
        image_id = kitty_image_id(image_data, columns, rows)
        commands = kitty_graphics_commands(
            base64.b64encode(image_data).decode("ascii"),
            image_id=image_id,
            columns=columns,
            rows=rows,
        )
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


def kitty_graphics_file_commands(path: Path, image_id: int, columns: int, rows: int) -> list[str]:
    payload = base64.b64encode(str(path).encode("utf-8")).decode("ascii")
    placement = f",i={image_id},U=1,c={max(1, columns)},r={max(1, rows)}"
    return [f"\033_Ga=T,t=t,f=100,q=2{placement};{payload}\033\\"]


def reserve_kitty_image_id(directory: Path, digest: str, candidate: int, occupied: set[int]) -> int:
    lock_fd = os.open(directory / ".ids.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(lock_fd) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        markers = list(directory.glob(".id-*"))
        for marker in markers:
            try:
                if marker.read_text() == digest:
                    marker.touch()
                    return int(marker.name.removeprefix(".id-"), 16)
            except (OSError, ValueError):
                continue

        if len(markers) >= KITTY_IMAGE_RESERVATION_LIMIT:
            marker = min(markers, key=lambda path: path.stat().st_mtime)
            retired_id = int(marker.name.removeprefix(".id-"), 16)
            emit_kitty_graphics_commands([f"\033_Ga=d,d=I,i={retired_id},q=2;\033\\"])
            marker.unlink()
            occupied.discard(retired_id)
            for reserved_digest, image_id in list(KITTY_SESSION_IMAGE_IDS.items()):
                if image_id == retired_id:
                    del KITTY_SESSION_IMAGE_IDS[reserved_digest]
            markers.remove(marker)

        marker_ids = {
            int(marker.name.removeprefix(".id-"), 16)
            for marker in markers
        }
        while candidate in occupied or candidate in marker_ids:
            candidate = candidate % 0xFFFFFF + 1
        marker = directory / f".id-{candidate:06x}"
        marker_fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(marker_fd, digest.encode("ascii"))
        finally:
            os.close(marker_fd)
        return candidate


def create_kitty_transfer_path(directory: Path, image_id: int, digest: str, data: bytes) -> Path:
    fd, raw_path = tempfile.mkstemp(
        prefix=f"{image_id:06x}-",
        suffix=f"-{digest}.png",
        dir=directory,
    )
    path = Path(raw_path)
    try:
        with os.fdopen(fd, "wb") as transfer:
            transfer.write(data)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def kitty_protocol_image_path(data: bytes, columns: int, rows: int) -> tuple[Path, int]:
    digest = kitty_image_digest(data, columns, rows)
    with KITTY_TRANSMIT_LOCK:
        directory = cache_path() / "kitty"
        directory.mkdir(parents=True, exist_ok=True)
        reserved_id = KITTY_SESSION_IMAGE_IDS.get(digest)
        if reserved_id is not None:
            reserved_id = reserve_kitty_image_id(
                directory,
                digest,
                reserved_id,
                set(KITTY_SESSION_IMAGE_IDS.values()) - {reserved_id},
            )
            KITTY_SESSION_IMAGE_IDS[digest] = reserved_id
            path = create_kitty_transfer_path(directory, reserved_id, digest, data)
            prune_artwork_cache(protected_path=path)
            return path, reserved_id

        entries: dict[int, list[Path]] = {}
        for existing in directory.glob("*.png"):
            try:
                image_id = int(existing.stem.split("-", 1)[0], 16)
            except ValueError:
                continue
            entries.setdefault(image_id, []).append(existing)

        for image_id, paths in entries.items():
            matching = [path for path in paths if path.stem.endswith(f"-{digest}")]
            if len(paths) == 1 and matching:
                image_id = reserve_kitty_image_id(
                    directory,
                    digest,
                    image_id,
                    set(entries) - {image_id} | set(KITTY_SESSION_IMAGE_IDS.values()),
                )
                path = create_kitty_transfer_path(directory, image_id, digest, data)
                KITTY_SESSION_IMAGE_IDS[digest] = image_id
                prune_artwork_cache(protected_path=path)
                return path, image_id

        image_id = kitty_image_id(data, columns, rows)
        image_id = reserve_kitty_image_id(
            directory,
            digest,
            image_id,
            set(entries) | set(KITTY_SESSION_IMAGE_IDS.values()),
        )
        path = create_kitty_transfer_path(directory, image_id, digest, data)
        KITTY_SESSION_IMAGE_IDS[digest] = image_id
        prune_artwork_cache(protected_path=path)
        return path, image_id


def emit_kitty_graphics_commands(commands: list[str]) -> None:
    with KITTY_TRANSMIT_LOCK:
        for command in commands:
            emit_kitty_graphics_payload(command.encode("ascii"))


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
    return int(kitty_image_digest(data, columns, rows)[:6], 16) or 1


def kitty_image_digest(data: bytes, columns: int, rows: int) -> str:
    return hashlib.sha256(data + f"\0{columns}x{rows}".encode("ascii")).hexdigest()


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
