from __future__ import annotations

import os
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_dir


APP_NAME = "plex-tui"


@dataclass(frozen=True)
class AppConfig:
    base_url: str
    token: str
    client_identifier: str
    account_token: str = ""


def config_path() -> Path:
    return Path(user_config_dir(APP_NAME)) / "config.toml"


def load_config() -> AppConfig:
    data: dict[str, str] = {}
    path = config_path()
    if path.exists():
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
        data = {k: str(v) for k, v in raw.items() if isinstance(v, str)}

    base_url = os.environ.get("PLEX_TUI_BASE_URL") or data.get("base_url", "")
    token = os.environ.get("PLEX_TUI_TOKEN") or data.get("token", "")
    client_identifier = data.get("client_identifier") or f"plex-tui-{uuid.uuid4()}"
    account_token = data.get("account_token", "")
    return AppConfig(
        base_url=base_url.strip(),
        token=token.strip(),
        client_identifier=client_identifier.strip(),
        account_token=account_token.strip(),
    )


def save_config(config: AppConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f'base_url = "{_toml_escape(config.base_url)}"',
        f'token = "{_toml_escape(config.token)}"',
        f'client_identifier = "{_toml_escape(config.client_identifier)}"',
    ]
    if config.account_token:
        lines.append(f'account_token = "{_toml_escape(config.account_token)}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
