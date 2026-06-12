from __future__ import annotations

import os
from io import BytesIO

from PIL import Image

from plextui import artwork
from plextui.artwork import (
    add_token,
    artwork_url,
    cached_artwork_path,
    kitty_graphics_commands,
    protocol_renderer_status,
    prune_artwork_cache,
    render_kitty_artwork,
    render_artwork,
    render_protocol_artwork,
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


def test_render_protocol_artwork_falls_back_without_explicit_native_opt_in():
    image = Image.new("RGB", (2, 4), "#00ff00")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    rendered = render_protocol_artwork(buffer.getvalue(), "kitty", width=2, max_height=2)

    assert rendered is None


def test_render_protocol_artwork_falls_back_even_when_native_opt_in_is_enabled(monkeypatch):
    monkeypatch.setenv("KITTY_WINDOW_ID", "1")
    image = Image.new("RGB", (2, 4), "#00ff00")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    rendered = render_protocol_artwork(buffer.getvalue(), "kitty", width=2, max_height=2)

    assert rendered is None
    assert protocol_renderer_status("kitty") == "Block fallback; native Kitty images are disabled inside Textual"


def test_render_kitty_artwork_builds_protocol_bytes():
    image = Image.new("RGB", (2, 4), "#00ff00")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    rendered = render_kitty_artwork(buffer.getvalue(), width=2, max_height=2)

    assert "\033_Ga=T,f=100,q=2;" in rendered.plain
    assert rendered.plain.endswith("\033\\")


def test_kitty_graphics_commands_chunks_large_payload(monkeypatch):
    monkeypatch.setattr(artwork, "KITTY_PAYLOAD_CHUNK_SIZE", 8)

    commands = kitty_graphics_commands("a" * 20)

    assert commands[0].startswith("\033_Ga=T,f=100,q=2,m=1;")
    assert commands[-1].startswith("\033_Gm=0;")


def test_auto_protocol_renderer_requires_kitty_terminal(monkeypatch):
    monkeypatch.delenv("KITTY_WINDOW_ID", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    image = Image.new("RGB", (2, 4), "#00ff00")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    rendered = render_protocol_artwork(buffer.getvalue(), "auto", width=2, max_height=2)

    assert rendered is None
    assert protocol_renderer_status("auto") == "Block fallback; native Kitty images are disabled inside Textual"


def test_protocol_renderer_status_explains_textual_fallback():
    assert protocol_renderer_status("kitty") == "Block fallback; native Kitty images are disabled inside Textual"


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
