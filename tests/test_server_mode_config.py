import pytest

from certmon.config import ConfigError, resolve_runtime_config


def test_desktop_mode_defaults_to_loopback(monkeypatch, tmp_path):
    monkeypatch.delenv("CERTMON_SERVER_MODE", raising=False)
    monkeypatch.delenv("CERTMON_BIND_HOST", raising=False)
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("CERTMON_PORT", raising=False)
    monkeypatch.delenv("PORT", raising=False)

    config = resolve_runtime_config(
        frozen=False,
        executable=tmp_path / "CertMon.exe",
        source_dir=tmp_path,
    )

    assert config.bind_host == "127.0.0.1"
    assert config.port == 5000
    assert config.server_mode is False
    assert config.auth_required is False


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.0.10"])
def test_lan_bind_requires_server_mode(monkeypatch, tmp_path, host):
    monkeypatch.delenv("CERTMON_SERVER_MODE", raising=False)
    monkeypatch.setenv("CERTMON_BIND_HOST", host)

    with pytest.raises(ConfigError, match="LAN binding requires CERTMON_SERVER_MODE=1"):
        resolve_runtime_config(
            frozen=False,
            executable=tmp_path / "CertMon.exe",
            source_dir=tmp_path,
        )


def test_server_mode_allows_lan_bind_and_requires_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("CERTMON_SERVER_MODE", "1")
    monkeypatch.setenv("CERTMON_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("CERTMON_PORT", "8080")

    config = resolve_runtime_config(
        frozen=False,
        executable=tmp_path / "CertMon.exe",
        source_dir=tmp_path,
    )

    assert config.bind_host == "0.0.0.0"
    assert config.port == 8080
    assert config.server_mode is True
    assert config.auth_required is True


def test_invalid_port_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("CERTMON_PORT", "70000")

    with pytest.raises(ConfigError, match="between 1 and 65535"):
        resolve_runtime_config(
            frozen=False,
            executable=tmp_path / "CertMon.exe",
            source_dir=tmp_path,
        )
