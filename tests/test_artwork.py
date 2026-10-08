from __future__ import annotations

import base64
import os
import subprocess
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from plextui import artwork
from plextui.artwork import (
    KITTY_PLACEHOLDER,
    KittyImage,
    add_token,
    artwork_url,
    cached_artwork_path,
    fetch_artwork,
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


@pytest.fixture(autouse=True)
def isolated_terminal_environment(monkeypatch):
    for name in ("TMUX", "TMUX_PANE", "HERDR_PANE_ID", "TERM", "TERM_PROGRAM", "KITTY_WINDOW_ID", "KITTY_PID"):
        monkeypatch.delenv(name, raising=False)
    artwork.tmux_passthrough_enabled.cache_clear()
    yield
    artwork.tmux_passthrough_enabled.cache_clear()


@pytest.mark.parametrize("multiplexer", ["tmux", "herdr"])
@pytest.mark.parametrize("renderer", ["auto", "block"])
def test_muxer_auto_and_block_ignore_inherited_outer_terminal(monkeypatch, multiplexer, renderer):
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    monkeypatch.setenv("TERM", "xterm-kitty")
    monkeypatch.setenv("KITTY_WINDOW_ID", "1")
    monkeypatch.setenv("TMUX" if multiplexer == "tmux" else "HERDR_PANE_ID", "probe")
    monkeypatch.setattr(artwork, "emit_kitty_graphics_payload", lambda _: pytest.fail("must not transmit"))

    assert artwork.resolve_protocol_renderer(renderer) == "block"
    assert render_protocol_artwork(b"not decoded for block fallback", renderer) is None


@pytest.mark.parametrize("value, enabled", [("on\n", True), ("all\n", True), ("off\n", False), ("", False)])
def test_tmux_passthrough_queries_only_current_pane_and_caches_result(monkeypatch, value, enabled):
    calls = []
    def query(command, **kwargs):
        calls.append((command, kwargs))
        return value
    monkeypatch.setattr(artwork.subprocess, "check_output", query)

    for _ in range(2):
        assert artwork.tmux_passthrough_enabled("/tmp/probe,comma.sock,12,0", "%3") is enabled
    assert len(calls) == 1
    assert calls[0][0] == ["tmux", "-S", "/tmp/probe,comma.sock", "show-options", "-p", "-v", "-t", "%3", "allow-passthrough"]
    assert calls[0][1]["timeout"] == 0.5


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.CalledProcessError(1, "tmux"), subprocess.TimeoutExpired("tmux", 0.5)])
def test_explicit_kitty_falls_back_when_tmux_query_fails(monkeypatch, error):
    monkeypatch.setenv("TMUX", "/tmp/probe.sock,12,0")
    monkeypatch.setenv("TMUX_PANE", "%3")
    def query(*args, **kwargs):
        raise error
    monkeypatch.setattr(artwork.subprocess, "check_output", query)
    monkeypatch.setattr(artwork, "emit_kitty_graphics_payload", lambda _: pytest.fail("must not transmit"))

    assert render_protocol_artwork(b"not decoded for block fallback", "kitty") is None
    assert "tmux passthrough unavailable" in protocol_renderer_status("kitty")


@pytest.mark.parametrize("environment", [{"TERM_PROGRAM": "tmux"}, {"TERM": "tmux-256color"}, {"TMUX": "/tmp/probe.sock,12,0"}])
def test_tmux_without_current_server_and_pane_does_not_query_default_server(monkeypatch, environment):
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(artwork.subprocess, "check_output", lambda *a, **kw: pytest.fail("no target pane"))

    assert artwork.resolve_protocol_renderer("kitty") == "block"


@pytest.mark.parametrize("enabled", [False, True])
def test_explicit_kitty_in_tmux_respects_passthrough(tmp_path, monkeypatch, enabled):
    monkeypatch.setenv("TMUX", "/tmp/probe.sock,12,0")
    monkeypatch.setenv("TMUX_PANE", "%3")
    monkeypatch.setattr(artwork.subprocess, "check_output", lambda *a, **kw: "on" if enabled else "off")
    monkeypatch.setattr(artwork, "cache_path", lambda: tmp_path)
    payloads = []
    monkeypatch.setattr(artwork, "emit_kitty_graphics_payload", payloads.append)
    buffer = BytesIO()
    Image.new("RGB", (2, 4), "red").save(buffer, format="PNG")

    rendered = render_protocol_artwork(buffer.getvalue(), "kitty", width=2, max_height=2)

    if enabled:
        assert isinstance(rendered, KittyImage)
        assert len(payloads) == 1
        assert payloads[0] == b"\x1bPtmux;" + rendered.commands[0].encode().replace(b"\x1b", b"\x1b\x1b") + b"\x1b\\"
        assert ",t=f," in rendered.commands[0]
        assert ",U=1," in rendered.commands[0]
        assert "tmux passthrough" in protocol_renderer_status("kitty")
    else:
        assert rendered is None
        assert payloads == []
        assert "restart plex-tui" in protocol_renderer_status("kitty")


def test_tmux_wraps_each_chunk_and_deletion_command(monkeypatch):
    monkeypatch.setenv("TMUX", "/tmp/probe.sock,12,0")
    monkeypatch.setattr(artwork, "KITTY_PAYLOAD_CHUNK_SIZE", 8)
    payloads = []
    monkeypatch.setattr(artwork, "emit_kitty_graphics_payload", payloads.append)
    commands = kitty_graphics_commands("a" * 20, image_id=42, columns=2, rows=2)
    commands.append("\x1b_Ga=d,d=I,i=42,q=2\x1b\\")

    artwork.emit_kitty_graphics_commands(commands)

    assert len(payloads) == 4
    for payload, command in zip(payloads, commands):
        assert payload.startswith(b"\x1bPtmux;") and payload.endswith(b"\x1b\\")
        assert payload[7:-2].replace(b"\x1b\x1b", b"\x1b") == command.encode()


def test_herdr_keeps_explicit_native_commands_and_conservative_auto(tmp_path, monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "herdr")
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(artwork, "cache_path", lambda: tmp_path)
    payloads = []
    monkeypatch.setattr(artwork, "emit_kitty_graphics_payload", payloads.append)
    buffer = BytesIO()
    Image.new("RGB", (2, 4), "red").save(buffer, format="PNG")

    rendered = render_protocol_artwork(buffer.getvalue(), "kitty", width=2, max_height=2)

    assert isinstance(rendered, KittyImage)
    assert payloads == [command.encode() for command in rendered.commands]
    assert artwork.resolve_protocol_renderer("auto") == "block"
    assert "Herdr graphics enabled" in protocol_renderer_status("auto")
    assert "via Herdr" in protocol_renderer_status("kitty")


class RawServer:
    def url(self, path, includeToken=False):
        suffix = "?X-Plex-Token=server-token" if includeToken else ""
        return f"http://plex{path}{suffix}"


class RawItem:
    _server = RawServer()


class ArtworkResponse:
    status = 200

    def __init__(self, data: bytes) -> None:
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, size: int) -> bytes:
        return self.data[:size]


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


def test_invalid_artwork_response_is_not_cached_and_valid_retry_succeeds(tmp_path, monkeypatch):
    config = AppConfig(base_url="http://plex", token="token", client_identifier="client")
    buffer = BytesIO()
    Image.new("RGB", (2, 2), "#ff0000").save(buffer, format="PNG")
    valid = buffer.getvalue()
    responses = iter((b"not-an-image", valid))
    calls = []
    monkeypatch.setattr(artwork, "cache_path", lambda: tmp_path)
    monkeypatch.setattr(
        artwork,
        "urlopen",
        lambda request, timeout: calls.append((request.full_url, timeout)) or ArtworkResponse(next(responses)),
    )
    cached = cached_artwork_path("/library/metadata/1/thumb", config)

    with pytest.raises(OSError, match="not a valid image"):
        fetch_artwork(RawItem(), "/library/metadata/1/thumb", config)

    assert not cached.exists()
    assert fetch_artwork(RawItem(), "/library/metadata/1/thumb", config) == valid
    assert cached.read_bytes() == valid
    assert len(calls) == 2


def test_invalid_existing_artwork_cache_is_evicted_before_retry(tmp_path, monkeypatch):
    config = AppConfig(base_url="http://plex", token="token", client_identifier="client")
    buffer = BytesIO()
    Image.new("RGB", (2, 2), "#00ff00").save(buffer, format="PNG")
    valid = buffer.getvalue()
    monkeypatch.setattr(artwork, "cache_path", lambda: tmp_path)
    monkeypatch.setattr(artwork, "urlopen", lambda request, timeout: ArtworkResponse(valid))
    cached = cached_artwork_path("/library/metadata/1/thumb", config)
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"poisoned")

    assert fetch_artwork(RawItem(), "/library/metadata/1/thumb", config) == valid
    assert cached.read_bytes() == valid


def test_invalid_cache_eviction_and_publication_share_entry_lock(tmp_path, monkeypatch):
    config = AppConfig(base_url="http://plex", token="token", client_identifier="client")
    buffer = BytesIO()
    Image.new("RGB", (2, 2), "#00ffff").save(buffer, format="PNG")
    valid = buffer.getvalue()
    events = []
    lock_depth = 0
    validate = artwork.validate_artwork_data
    unlink = Path.unlink

    @contextmanager
    def entry_lock(path):
        nonlocal lock_depth
        assert path == cached
        assert lock_depth == 0
        lock_depth = 1
        events.append("lock")
        try:
            yield
        finally:
            events.append("unlock")
            lock_depth = 0

    def capture_validate(data):
        events.append(f"validate:{lock_depth}:{data == valid}")
        validate(data)

    def capture_unlink(path, *args, **kwargs):
        events.append(f"unlink:{lock_depth}")
        return unlink(path, *args, **kwargs)

    def fetch_response(request, timeout):
        events.append(f"fetch:{lock_depth}")
        return ArtworkResponse(valid)

    monkeypatch.setattr(artwork, "cache_path", lambda: tmp_path)
    cached = cached_artwork_path("/library/metadata/1/thumb", config)
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"poisoned")
    monkeypatch.setattr(artwork, "artwork_cache_entry_lock", entry_lock)
    monkeypatch.setattr(artwork, "validate_artwork_data", capture_validate)
    monkeypatch.setattr(Path, "unlink", capture_unlink)
    monkeypatch.setattr(artwork, "urlopen", fetch_response)

    assert fetch_artwork(RawItem(), "/library/metadata/1/thumb", config) == valid
    assert events == [
        "lock",
        "validate:1:False",
        "unlink:1",
        "unlock",
        "fetch:0",
        "validate:0:True",
        "lock",
        "unlock",
    ]


def test_artwork_cache_process_locks_are_scoped_to_cache_key(tmp_path):
    first_path = tmp_path / "artwork" / "first"
    second_path = tmp_path / "artwork" / "second"

    first = artwork.artwork_cache_process_lock(first_path)
    same = artwork.artwork_cache_process_lock(first_path)
    second = artwork.artwork_cache_process_lock(second_path)

    assert same is first
    assert second is not first


def test_valid_artwork_is_atomically_replaced_into_cache(tmp_path, monkeypatch):
    config = AppConfig(base_url="http://plex", token="token", client_identifier="client")
    buffer = BytesIO()
    Image.new("RGB", (2, 2), "#0000ff").save(buffer, format="PNG")
    valid = buffer.getvalue()
    replacements = []
    replace = os.replace
    monkeypatch.setattr(artwork, "cache_path", lambda: tmp_path)
    monkeypatch.setattr(artwork, "urlopen", lambda request, timeout: ArtworkResponse(valid))

    def capture_replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        replace(source, destination)

    monkeypatch.setattr(artwork.os, "replace", capture_replace)

    assert fetch_artwork(RawItem(), "/library/metadata/1/thumb", config) == valid
    cached = cached_artwork_path("/library/metadata/1/thumb", config)
    assert len(replacements) == 1
    temporary, destination = replacements[0]
    assert temporary.parent == tmp_path
    assert destination == cached
    assert not temporary.exists()
    assert cached.read_bytes() == valid


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
    monkeypatch.setattr(artwork, "KITTY_SESSION_IMAGE_IDS", {})
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


def test_kitty_cache_does_not_reuse_pruned_session_image_id(tmp_path, monkeypatch):
    monkeypatch.setattr(artwork, "cache_path", lambda: tmp_path)
    monkeypatch.setattr(artwork, "kitty_image_id", lambda data, columns, rows: 7)
    monkeypatch.setattr(artwork, "KITTY_SESSION_IMAGE_IDS", {})
    monkeypatch.setattr(artwork, "emit_kitty_graphics_commands", lambda commands: None)

    buffers = []
    for color in ("#ff0000", "#0000ff"):
        buffer = BytesIO()
        Image.new("RGB", (4, 4), color).save(buffer, format="PNG")
        buffers.append(buffer.getvalue())

    first = render_kitty_artwork(buffers[0], width=2, max_height=2, transmit=True)
    payload = first.commands[0].split(";", 1)[1].removesuffix("\033\\")
    Path(base64.b64decode(payload).decode("utf-8")).unlink()
    artwork.KITTY_SESSION_IMAGE_IDS.clear()
    second = render_kitty_artwork(buffers[1], width=2, max_height=2, transmit=True)
    artwork.KITTY_SESSION_IMAGE_IDS.clear()
    restored = render_kitty_artwork(buffers[0], width=2, max_height=2, transmit=True)

    assert first.image_id == 7
    assert second.image_id == 8
    assert restored.image_id == first.image_id


def test_kitty_cache_recreates_transfer_removed_before_read(tmp_path, monkeypatch):
    monkeypatch.setattr(artwork, "cache_path", lambda: tmp_path)
    monkeypatch.setattr(artwork, "KITTY_SESSION_IMAGE_IDS", {})
    data = b"image"
    first, first_id = artwork.kitty_protocol_image_path(data, 2, 2)
    first.unlink()
    restored, restored_id = artwork.kitty_protocol_image_path(data, 2, 2)

    assert restored_id == first_id
    assert restored != first
    assert restored.read_bytes() == data


def test_kitty_cache_uses_unique_paths_for_queued_transfers(tmp_path, monkeypatch):
    monkeypatch.setattr(artwork, "cache_path", lambda: tmp_path)
    monkeypatch.setattr(artwork, "KITTY_SESSION_IMAGE_IDS", {})
    data = b"image"
    first, first_id = artwork.kitty_protocol_image_path(data, 2, 2)
    second, second_id = artwork.kitty_protocol_image_path(data, 2, 2)

    assert second_id == first_id
    assert second != first
    assert first.read_bytes() == data
    assert second.read_bytes() == data


def test_kitty_id_reservations_retire_oldest_at_limit(tmp_path, monkeypatch):
    directory = tmp_path / "kitty"
    directory.mkdir()
    deleted = []
    monkeypatch.setattr(artwork, "KITTY_IMAGE_RESERVATION_LIMIT", 2)
    monkeypatch.setattr(artwork, "KITTY_SESSION_IMAGE_IDS", {})
    monkeypatch.setattr(artwork, "emit_kitty_graphics_commands", deleted.extend)
    artwork.reserve_kitty_image_id(directory, "first", 1, set())
    artwork.reserve_kitty_image_id(directory, "second", 2, set())
    os.utime(directory / ".id-000001", (1, 1))
    os.utime(directory / ".id-000002", (2, 2))

    reserved = artwork.reserve_kitty_image_id(directory, "third", 3, set())

    assert reserved == 3
    assert deleted == ["\033_Ga=d,d=I,i=1,q=2;\033\\"]
    assert sorted(path.name for path in directory.glob(".id-*")) == [
        ".id-000002",
        ".id-000003",
    ]


def test_kitty_transmit_holds_cross_process_lock_through_emit(tmp_path, monkeypatch):
    events = []

    @contextmanager
    def transaction(directory):
        assert directory == tmp_path / "kitty"
        events.append("lock")
        try:
            yield
        finally:
            events.append("unlock")

    def reserve(data, columns, rows):
        events.append("reserve")
        (tmp_path / "kitty" / ".id-000007").write_text("reserved")
        return tmp_path / "transfer.png", 7

    monkeypatch.setattr(artwork, "cache_path", lambda: tmp_path)
    monkeypatch.setattr(artwork, "kitty_terminal_transaction", transaction)
    monkeypatch.setattr(artwork, "kitty_protocol_image_path", reserve)
    monkeypatch.setattr(artwork, "emit_kitty_graphics_commands", lambda commands: events.append("emit"))
    buffer = BytesIO()
    Image.new("RGB", (4, 4), "#00ff00").save(buffer, format="PNG")

    render_kitty_artwork(buffer.getvalue(), width=2, max_height=2, transmit=True)

    assert events == ["lock", "reserve", "emit", "unlock"]


@pytest.mark.parametrize("restored_color", ["blue", "red"])
def test_cached_kitty_image_expires_when_id_is_reused(tmp_path, monkeypatch, restored_color):
    monkeypatch.setattr(artwork, "cache_path", lambda: tmp_path)
    monkeypatch.setattr(artwork, "KITTY_SESSION_IMAGE_IDS", {})
    monkeypatch.setattr(artwork, "KITTY_IMAGE_RESERVATION_LIMIT", 1)
    monkeypatch.setattr(artwork, "kitty_image_id", lambda *args: 7)
    commands = []
    monkeypatch.setattr(artwork, "emit_kitty_graphics_commands", commands.extend)

    def render(color):
        buffer = BytesIO()
        Image.new("RGB", (4, 4), color).save(buffer, format="PNG")
        return render_kitty_artwork(buffer.getvalue(), width=2, max_height=2, transmit=True)

    first = render("red")
    assert artwork.cached_artwork_is_current(first)
    render("green")
    # Another process may restore the original digest, but our terminal lost it.
    artwork.KITTY_SESSION_IMAGE_IDS.clear()
    restored = render(restored_color)

    assert first.image_id == restored.image_id == 7
    assert not artwork.cached_artwork_is_current(first.padded(1, 1))
    assert artwork.cached_artwork_is_current(restored)
    assert len(list((tmp_path / "kitty").glob(".id-*"))) == 1
    assert sum("a=T,t=f," in command for command in commands) == 3


def test_cached_kitty_reuse_keeps_recent_image_at_reservation_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(artwork, "KITTY_IMAGE_RESERVATION_LIMIT", 2)
    monkeypatch.setattr(artwork, "emit_kitty_graphics_commands", lambda commands: None)
    artwork.reserve_kitty_image_id(tmp_path, "first", 1, set())
    artwork.reserve_kitty_image_id(tmp_path, "second", 2, set())
    first_marker = tmp_path / ".id-000001"
    image = KittyImage((), (), 1, 1, reservation_path=first_marker, reservation=first_marker.read_text())
    os.utime(first_marker, (1, 1))
    os.utime(tmp_path / ".id-000002", (2, 2))

    assert artwork.cached_artwork_is_current(image)
    artwork.reserve_kitty_image_id(tmp_path, "third", 3, set())

    assert first_marker.exists()
    assert not (tmp_path / ".id-000002").exists()
    first_marker.unlink()
    assert not artwork.cached_artwork_is_current(image)


def test_kitty_reservation_accepts_existing_digest_only_markers(tmp_path):
    marker = tmp_path / ".id-000007"
    marker.write_text("existing-digest")
    assert artwork.reserve_kitty_image_id(tmp_path, "existing-digest", 8, set()) == 7


def test_kitty_id_retirement_at_production_limit(tmp_path, monkeypatch):
    deleted = []
    monkeypatch.setattr(artwork, "emit_kitty_graphics_commands", deleted.extend)
    monkeypatch.setattr(artwork, "KITTY_SESSION_IMAGE_IDS", {})
    assert artwork.KITTY_IMAGE_RESERVATION_LIMIT == 4096
    for image_id in range(1, 4097):
        (tmp_path / f".id-{image_id:06x}").write_text(f"{image_id:064x}")
    os.utime(tmp_path / ".id-000001", (1, 1))

    image_id = artwork.reserve_kitty_image_id(tmp_path, "new-digest", 1, {1})

    assert image_id == 1
    assert len(list(tmp_path.glob(".id-*"))) == 4096
    assert deleted == ["\033_Ga=d,d=I,i=1,q=2;\033\\"]
    assert (tmp_path / ".id-000001").read_text().startswith("new-digest\n")


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
    os.utime(derived, (1, 1))
    monkeypatch.setattr(artwork, "cache_path", lambda: cache_dir)

    prune_artwork_cache(limit_bytes=0, protected_path=derived)

    assert not source.exists()
    assert derived.exists()

    prune_artwork_cache(limit_bytes=0)

    assert not derived.exists()


def test_prune_artwork_cache_keeps_pending_kitty_file(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    kitty_dir = cache_dir / "kitty"
    kitty_dir.mkdir(parents=True)
    pending = kitty_dir / "000001-digest.png"
    pending.write_bytes(b"pending")
    monkeypatch.setattr(artwork, "cache_path", lambda: cache_dir)

    prune_artwork_cache(limit_bytes=0)

    assert pending.exists()


@pytest.mark.parametrize("age, retained", [(59.9, True), (60.1, False)])
def test_kitty_transfer_retention_boundary_under_cache_pressure(tmp_path, monkeypatch, age, retained):
    kitty_dir = tmp_path / "kitty"
    kitty_dir.mkdir()
    transfer = kitty_dir / "000001-digest.png"
    transfer.write_bytes(b"pending")
    os.utime(transfer, (1000 - age, 1000 - age))
    monkeypatch.setattr(artwork, "cache_path", lambda: tmp_path)
    monkeypatch.setattr(artwork.time, "time", lambda: 1000)

    prune_artwork_cache(limit_bytes=0)

    assert transfer.exists() is retained


def test_prune_artwork_cache_continues_after_entry_disappears(tmp_path, monkeypatch):
    artwork_dir = tmp_path / "artwork"
    artwork_dir.mkdir()
    vanished = artwork_dir / "vanished.img"
    remaining = artwork_dir / "remaining.img"
    vanished.write_bytes(b"old")
    remaining.write_bytes(b"new")
    monkeypatch.setattr(artwork, "cache_path", lambda: tmp_path)
    stat = Path.stat

    def missing_stat(path, *args, **kwargs):
        if path == vanished:
            raise FileNotFoundError(path)
        return stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", missing_stat)

    prune_artwork_cache(limit_bytes=0)

    assert stat(vanished).st_size == 3
    assert not remaining.exists()
