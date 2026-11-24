import pytest


@pytest.fixture(autouse=True)
def isolate_ssh_environment(monkeypatch):
    """Make tests local by default, even when pytest runs over SSH."""
    for name in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"):
        monkeypatch.delenv(name, raising=False)
