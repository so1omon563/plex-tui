from __future__ import annotations

import base64
import os
from io import BytesIO
from pathlib import Path

from PIL import Image

from plextui import artwork
from plextui.artwork import (
    KITTY_PLACEHOLDER,
    KittyImage,
    add_token,
    artwork_url,
    cached_artwork_path,
    kitty_graphics_commands,
    kitty_placeholder_lines,
    protocol_renderer_status,
    prune_artwork_cache,
    render_kitty_artwork,
    render_artwork,
    render_protocol_artwork,
    write_all,
)
from plextui.config import AppConfig


class RawServer:
    def url(self, path, includeToken=False):
        suffix = "?X-Plex-Token=server-token" if includeToken else ""
        return f"http://plex{path}{suffix}"


class RawItem:
    _server = RawServer()


def test_add_token_preserves_existing_query():
    url = add_token("http://plex/library/metadata/1/thumb?width=300", "token")

    assert url == "http://plex/library/metadata/1/thumb?width=300&X-Plex-Token=token"


def test_artwork_url_prefers_plexapi_server_url():
    config = AppConfig(base_url="http://fallback", token="fallback-token", client_identifier="client")

    assert artwork_url(RawItem(), "/library/metadata/1/thumb", config) == (
        "http://plex/library/metadata/1/thumb?X-Plex-Token=server-token"
    )


def test_artwork_url_can_request_transcoded_size():
    config = AppConfig(base_url="http://plex", token="token", client_identifier="client")

    url = artwork_url(RawItem(), "/library/metadata/1/thumb", config, width=144, height=144)

    assert url.startswith("http://plex/photo/:/transcode?")
    assert "width=144" in url
    assert "height=144" in url
    assert "url=%2Flibrary%2Fmetadata%2F1%2Fthumb" in url
    assert "X-Plex-Token=token" in url


def test_artwork_url_leaves_external_urls_alone_even_with_size():
    config = AppConfig(base_url="http://plex", token="token", client_identifier="client")
    url = "https://metadata-static.plex.tv/poster.jpg"

    assert artwork_url(RawItem(), url, config, width=144, height=144) == url
    assert cached_artwork_path(url, config, width=144, height=144) != cached_artwork_path(
        "/metadata-static/poster.jpg",
        config,
        width=144,
        height=144,
    )


def test_artwork_cache_key_includes_requested_size():
    config = AppConfig(base_url="http://plex", token="token", client_identifier="client")

    original = cached_artwork_path("/library/metadata/1/thumb", config)
    resized = cached_artwork_path("/library/metadata/1/thumb", config, width=144, height=144)

    assert original != resized


def test_render_artwork_returns_halfcell_text():
    image = Image.new("RGB", (2, 4), "#ff0000")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    rendered = render_artwork(buffer.getvalue(), width=2, max_height=2)

    assert rendered.plain == "▀▀\n▀▀"
    assert rendered.spans


def test_render_protocol_artwork_tries_kitty_when_explicitly_enabled(tmp_path, monkeypatch):
    monkeypatch.delenv("KITTY_WINDOW_ID", raising=False)
    monkeypatch.delenv("KITTY_PID", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.setattr(artwork, "cache_path", lambda: tmp_path)
    transmitted = []
    monkeypatch.setattr(artwork, "emit_kitty_graphics_commands", lambda commands: transmitted.extend(commands))
    image = Image.new("RGB", (2, 4), "#00ff00")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    rendered = render_protocol_artwork(buffer.getvalue(), "kitty", width=2, max_height=2)

    assert isinstance(rendered, KittyImage)
    assert transmitted == list(rendered.commands)


def test_render_protocol_artwork_uses_unicode_placeholders_when_kitty_is_detected(tmp_path, monkeypatch):
    monkeypatch.setenv("KITTY_WINDOW_ID", "1")
    monkeypatch.setattr(artwork, "cache_path", lambda: tmp_path)
    transmitted = []
    monkeypatch.setattr(artwork, "emit_kitty_graphics_commands", lambda commands: transmitted.extend(commands))
    image = Image.new("RGB", (2, 4), "#00ff00")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    rendered = render_protocol_artwork(buffer.getvalue(), "kitty", width=2, max_height=2)

    assert isinstance(rendered, KittyImage)
    assert rendered.commands[0].startswith("\033_Ga=T,t=f,f=100,q=2,i=")
    assert ",U=1,c=2,r=2;" in rendered.commands[0]
    assert rendered.plain.count(KITTY_PLACEHOLDER) == 4
    assert transmitted == list(rendered.commands)
    assert protocol_renderer_status("kitty") == "Kitty native images via Unicode placeholders"


def test_render_kitty_artwork_builds_virtual_placement_and_placeholder_text():
    image = Image.new("RGB", (2, 4), "#00ff00")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    rendered = render_kitty_artwork(buffer.getvalue(), width=2, max_height=2)

    assert isinstance(rendered, KittyImage)
    assert rendered.commands[0].startswith("\033_Ga=T,f=100,q=2,i=")
    assert rendered.commands[0].endswith("\033\\")
    assert rendered.plain.count(KITTY_PLACEHOLDER) == 4
    assert len(rendered.lines) == 2


def test_kitty_graphics_commands_chunks_large_payload(monkeypatch):
    monkeypatch.setattr(artwork, "KITTY_PAYLOAD_CHUNK_SIZE", 8)

    commands = kitty_graphics_commands("a" * 20, image_id=42, columns=2, rows=2)

    assert commands[0].startswith("\033_Ga=T,f=100,q=2,i=42,U=1,c=2,r=2,m=1;")
    assert commands[-1].startswith("\033_Gm=0;")


def test_kitty_graphics_emits_each_command_boundary(monkeypatch):
    payloads = []

    monkeypatch.setattr(artwork, "emit_kitty_graphics_payload", payloads.append)

    artwork.emit_kitty_graphics_commands(["first", "second"])

    assert payloads == [b"first", b"second"]


def test_auto_protocol_renderer_requires_kitty_terminal(monkeypatch):
    monkeypatch.delenv("KITTY_WINDOW_ID", raising=False)
    monkeypatch.delenv("KITTY_PID", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    image = Image.new("RGB", (2, 4), "#00ff00")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    rendered = render_protocol_artwork(buffer.getvalue(), "auto", width=2, max_height=2)

    assert rendered is None
    assert protocol_renderer_status("auto") == "Block art; Kitty-compatible terminal not detected"


def test_auto_protocol_renderer_ignores_stale_kitty_env_in_iterm(monkeypatch):
    monkeypatch.setenv("KITTY_WINDOW_ID", "1")
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    monkeypatch.setenv("TERM", "xterm-256color")
    image = Image.new("RGB", (2, 4), "#00ff00")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    rendered = render_protocol_artwork(buffer.getvalue(), "auto", width=2, max_height=2)

    assert rendered is None


def test_auto_protocol_renderer_uses_kitty_when_kitty_env_matches_terminal(tmp_path, monkeypatch):
    monkeypatch.setenv("KITTY_WINDOW_ID", "1")
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.setenv("TERM", "xterm-kitty")
    monkeypatch.setattr(artwork, "cache_path", lambda: tmp_path)
    transmitted = []
    monkeypatch.setattr(artwork, "emit_kitty_graphics_commands", lambda commands: transmitted.extend(commands))
    image = Image.new("RGB", (2, 4), "#00ff00")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    rendered = render_protocol_artwork(buffer.getvalue(), "auto", width=2, max_height=2)

    assert isinstance(rendered, KittyImage)
    assert transmitted == list(rendered.commands)


def test_auto_protocol_renderer_uses_kitty_placeholders_in_ghostty(tmp_path, monkeypatch):
    monkeypatch.delenv("KITTY_WINDOW_ID", raising=False)
    monkeypatch.delenv("KITTY_PID", raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    monkeypatch.setattr(artwork, "cache_path", lambda: tmp_path)
    transmitted = []
    monkeypatch.setattr(artwork, "emit_kitty_graphics_commands", lambda commands: transmitted.extend(commands))
    image = Image.new("RGB", (2, 4), "#00ff00")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    rendered = render_protocol_artwork(buffer.getvalue(), "auto", width=2, max_height=2)

    assert isinstance(rendered, KittyImage)
    assert transmitted == list(rendered.commands)
    assert protocol_renderer_status("auto") == "Kitty native images via Unicode placeholders"


def test_protocol_renderer_transmits_kitty_file_reference(tmp_path, monkeypatch):
    monkeypatch.delenv("KITTY_WINDOW_ID", raising=False)
    monkeypatch.delenv("KITTY_PID", raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    monkeypatch.setattr(artwork, "cache_path", lambda: tmp_path)
    transmitted = []
    monkeypatch.setattr(artwork, "emit_kitty_graphics_commands", lambda commands: transmitted.extend(commands))
    image = Image.new("RGB", (6, 8), "#00ff00")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    rendered = render_protocol_artwork(buffer.getvalue(), "auto", width=2, max_height=2)

    assert isinstance(rendered, KittyImage)
    assert transmitted == list(rendered.commands)
    command = transmitted[0]
    assert ",t=f," in command
    payload = command.split(";", 1)[1].removesuffix("\033\\")
    image_path = Path(base64.b64decode(payload).decode("utf-8"))
    assert image_path.exists()
    assert image_path.read_bytes().startswith(b"\x89PNG")
    assert base64.b64encode(image_path.read_bytes()).decode("ascii") not in command


def test_kitty_cache_resolves_short_id_collisions(tmp_path, monkeypatch):
    monkeypatch.setattr(artwork, "cache_path", lambda: tmp_path)
    monkeypatch.setattr(artwork, "kitty_image_id", lambda data, columns, rows: 7)
    monkeypatch.setattr(artwork, "emit_kitty_graphics_commands", lambda commands: None)

    buffers = []
    for color in ("#ff0000", "#0000ff"):
        buffer = BytesIO()
        Image.new("RGB", (4, 4), color).save(buffer, format="PNG")
        buffers.append(buffer.getvalue())

    first = render_kitty_artwork(buffers[0], width=2, max_height=2, transmit=True)
    second = render_kitty_artwork(buffers[1], width=2, max_height=2, transmit=True)

    paths = []
    for rendered in (first, second):
        payload = rendered.commands[0].split(";", 1)[1].removesuffix("\033\\")
        paths.append(Path(base64.b64decode(payload).decode("utf-8")))
    assert first.image_id == 7
    assert second.image_id == 8
    assert paths[0] != paths[1]
    assert paths[0].read_bytes() != paths[1].read_bytes()


def test_protocol_renderer_status_explains_explicit_kitty_force(monkeypatch):
    monkeypatch.delenv("KITTY_WINDOW_ID", raising=False)
    monkeypatch.delenv("KITTY_PID", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)

    assert protocol_renderer_status("kitty") == "Kitty native images via Unicode placeholders"


def test_kitty_placeholder_lines_encode_row_and_column_cells():
    lines = kitty_placeholder_lines(42, columns=2, rows=2)

    assert lines[0].startswith(f"{KITTY_PLACEHOLDER}\u0305\u0305")
    assert lines[0].endswith(f"{KITTY_PLACEHOLDER}\u0305\u030d")
    assert lines[1].startswith(f"{KITTY_PLACEHOLDER}\u030d\u0305")


def test_write_all_retries_short_terminal_writes(monkeypatch):
    chunks = []

    def short_write(fd, payload):
        del fd
        chunk = bytes(payload[:3])
        chunks.append(chunk)
        return len(chunk)

    monkeypatch.setattr(artwork.os, "write", short_write)

    write_all(1, b"abcdefgh")

    assert b"".join(chunks) == b"abcdefgh"


def test_prune_artwork_cache_removes_oldest_files(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    artwork_dir = cache_dir / "artwork"
    artwork_dir.mkdir(parents=True)
    old = artwork_dir / "old.img"
    new = artwork_dir / "new.img"
    old.write_bytes(b"1" * 10)
    new.write_bytes(b"2" * 10)
    os.utime(old, (1, 1))
    os.utime(new, (2, 2))
    monkeypatch.setattr(artwork, "cache_path", lambda: cache_dir)

    prune_artwork_cache(limit_bytes=10)

    assert not old.exists()
    assert new.exists()


def test_prune_artwork_cache_bounds_kitty_files_without_deleting_protected_file(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    artwork_dir = cache_dir / "artwork"
    kitty_dir = cache_dir / "kitty"
    artwork_dir.mkdir(parents=True)
    kitty_dir.mkdir()
    source = artwork_dir / "source.img"
    derived = kitty_dir / "000001-digest.png"
    source.write_bytes(b"source")
    derived.write_bytes(b"derived")
    monkeypatch.setattr(artwork, "cache_path", lambda: cache_dir)

    prune_artwork_cache(limit_bytes=0, protected_path=derived)

    assert not source.exists()
    assert derived.exists()

    prune_artwork_cache(limit_bytes=0)

    assert not derived.exists()
