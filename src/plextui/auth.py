from __future__ import annotations

import ipaddress
import webbrowser
from dataclasses import dataclass
from urllib.parse import SplitResult, urlparse

import requests
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
    def row_label(self) -> str:
        verified = ", reachable" if self.verified else ""
        return f"{self.scheme.upper()} ({self.connection_label}{verified})"

    @property
    def sort_key(self) -> tuple[int, str, str, int | None, str]:
        verified_rank = 0 if self.verified else 1
        if self.is_local and self.scheme == "http":
            return (verified_rank, "0", self.host, self.port, self.uri)
        if self.is_local:
            return (verified_rank, "1", self.host, self.port, self.uri)
        if self.scheme == "http":
            return (verified_rank, "2", self.host, self.port, self.uri)
        if self.is_plex_direct:
            return (verified_rank, "3", self.host, self.port, self.uri)
        return (verified_rank, "4", self.host, self.port, self.uri)

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
    saved = AppConfig(
        base_url=choice.uri,
        token=choice.resource.accessToken,
        client_identifier=config.client_identifier,
        account_token=account_token,
        preferred_audio_language=config.preferred_audio_language,
        preferred_subtitle_language=config.preferred_subtitle_language,
        subtitle_mode=config.subtitle_mode,
        artwork_mode=config.artwork_mode,
        artwork_renderer=config.artwork_renderer,
        detail_artwork_mode=config.detail_artwork_mode,
        grid_density=config.grid_density,
        media_view=config.media_view,
        theme=config.theme,
        mpv_window_size=config.mpv_window_size,
        playback_mode=config.playback_mode,
        transcode_quality=config.transcode_quality,
        page_size=config.page_size,
        auto_load_threshold=config.auto_load_threshold,
        grid_prefetch_pages=config.grid_prefetch_pages,
        hidden_library_keys=config.hidden_library_keys,
    )
    save_config(saved)
    return saved


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
    try:
        response = requests.get(
            uri,
            headers={"X-Plex-Token": token},
            params={"X-Plex-Token": token},
            timeout=timeout,
        )
    except requests.RequestException:
        return False
    if response.status_code not in {200, 201, 204}:
        return False
    return "MediaContainer" in response.text or response.headers.get("X-Plex-Protocol") == "1.0"


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
