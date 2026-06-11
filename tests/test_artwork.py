from __future__ import annotations

import os
from io import BytesIO

from PIL import Image

from plextui import artwork
from plextui.artwork import add_token, artwork_url, prune_artwork_cache, render_artwork, render_protocol_artwork
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


def test_render_protocol_artwork_is_disabled_even_when_enabled(monkeypatch):
    monkeypatch.setenv("PLEX_TUI_ENABLE_NATIVE_IMAGES", "1")
    image = Image.new("RGB", (2, 4), "#00ff00")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    rendered = render_protocol_artwork(buffer.getvalue(), "kitty", width=2, max_height=2)

    assert rendered is None


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
