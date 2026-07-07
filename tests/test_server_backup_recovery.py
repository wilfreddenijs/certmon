from certmon.auth import hash_password, hash_session_token
from certmon.audit import AuditService
from certmon.backup import BackupService
from certmon.db import Database


def test_backup_restore_preserves_server_auth_and_audit_metadata(tmp_path):
    data_dir = tmp_path / "data"
    db = Database(data_dir / "certmon.db")
    db.initialize()
    db.create_user(
        user_id="admin-1",
        username="admin",
        password_hash=hash_password("correct horse"),
        roles=["admin"],
    )
    db.create_session(
        token_hash=hash_session_token("session-token"),
        user_id="admin-1",
        expires_at="2099-01-01T00:00:00Z",
    )
    AuditService(db).record(
        "backup_test",
        user={"username": "admin"},
        source_ip="127.0.0.1",
        target="server-mode",
        details={"api_token": "secret-value"},
    )

    backup = BackupService(data_dir, db).create_backup(
        tmp_path / "backups",
        b"recovery-package",
    )
    restored_dir = BackupService(data_dir, db).restore_backup(
        backup.path,
        tmp_path / "restored",
        b"recovery-package",
        expected_backup_id=backup.backup_id,
    )
    restored = Database(restored_dir / "certmon.db")

    assert restored.get_user_by_username("admin")["roles"] == ["admin"]
    assert restored.get_session(hash_session_token("session-token"))["user_id"] == "admin-1"
    event = restored.list_audit_events()[0]
    assert event["event_type"] == "backup_test"
    assert event["username"] == "admin"
    assert event["details"]["api_token"] == "[redacted]"
