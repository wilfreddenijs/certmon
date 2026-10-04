import io
import zipfile
from pathlib import Path

import pytest

from certmon.auth import hash_password
from certmon.config import ConfigError, resolve_runtime_config
from certmon.permissions import Permission, permissions_for_roles
from tests.test_auth_api import load_app


def auth_headers(client):
    status = client.get("/api/auth/status").get_json()
    return {status["csrf_header"]: status["csrf_token"]}


def login_as(module, client, role):
    module.database.create_user(
        user_id=f"{role}-1",
        username=role,
        password_hash=hash_password("correct horse"),
        roles=[role],
    )
    assert client.post(
        "/api/auth/login",
        json={"username": role, "password": "correct horse"},
    ).status_code == 200


@pytest.mark.parametrize("role", ["viewer", "operator", "ca_admin"])
def test_unprivileged_roles_are_rejected_before_backup_processing(tmp_data_dir, monkeypatch, role):
    module = load_app(tmp_data_dir, monkeypatch)
    client = module.app.test_client()
    login_as(module, client, role)
    monkeypatch.setattr(
        module.server_backup_service,
        "stage_restore",
        lambda *_args, **_kwargs: pytest.fail("backup content was processed"),
    )

    response = client.post(
        "/api/server-backup/restore",
        data={
            "passphrase": "must-not-be-read",
            "backup": (io.BytesIO(b"not-a-zip"), "backup.zip"),
        },
        headers=auth_headers(client),
    )

    assert response.status_code == 403


def test_server_backup_permission_is_limited_to_security_admin_and_admin():
    assert Permission.MANAGE_SERVER_BACKUP in permissions_for_roles(["security_admin"])
    assert Permission.MANAGE_SERVER_BACKUP in permissions_for_roles(["admin"])
    for role in ("viewer", "operator", "ca_admin"):
        assert Permission.MANAGE_SERVER_BACKUP not in permissions_for_roles([role])


@pytest.mark.parametrize("role", ["security_admin", "admin"])
def test_authorized_roles_can_export_and_stage_restore(tmp_data_dir, monkeypatch, role):
    module = load_app(tmp_data_dir, monkeypatch)
    client = module.app.test_client()
    login_as(module, client, role)
    headers = auth_headers(client)

    exported = client.post(
        "/api/server-backup/export",
        json={"passphrase": "correct passphrase"},
        headers=headers,
    )
    assert exported.status_code == 200
    assert exported.headers["Content-Disposition"].startswith(
        "attachment; filename=certmon-server-backup-"
    )
    with zipfile.ZipFile(io.BytesIO(exported.data)) as archive:
        assert "recovery-package.json" in archive.namelist()

    restored = client.post(
        "/api/server-backup/restore",
        data={
            "passphrase": "correct passphrase",
            "backup": (io.BytesIO(exported.data), "backup.zip"),
        },
        headers=headers,
    )
    body = restored.get_json()
    assert restored.status_code == 200
    assert body["staged_path"] != str(tmp_data_dir)
    assert any("Stop CertMon" in step for step in body["activation_steps"])
    exported.close()


def test_server_backup_routes_require_csrf_in_server_mode(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch)
    client = module.app.test_client()
    login_as(module, client, "security_admin")

    assert client.post(
        "/api/server-backup/export", json={"passphrase": "correct passphrase"}
    ).status_code == 403
    assert client.post(
        "/api/server-backup/restore",
        data={"backup": (io.BytesIO(b"zip"), "backup.zip"), "passphrase": "secret"},
    ).status_code == 403


def test_restore_enforces_streamed_upload_limit(tmp_data_dir, monkeypatch):
    monkeypatch.setenv("CERTMON_MAX_BACKUP_UPLOAD_MB", "1")
    module = load_app(tmp_data_dir, monkeypatch)
    client = module.app.test_client()
    login_as(module, client, "security_admin")

    response = client.post(
        "/api/server-backup/restore",
        data={
            "passphrase": "correct passphrase",
            "backup": (io.BytesIO(b"x" * (1024 * 1024 + 1)), "backup.zip"),
        },
        headers=auth_headers(client),
    )

    assert response.status_code == 413


def test_backup_audit_events_do_not_contain_passphrases_or_package_data(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch)
    client = module.app.test_client()
    login_as(module, client, "security_admin")
    secret = "unique-backup-passphrase"

    response = client.post(
        "/api/server-backup/export",
        json={"passphrase": secret},
        headers=auth_headers(client),
    )
    assert response.status_code == 200
    response.close()

    events = module.database.list_audit_events()
    backup_events = [event for event in events if event["event_type"].startswith("server_backup")]
    assert backup_events
    assert secret not in repr(backup_events)
    assert "recovery-package" not in repr(backup_events).lower()
    assert "ciphertext" not in repr(backup_events).lower()


def test_temporary_export_and_upload_files_are_cleaned_up(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch)
    client = module.app.test_client()
    login_as(module, client, "security_admin")
    headers = auth_headers(client)
    exported_path = None
    original_export = module.server_backup_service.export_package

    def track_export(passphrase, output_file):
        nonlocal exported_path
        exported_path = Path(output_file)
        return original_export(passphrase, output_file)

    monkeypatch.setattr(module.server_backup_service, "export_package", track_export)
    response = client.post(
        "/api/server-backup/export",
        json={"passphrase": "correct passphrase"},
        headers=headers,
    )
    assert response.status_code == 200
    response.get_data()
    response.close()
    assert exported_path is not None
    assert not exported_path.parent.exists()

    uploaded_path = None

    def reject_upload(package_file, *_args, **_kwargs):
        nonlocal uploaded_path
        uploaded_path = Path(package_file)
        raise module.ServerBackupPackageError("invalid package")

    monkeypatch.setattr(module.server_backup_service, "stage_restore", reject_upload)
    rejected = client.post(
        "/api/server-backup/restore",
        data={
            "passphrase": "correct passphrase",
            "backup": (io.BytesIO(b"invalid"), "backup.zip"),
        },
        headers=headers,
    )
    assert rejected.status_code == 400
    assert uploaded_path is not None
    assert not uploaded_path.exists()


def test_backup_upload_config_defaults_and_rejects_nonpositive_values(tmp_path, monkeypatch):
    monkeypatch.delenv("CERTMON_MAX_BACKUP_UPLOAD_MB", raising=False)
    config = resolve_runtime_config(
        frozen=False, executable=tmp_path / "certmon.exe", source_dir=tmp_path
    )
    assert config.max_backup_upload_bytes == 512 * 1024 * 1024

    monkeypatch.setenv("CERTMON_MAX_BACKUP_UPLOAD_MB", "0")
    with pytest.raises(ConfigError, match="greater than zero"):
        resolve_runtime_config(
            frozen=False, executable=tmp_path / "certmon.exe", source_dir=tmp_path
        )
