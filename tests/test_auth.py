from __future__ import annotations

from plextui import __version__
from plextui.auth import LoginSession, plex_headers
from plextui.config import AppConfig


class PinLogin:
    def run(self, timeout: int = 300) -> None:
        self.timeout = timeout

    def oauthUrl(self) -> str:
        return "http://plex/login"


def test_login_start_returns_url_when_browser_open_fails(monkeypatch):
    monkeypatch.setattr("plextui.auth.webbrowser.open", lambda url: (_ for _ in ()).throw(RuntimeError("no browser")))
    session = object.__new__(LoginSession)
    session.config = AppConfig("", "", "client-id")
    session.pin_login = PinLogin()

    assert session.start(timeout=10) == "http://plex/login"
    assert session.pin_login.timeout == 10


def test_plex_headers_use_package_version():
    headers = plex_headers(AppConfig("", "", "client-id"))

    assert headers["X-Plex-Version"] == __version__
    assert headers["X-Plex-Client-Identifier"] == "client-id"
