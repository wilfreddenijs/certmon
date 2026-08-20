import os
import ipaddress
from dataclasses import dataclass
from pathlib import Path


LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
DEFAULT_MAX_BACKUP_UPLOAD_MB = 512
TRUE_VALUES = {"1", "true", "yes", "on"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeConfig:
    data_dir: Path
    bind_host: str
    port: int
    server_mode: bool
    auth_required: bool
    max_backup_upload_bytes: int


def resolve_data_dir(*, frozen: bool, executable: Path, source_dir: Path) -> Path:
    configured = os.environ.get("CERTMON_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if frozen:
        program_data = Path(os.environ.get("PROGRAMDATA", executable.parent))
        return program_data / "CertMon"
    return source_dir / "data"


def _env_flag(name, *, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in TRUE_VALUES


def _is_loopback_host(host):
    normalized = (host or "").strip().lower()
    if normalized in {"localhost", "::1"}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _is_wildcard_host(host):
    normalized = (host or "").strip().lower()
    return normalized in {"0.0.0.0", "::", ""}


def resolve_runtime_config(*, frozen: bool, executable: Path, source_dir: Path) -> RuntimeConfig:
    data_dir = resolve_data_dir(
        frozen=frozen,
        executable=executable,
        source_dir=source_dir,
    )
    bind_host = os.environ.get("CERTMON_BIND_HOST") or os.environ.get("HOST") or LOOPBACK_HOST
    bind_host = bind_host.strip() or LOOPBACK_HOST
    port_value = os.environ.get("CERTMON_PORT") or os.environ.get("PORT") or str(DEFAULT_PORT)
    try:
        port = int(port_value)
    except ValueError as exc:
        raise ConfigError(f"Invalid CERTMON_PORT/PORT value: {port_value!r}") from exc
    if port < 1 or port > 65535:
        raise ConfigError("CertMon port must be between 1 and 65535")

    upload_mb_value = os.environ.get(
        "CERTMON_MAX_BACKUP_UPLOAD_MB", str(DEFAULT_MAX_BACKUP_UPLOAD_MB)
    )
    try:
        max_backup_upload_mb = int(upload_mb_value)
    except ValueError as exc:
        raise ConfigError(
            f"Invalid CERTMON_MAX_BACKUP_UPLOAD_MB value: {upload_mb_value!r}"
        ) from exc
    if max_backup_upload_mb <= 0:
        raise ConfigError("CERTMON_MAX_BACKUP_UPLOAD_MB must be greater than zero")

    server_mode = _env_flag("CERTMON_SERVER_MODE", default=False)
    lan_bind = _is_wildcard_host(bind_host) or not _is_loopback_host(bind_host)
    if lan_bind and not server_mode:
        raise ConfigError(
            "LAN binding requires CERTMON_SERVER_MODE=1. "
            "Default desktop mode is loopback-only."
        )

    return RuntimeConfig(
        data_dir=data_dir,
        bind_host=bind_host,
        port=port,
        server_mode=server_mode,
        auth_required=server_mode,
        max_backup_upload_bytes=max_backup_upload_mb * 1024 * 1024,
    )
