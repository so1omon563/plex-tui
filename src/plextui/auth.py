from __future__ import annotations

import webbrowser
from dataclasses import dataclass

from plexapi.myplex import MyPlexAccount, MyPlexPinLogin, MyPlexResource

from .config import APP_NAME, AppConfig, save_config


@dataclass(frozen=True)
class ServerChoice:
    name: str
    uri: str
    source: str
    resource: MyPlexResource


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
        for resource in account.resources():
            if "server" not in str(resource.provides):
                continue
            for uri in resource.preferred_connections():
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
        return account_token, choices

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
        media_view=config.media_view,
        theme=config.theme,
        mpv_window_size=config.mpv_window_size,
    )
    save_config(saved)
    return saved


def plex_headers(config: AppConfig) -> dict[str, str]:
    return {
        "X-Plex-Product": APP_NAME,
        "X-Plex-Version": "0.1.0",
        "X-Plex-Client-Identifier": config.client_identifier,
        "X-Plex-Platform": "Python",
        "X-Plex-Platform-Version": "3",
        "X-Plex-Device": "terminal",
        "X-Plex-Device-Name": APP_NAME,
    }
