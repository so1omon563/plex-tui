from __future__ import annotations

from plextui import __version__
from plextui.auth import LoginSession, reachable_advertised_urls, reachable_server_choices, plex_headers
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


class FakeServer:
    def __init__(self, baseurl: str) -> None:
        self._baseurl = baseurl


class FakeResource:
    def __init__(
        self,
        name: str,
        token: str,
        connections: list[str],
        source: str = "owned",
        reachable_uri: str = "",
    ) -> None:
        self.name = name
        self.accessToken = token
        self.sourceTitle = source
        self.provides = "server"
        self._connections = connections
        self.reachable_uri = reachable_uri
        self.connect_timeout = None

    def preferred_connections(self) -> list[str]:
        return self._connections

    def connect(self, timeout: int = 5) -> FakeServer:
        self.connect_timeout = timeout
        if not self.reachable_uri:
            raise RuntimeError("unreachable")
        return FakeServer(self.reachable_uri)


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


def test_login_wait_uses_reachable_resource_connection(monkeypatch):
    resources = [
        FakeResource(
            "My Plex",
            "server-token",
            [
                "https://192-168-0-13.c6b9a2e9ab05414c9f740f76903d0db3.plex.direct:32400",
                "http://192.168.0.13:32400",
            ],
            reachable_uri="https://23-239-4-140.c6b9a2e9ab05414c9f740f76903d0db3.plex.direct:8443",
        ),
        FakeResource(
            "Offline Plex",
            "offline-token",
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
    assert len(choices) == 1
    assert choices[0].uri == "https://23-239-4-140.c6b9a2e9ab05414c9f740f76903d0db3.plex.direct:8443"
    assert choices[0].verified
    assert resources[0].connect_timeout == 5


def test_login_wait_fails_when_no_resource_connections_are_reachable(monkeypatch):
    resources = [
        FakeResource("My Plex", "server-token", ["http://192.168.0.13:32400"]),
    ]

    monkeypatch.setattr("plextui.auth.MyPlexAccount", lambda token: FakeAccount(resources))
    session = object.__new__(LoginSession)
    session.config = AppConfig("", "", "client-id")
    session.pin_login = FakePinLogin("account-token")

    try:
        session.wait()
    except RuntimeError as exc:
        assert "No reachable Plex Media Server connections" in str(exc)
    else:
        raise AssertionError("expected unreachable login resources to fail")


def test_login_wait_falls_back_to_reachable_advertised_urls(monkeypatch):
    resource = FakeResource(
        "My Plex",
        "server-token",
        [
            "http://192.168.0.13:32400",
            "http://24.255.40.151:17734",
        ],
    )
    resources = [resource]
    responses = {
        "http://192.168.0.13:32400": FakeResponse(200, "<MediaContainer friendlyName='Plex' />"),
        "http://24.255.40.151:17734": FakeResponse(404, "not found"),
    }

    monkeypatch.setattr("plextui.auth.MyPlexAccount", lambda token: FakeAccount(resources))
    monkeypatch.setattr("plextui.auth.requests.get", lambda uri, **kwargs: responses[uri])
    session = object.__new__(LoginSession)
    session.config = AppConfig("", "", "client-id")
    session.pin_login = FakePinLogin("account-token")

    _account_token, choices = session.wait()

    assert [choice.uri for choice in choices] == ["http://192.168.0.13:32400"]
    assert choices[0].verified


def test_reachable_server_choices_deduplicates_connected_urls():
    resources = [
        FakeResource("My Plex", "server-token", [], reachable_uri="http://plex.example:32400"),
        FakeResource("My Plex", "server-token", [], reachable_uri="http://plex.example:32400"),
    ]

    choices = reachable_server_choices(resources, timeout=1)

    assert [choice.uri for choice in choices] == ["http://plex.example:32400"]


def test_reachable_advertised_urls_accepts_plex_protocol_header(monkeypatch):
    resource = FakeResource("My Plex", "server-token", ["http://plex.example:32400"])
    seen = {}

    def fake_get(uri, **kwargs):
        seen["uri"] = uri
        seen["headers"] = kwargs["headers"]
        seen["params"] = kwargs["params"]
        seen["timeout"] = kwargs["timeout"]
        return FakeResponse(200, "", {"X-Plex-Protocol": "1.0"})

    monkeypatch.setattr("plextui.auth.requests.get", fake_get)

    assert reachable_advertised_urls(resource, timeout=2) == ["http://plex.example:32400"]
    assert seen == {
        "uri": "http://plex.example:32400",
        "headers": {"X-Plex-Token": "server-token"},
        "params": {"X-Plex-Token": "server-token"},
        "timeout": 2,
    }


class FakeResponse:
    def __init__(self, status_code: int, text: str, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
