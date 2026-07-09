import pytest

from certmon.config import ConfigError
import launcher


def test_launcher_rejects_lan_bind_without_server_mode(monkeypatch):
    monkeypatch.delenv("CERTMON_SERVER_MODE", raising=False)
    monkeypatch.setenv("CERTMON_BIND_HOST", "0.0.0.0")

    with pytest.raises(ConfigError, match="LAN binding requires CERTMON_SERVER_MODE=1"):
        launcher.resolve_launcher_runtime()


def test_launcher_allows_explicit_server_mode_lan_bind(monkeypatch):
    monkeypatch.setenv("CERTMON_SERVER_MODE", "1")
    monkeypatch.setenv("CERTMON_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("CERTMON_PORT", "5088")

    runtime = launcher.resolve_launcher_runtime()

    assert runtime.server_mode is True
    assert runtime.auth_required is True
    assert runtime.bind_host == "0.0.0.0"
    assert runtime.port == 5088


def test_launcher_desktop_mode_keeps_free_loopback_port(monkeypatch):
    monkeypatch.delenv("CERTMON_SERVER_MODE", raising=False)
    monkeypatch.delenv("CERTMON_BIND_HOST", raising=False)
    monkeypatch.setenv("CERTMON_PORT", "5090")
    monkeypatch.setattr(launcher, "find_free_port", lambda start: start + 1)

    runtime = launcher.resolve_launcher_runtime()

    assert runtime.server_mode is False
    assert runtime.auth_required is False
    assert runtime.bind_host == "127.0.0.1"
    assert runtime.port == 5091
