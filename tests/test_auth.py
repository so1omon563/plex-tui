from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from plextui import __version__
from plextui.auth import LoginSession, ProfileChoice, ServerChoice, profile_choices, reachable_advertised_urls, reachable_server_choices, plex_headers, switch_profile
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
        identifier: str = "",
    ) -> None:
        self.name = name
        self.accessToken = token
        self.sourceTitle = source
        self.provides = "server"
        self._connections = connections
        self.reachable_uri = reachable_uri
        self.clientIdentifier = identifier
        self.connect_timeout = None

    def preferred_connections(self) -> list[str]:
        return self._connections

    def connect(self, timeout: int = 5) -> FakeServer:
        self.connect_timeout = timeout
        if not self.reachable_uri:
            raise RuntimeError("unreachable")
        return FakeServer(self.reachable_uri)


class FakeAccount:
    def __init__(
        self,
        resources: list[FakeResource],
        *,
        token: str = "account-token",
        account_id: int = 1,
        title: str = "Owner",
        users: list[object] | None = None,
    ) -> None:
        self._resources = resources
        self.authToken = token
        self.id = account_id
        self.title = title
        self.username = title
        self.friendlyName = title
        self.protected = False
        self._users = users or []

    def resources(self) -> list[FakeResource]:
        return self._resources

    def users(self) -> list[object]:
        return self._users

    def switchHomeUser(self, user, pin=None):
        if pin == "bad":
            raise RuntimeError("bad pin")
        return FakeAccount(
            [FakeResource("My Plex", "kid-server-token", [], reachable_uri="http://plex.example:32400")],
            token=f"{user.username}-token",
            account_id=user.id,
            title=user.title,
        )


class FakeUser:
    def __init__(self, title: str, user_id: int, *, home: bool = True, protected: bool = False) -> None:
        self.title = title
        self.username = title
        self.id = user_id
        self.home = home
        self.protected = protected


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


def test_server_choices_sort_implicit_port_before_explicit_port():
    resource = FakeResource("My Plex", "server-token", [])
    choices = [
        ServerChoice("My Plex", "http://localhost:32400", "owned", resource, verified=True),
        ServerChoice("My Plex", "http://localhost", "owned", resource, verified=True),
    ]

    assert [choice.uri for choice in sorted(choices, key=lambda choice: choice.sort_key)] == [
        "http://localhost",
        "http://localhost:32400",
    ]


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

    def fake_urlopen(request, timeout):
        return responses[urlsplit(request.full_url).scheme + "://" + urlsplit(request.full_url).netloc]

    monkeypatch.setattr("plextui.auth.MyPlexAccount", lambda token: FakeAccount(resources))
    monkeypatch.setattr("plextui.auth.urlopen", fake_urlopen)
    session = object.__new__(LoginSession)
    session.config = AppConfig("", "", "client-id")
    session.pin_login = FakePinLogin("account-token")

    _account_token, choices = session.wait()

    assert [choice.uri for choice in choices] == ["http://192.168.0.13:32400"]
    assert choices[0].verified


def test_profile_choices_include_current_home_users(monkeypatch):
    users = [
        FakeUser("Kid", 2, protected=True),
        FakeUser("Friend", 3, home=False),
    ]

    def fake_account(token: str) -> FakeAccount:
        if token == "kid-token":
            return FakeAccount([], token=token, account_id=2, title="Kid")
        return FakeAccount([], token=token, account_id=1, title="Owner", users=users)

    monkeypatch.setattr("plextui.auth.MyPlexAccount", fake_account)

    choices = profile_choices(AppConfig("http://plex", "server", "client", account_token="kid-token", home_account_token="home-token"))

    assert [(choice.title, choice.key, choice.protected, choice.current) for choice in choices] == [
        ("Owner", "1", False, False),
        ("Kid", "2", True, True),
    ]


def test_switch_profile_saves_profile_and_home_tokens(monkeypatch):
    users = [FakeUser("Kid", 2)]
    home_account = FakeAccount(
        [FakeResource("My Plex", "owner-server-token", [], reachable_uri="http://plex.example:32400")],
        token="home-token",
        account_id=1,
        title="Owner",
        users=users,
    )
    saved = {}
    root_checks = []

    monkeypatch.setattr("plextui.auth.MyPlexAccount", lambda token: home_account)
    monkeypatch.setattr("plextui.auth.plex_root_responds", lambda *args: root_checks.append(args) or True)
    monkeypatch.setattr("plextui.auth.save_config", lambda config: saved.setdefault("config", config))

    switched = switch_profile(
        AppConfig("http://plex.example:32400", "owner-server-token", "client", account_token="home-token"),
        ProfileChoice("Kid", "2", False, False, users[0]),
    )

    assert switched.token == "kid-server-token"
    assert switched.account_token == "Kid-token"
    assert switched.home_account_token == "home-token"
    assert switched.active_profile_title == "Kid"
    assert root_checks == []
    assert saved["config"] == switched


def test_switch_profile_reuses_current_server_when_profile_has_no_resources(monkeypatch):
    users = [FakeUser("Kid", 2)]
    profile_account = FakeAccount([], token="Kid-token", account_id=2, title="Kid")
    home_account = FakeAccount(
        [FakeResource("My Plex", "owner-server-token", [], reachable_uri="http://plex.example:32400")],
        token="home-token",
        account_id=1,
        title="Owner",
        users=users,
    )
    saved = {}
    root_checks = []

    def switch_home_user(user, pin=None):
        return profile_account

    def plex_root_responds(uri, token, timeout):
        root_checks.append((uri, token, timeout))
        return uri == "http://plex.example:32400" and token == "Kid-token"

    home_account.switchHomeUser = switch_home_user
    monkeypatch.setattr("plextui.auth.MyPlexAccount", lambda token: home_account)
    monkeypatch.setattr("plextui.auth.plex_root_responds", plex_root_responds)
    monkeypatch.setattr("plextui.auth.save_config", lambda config: saved.setdefault("config", config))

    switched = switch_profile(
        AppConfig("http://plex.example:32400", "owner-server-token", "client", account_token="home-token"),
        ProfileChoice("Kid", "2", False, False, users[0]),
    )

    assert root_checks == [("http://plex.example:32400", "Kid-token", 5)]
    assert switched.base_url == "http://plex.example:32400"
    assert switched.token == "Kid-token"
    assert switched.account_token == "Kid-token"
    assert switched.home_account_token == "home-token"
    assert switched.active_profile_title == "Kid"
    assert saved["config"] == switched


def test_switch_profile_keeps_server_identity_when_url_changes(monkeypatch):
    users = [FakeUser("Kid", 2)]
    profile_account = FakeAccount(
        [
            FakeResource(
                "Another Plex",
                "other-token",
                [],
                reachable_uri="http://127.0.0.1:32400",
                identifier="other-server",
            ),
            FakeResource(
                "My Plex",
                "kid-server-token",
                [],
                reachable_uri="https://new.example:32400",
                identifier="saved-server",
            ),
        ],
        token="Kid-token",
        account_id=2,
        title="Kid",
    )
    home_account = FakeAccount([], token="home-token", users=users)
    home_account.switchHomeUser = lambda user, pin=None: profile_account
    saved = {}
    monkeypatch.setattr("plextui.auth.MyPlexAccount", lambda token: home_account)
    monkeypatch.setattr("plextui.auth.save_config", lambda config: saved.setdefault("config", config))

    switched = switch_profile(
        AppConfig(
            "https://old.example:32400",
            "owner-server-token",
            "client",
            account_token="home-token",
            server_identifier="saved-server",
        ),
        ProfileChoice("Kid", "2", False, False, users[0]),
    )

    assert switched.base_url == "https://new.example:32400"
    assert switched.token == "kid-server-token"
    assert switched.server_identifier == "saved-server"
    assert saved["config"] == switched


def test_switch_profile_does_not_fall_back_to_another_server(monkeypatch):
    users = [FakeUser("Kid", 2)]
    profile_account = FakeAccount(
        [
            FakeResource(
                "Another Plex",
                "other-token",
                [],
                reachable_uri="http://127.0.0.1:32400",
                identifier="other-server",
            )
        ],
        token="Kid-token",
        account_id=2,
        title="Kid",
    )
    home_account = FakeAccount([], token="home-token", users=users)
    home_account.switchHomeUser = lambda user, pin=None: profile_account
    monkeypatch.setattr("plextui.auth.MyPlexAccount", lambda token: home_account)
    monkeypatch.setattr("plextui.auth.plex_root_responds", lambda *args, **kwargs: False)

    with pytest.raises(RuntimeError, match="relogin to choose a server explicitly"):
        switch_profile(
            AppConfig(
                "https://old.example:32400",
                "owner-server-token",
                "client",
                account_token="home-token",
                server_identifier="saved-server",
            ),
            ProfileChoice("Kid", "2", False, False, users[0]),
        )


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

    def fake_urlopen(request, timeout):
        url = urlsplit(request.full_url)
        seen["uri"] = f"{url.scheme}://{url.netloc}"
        seen["headers"] = dict(request.header_items())
        seen["params"] = parse_qs(url.query)
        seen["timeout"] = timeout
        return FakeResponse(200, "", {"X-Plex-Protocol": "1.0"})

    monkeypatch.setattr("plextui.auth.urlopen", fake_urlopen)

    assert reachable_advertised_urls(resource, timeout=2) == ["http://plex.example:32400"]
    assert seen == {
        "uri": "http://plex.example:32400",
        "headers": {"X-plex-token": "server-token"},
        "params": {"X-Plex-Token": ["server-token"]},
        "timeout": 2,
    }


class FakeResponse:
    def __init__(self, status_code: int, text: str, headers: dict[str, str] | None = None) -> None:
        self.status = status_code
        self.text = text
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size: int = -1) -> bytes:
        return self.text.encode("utf-8")
