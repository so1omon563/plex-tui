from __future__ import annotations

import ipaddress
import webbrowser
from dataclasses import dataclass
from urllib.parse import SplitResult, urlparse

from plexapi.myplex import MyPlexAccount, MyPlexPinLogin, MyPlexResource

from . import __version__
from .config import APP_NAME, AppConfig, save_config


@dataclass(frozen=True)
class ServerChoice:
    name: str
    uri: str
    source: str
    resource: MyPlexResource

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
        return self.scheme

    @property
    def row_label(self) -> str:
        return f"{self.scheme.upper()} ({self.connection_label})"

    @property
    def sort_key(self) -> tuple[int, str, int | None, str]:
        if self.is_local and self.scheme == "http":
            return (0, self.host, self.port, self.uri)
        if self.is_local:
            return (1, self.host, self.port, self.uri)
        if self.scheme == "http":
            return (2, self.host, self.port, self.uri)
        if self.is_plex_direct:
            return (3, self.host, self.port, self.uri)
        return (4, self.host, self.port, self.uri)

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
        choices: list[ServerChoice] = []
        seen: set[tuple[str, str]] = set()
        for resource in account.resources():
            if "server" not in str(resource.provides):
                continue
            for uri in resource.preferred_connections():
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
                    )
                )
        if not choices:
            raise RuntimeError("No Plex Media Server resources found for this account")

        non_direct_choices = [choice for choice in choices if not choice.is_plex_direct]
        return account_token, sorted(non_direct_choices or choices, key=lambda c: c.sort_key)

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
        page_size=config.page_size,
        auto_load_threshold=config.auto_load_threshold,
        grid_prefetch_pages=config.grid_prefetch_pages,
    )
    save_config(saved)
    return saved


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
