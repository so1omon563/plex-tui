from __future__ import annotations

from plextui import __version__
from plextui.auth import LoginSession, plex_headers
from plextui.config import AppConfig


class PinLogin:
    def run(self, timeout: int = 300) -> None:
        self.timeout = timeout

    def oauthUrl(self) -> str:
        return "http://plex/login"


class FakePinLogin:
    def __init__(self, token: str) -> None:
        self.token = token

    def run(self, timeout: int = 300) -> None:
        self.timeout = timeout

    def waitForLogin(self) -> bool:
        return True


class FakeResource:
    def __init__(self, name: str, token: str, connections: list[str], source: str = "owned") -> None:
        self.name = name
        self.accessToken = token
        self.sourceTitle = source
        self.provides = "server"
        self._connections = connections

    def preferred_connections(self) -> list[str]:
        return self._connections


class FakeAccount:
    def __init__(self, resources: list[FakeResource]) -> None:
        self._resources = resources

    def resources(self) -> list[FakeResource]:
        return self._resources


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


def test_login_wait_filters_and_orders_connections(monkeypatch):
    resources = [
        FakeResource(
            "My Plex",
            "server-token",
            [
                "https://192-168-0-13.c6b9a2e9ab05414c9f740f76903d0db3.plex.direct:32400",
                "http://192.168.0.13:32400",
            ],
        ),
        FakeResource(
            "My Plex",
            "server-token",
            [
                "https://24-255-40-151.c6b9a2e9ab05414c9f740f76903d0db3.plex.direct:17734",
                "http://24.255.40.151:17734",
            ],
        ),
    ]

    monkeypatch.setattr("plextui.auth.MyPlexAccount", lambda token: FakeAccount(resources))
    session = object.__new__(LoginSession)
    session.config = AppConfig("", "", "client-id")
    session.pin_login = FakePinLogin("account-token")

    account_token, choices = session.wait()

    assert account_token == "account-token"
    assert [choice.uri for choice in choices[:2]] == [
        "http://192.168.0.13:32400",
        "http://24.255.40.151:17734",
    ]
    assert all("plex.direct" not in choice.uri for choice in choices[:2])
