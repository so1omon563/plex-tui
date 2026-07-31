from __future__ import annotations

import ipaddress
import webbrowser
from dataclasses import dataclass, replace
from urllib.parse import SplitResult, urlencode, urlparse
from urllib.request import Request, urlopen

from plexapi.myplex import MyPlexAccount, MyPlexPinLogin, MyPlexResource

from . import __version__
from .config import APP_NAME, AppConfig, save_config


@dataclass(frozen=True)
class ServerChoice:
    name: str
    uri: str
    source: str
    resource: MyPlexResource
    verified: bool = False

    @property
    def parsed_uri(self) -> SplitResult:
        return urlparse(self.uri)

    @property
    def host(self) -> str:
        return self.parsed_uri.hostname or ""

    @property
    def scheme(self) -> str:
        return self.parsed_uri.scheme or ""

    @property
    def port(self) -> int | None:
        return self.parsed_uri.port

    @property
    def is_local(self) -> bool:
        if self.host in {"localhost", "127.0.0.1", "::1"}:
            return True
        if self._looks_like_private_host(self.host):
            return True
        if self._looks_like_plex_direct_private_ip(self.host):
            return True
        return False

    @property
    def is_plex_direct(self) -> bool:
        return self.host.endswith(".plex.direct") if self.host else False

    @property
    def connection_label(self) -> str:
        if self.is_local:
            return "local"
        if self.is_plex_direct:
            return "plex.direct"
        return "remote"

    @property
    def resource_identifier(self) -> str:
        return str(getattr(self.resource, "clientIdentifier", "") or "")

    @property
    def row_label(self) -> str:
        verified = ", reachable" if self.verified else ""
        return f"{self.scheme.upper()} ({self.connection_label}{verified})"

    @property
    def sort_key(self) -> tuple[int, str, str, int, str]:
        verified_rank = 0 if self.verified else 1
        port = self.port if self.port is not None else -1
        if self.is_local and self.scheme == "http":
            return (verified_rank, "0", self.host, port, self.uri)
        if self.is_local:
            return (verified_rank, "1", self.host, port, self.uri)
        if self.scheme == "http":
            return (verified_rank, "2", self.host, port, self.uri)
        if self.is_plex_direct:
            return (verified_rank, "3", self.host, port, self.uri)
        return (verified_rank, "4", self.host, port, self.uri)

    @staticmethod
    def _looks_like_private_host(host: str) -> bool:
        try:
            return ipaddress.ip_address(host).is_private
        except ValueError:
            return False

    @staticmethod
    def _looks_like_plex_direct_private_ip(host: str) -> bool:
        if not host.endswith(".plex.direct"):
            return False
        candidate = host.removesuffix(".plex.direct").split(".", 1)[0]
        parts = candidate.split("-")
        if len(parts) != 4:
            return False
        try:
            return ipaddress.ip_address(".".join(parts)).is_private
        except ValueError:
            return False


@dataclass(frozen=True)
class ProfileChoice:
    title: str
    key: str
    protected: bool
    current: bool
    user: object | None = None


class LoginSession:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.pin_login = MyPlexPinLogin(headers=plex_headers(config), oauth=True)

    def start(self, timeout: int = 300) -> str:
        self.pin_login.run(timeout=timeout)
        url = self.pin_login.oauthUrl()
        try:
            webbrowser.open(url)
        except Exception:
            pass
        return url

    def wait(self) -> tuple[str, list[ServerChoice]]:
        if not self.pin_login.waitForLogin() or not self.pin_login.token:
            raise RuntimeError("Plex login timed out or was cancelled")

        account_token = self.pin_login.token
        account = MyPlexAccount(token=account_token)
        resources = []
        for resource in account.resources():
            if "server" not in str(resource.provides):
                continue
            resources.append(resource)
        if not resources:
            raise RuntimeError("No Plex Media Server resources found for this account")

        choices = reachable_server_choices(resources)
        if not choices:
            raise RuntimeError(
                "No reachable Plex Media Server connections found for this account. "
                "Plex reported servers, but none responded from this machine. "
                "Check Plex remote access, VPN/firewall rules, and whether the server is online."
            )
        return account_token, sorted(choices, key=lambda c: c.sort_key)

    def stop(self) -> None:
        self.pin_login.stop()


def save_server_choice(config: AppConfig, account_token: str, choice: ServerChoice) -> AppConfig:
    saved = replace(
        config,
        base_url=choice.uri,
        token=choice.resource.accessToken,
        account_token=account_token,
        home_account_token=account_token,
        server_identifier=choice.resource_identifier,
    )
    save_config(saved)
    return saved


def profile_choices(config: AppConfig) -> list[ProfileChoice]:
    home_token = config.home_account_token or config.account_token
    if not home_token:
        raise RuntimeError("Plex account login is required before switching profiles")
    home_account = MyPlexAccount(token=home_token)
    active_account = MyPlexAccount(token=config.account_token or home_token)
    active_id = str(getattr(active_account, "id", ""))
    choices = [
        ProfileChoice(
            profile_title(home_account),
            str(getattr(home_account, "id", "")),
            bool(getattr(home_account, "protected", False)),
            str(getattr(home_account, "id", "")) == active_id,
        )
    ]
    for user in home_account.users():
        if not getattr(user, "home", False):
            continue
        choices.append(
            ProfileChoice(
                profile_title(user),
                str(getattr(user, "id", "")),
                bool(getattr(user, "protected", False)),
                str(getattr(user, "id", "")) == active_id,
                user=user,
            )
        )
    return choices


def switch_profile(config: AppConfig, choice: ProfileChoice, pin: str = "") -> AppConfig:
    home_token = config.home_account_token or config.account_token
    if not home_token:
        raise RuntimeError("Plex account login is required before switching profiles")
    home_account = MyPlexAccount(token=home_token)
    if choice.user is None or choice.key == str(getattr(home_account, "id", "")):
        account = home_account
    else:
        account = home_account.switchHomeUser(choice.user, pin=pin or None)
    account_token = str(account.authToken)
    server_choices = reachable_server_choices([
        resource
        for resource in account.resources()
        if "server" in str(resource.provides)
    ])
    if server_choices:
        selected = matching_server_choice(server_choices, config.base_url, config.server_identifier)
    else:
        selected = None
    if selected is not None:
        saved = replace(
            config,
            base_url=selected.uri,
            token=selected.resource.accessToken,
            account_token=account_token,
            home_account_token=home_token,
            active_profile_title=profile_title(account),
            server_identifier=selected.resource_identifier,
        )
    elif config.base_url and plex_root_responds(config.base_url, account_token, timeout=5):
        saved = replace(
            config,
            token=account_token,
            account_token=account_token,
            home_account_token=home_token,
            active_profile_title=profile_title(account),
        )
    else:
        raise RuntimeError(
            "The saved Plex server is not reachable for this profile; "
            "relogin to choose a server explicitly"
        )
    save_config(saved)
    return saved


def matching_server_choice(
    choices: list[ServerChoice],
    base_url: str,
    resource_identifier: str = "",
) -> ServerChoice | None:
    if resource_identifier:
        matches = [choice for choice in choices if choice.resource_identifier == resource_identifier]
        return min(matches, key=lambda choice: choice.sort_key) if matches else None
    target = base_url.rstrip("/")
    for choice in choices:
        if choice.uri.rstrip("/") == target:
            return choice
    return None


def profile_title(profile: object) -> str:
    return (
        str(getattr(profile, "title", "") or "")
        or str(getattr(profile, "friendlyName", "") or "")
        or str(getattr(profile, "username", "") or "")
        or "Plex Profile"
    )


def reachable_server_choices(resources: list[MyPlexResource], timeout: int = 5) -> list[ServerChoice]:
    choices = []
    seen: set[tuple[str, str]] = set()
    for resource in resources:
        for uri in reachable_resource_urls(resource, timeout):
            key = (resource.name, uri)
            if key in seen:
                continue
            seen.add(key)
            choices.append(
                ServerChoice(
                    name=resource.name,
                    uri=uri,
                    source=resource.sourceTitle or "owned",
                    resource=resource,
                    verified=True,
                )
            )
    return choices


def reachable_resource_urls(resource: MyPlexResource, timeout: int) -> list[str]:
    try:
        server = resource.connect(timeout=timeout)
    except Exception:
        return reachable_advertised_urls(resource, timeout)

    uri = str(getattr(server, "_baseurl", "") or getattr(server, "baseurl", "") or "").rstrip("/")
    return [uri] if uri else reachable_advertised_urls(resource, timeout)


def reachable_advertised_urls(resource: MyPlexResource, timeout: int) -> list[str]:
    reachable = []
    for uri in resource.preferred_connections():
        normalized = uri.rstrip("/")
        if normalized and plex_root_responds(normalized, resource.accessToken, timeout):
            reachable.append(normalized)
    return reachable


def plex_root_responds(uri: str, token: str, timeout: int) -> bool:
    url = f"{uri}{'&' if '?' in uri else '?'}{urlencode({'X-Plex-Token': token})}"
    request = Request(url, headers={"X-Plex-Token": token})
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            text = response.read(4096).decode("utf-8", errors="replace")
            headers = response.headers
    except OSError:
        return False
    if status not in {200, 201, 204}:
        return False
    return "MediaContainer" in text or headers.get("X-Plex-Protocol") == "1.0"


def plex_headers(config: AppConfig) -> dict[str, str]:
    return {
        "X-Plex-Product": APP_NAME,
        "X-Plex-Version": __version__,
        "X-Plex-Client-Identifier": config.client_identifier,
        "X-Plex-Platform": "Python",
        "X-Plex-Platform-Version": "3",
        "X-Plex-Device": "terminal",
        "X-Plex-Device-Name": APP_NAME,
    }
