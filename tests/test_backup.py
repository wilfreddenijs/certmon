import json

import pytest

from certmon.backup import BackupError, BackupService
from certmon.db import Database
from certmon.vault import MemoryKeyProtector, Vault


def make_installation(tmp_path):
    data_dir = tmp_path / "data"
    database = Database(data_dir / "certmon.db")
    database.initialize()
    database.put_certificate("cert-1", {"kind": "leaf", "identifiers": ["device.local"]})
    vault = Vault(data_dir / "secrets", MemoryKeyProtector())
    vault.initialize()
    recovery_package = vault.create_recovery_package("backup passphrase")
    certificate_dir = data_dir / "certificates" / "cert-1"
    certificate_dir.mkdir(parents=True)
    (certificate_dir / "certificate.pem").write_bytes(b"public")
    (certificate_dir / "private-key.pem.enc").write_bytes(b"encrypted-private")
    return data_dir, database, recovery_package


def test_backup_uses_online_sqlite_copy_and_preserves_encrypted_artifacts(tmp_path):
    data_dir, database, recovery_package = make_installation(tmp_path)

    result = BackupService(data_dir, database).create_backup(
        tmp_path / "backups", recovery_package
    )
    database.put_certificate("cert-2", {"kind": "leaf", "identifiers": ["new.local"]})
    (data_dir / "certificates/cert-1/private-key.pem.enc").write_bytes(b"changed-live")

    backup_db = Database(result.path / "certmon.db")
    assert backup_db.get_certificate("cert-1")["identifiers"] == ["device.local"]
    assert backup_db.get_certificate("cert-2") is None
    assert (result.path / "certificates/cert-1/private-key.pem.enc").read_bytes() == b"encrypted-private"


def test_restore_verifies_manifest_and_writes_only_to_new_directory(tmp_path):
    data_dir, database, recovery_package = make_installation(tmp_path)
    service = BackupService(data_dir, database)
    backup = service.create_backup(tmp_path / "backups", recovery_package)
    restore_dir = tmp_path / "restored"

    restored = service.restore_backup(
        backup.path,
        restore_dir,
        recovery_package,
        expected_backup_id=backup.backup_id,
    )

    assert restored == restore_dir
    assert (restore_dir / "certmon.db").is_file()
    assert (restore_dir / "certificates/cert-1/private-key.pem.enc").is_file()
    assert data_dir != restore_dir


def test_restore_rejects_hash_mismatch(tmp_path):
    data_dir, database, recovery_package = make_installation(tmp_path)
    service = BackupService(data_dir, database)
    backup = service.create_backup(tmp_path / "backups", recovery_package)
    (backup.path / "certificates/cert-1/private-key.pem.enc").write_bytes(b"tampered")

    with pytest.raises(BackupError, match="hash mismatch"):
        service.restore_backup(backup.path, tmp_path / "restored", recovery_package)


def test_restore_rejects_wrong_recovery_package_and_backup_id(tmp_path):
    data_dir, database, recovery_package = make_installation(tmp_path)
    service = BackupService(data_dir, database)
    backup = service.create_backup(tmp_path / "backups", recovery_package)

    with pytest.raises(BackupError, match="recovery package"):
        service.restore_backup(backup.path, tmp_path / "wrong-package", b"wrong")
    with pytest.raises(BackupError, match="backup ID"):
        service.restore_backup(
            backup.path,
            tmp_path / "wrong-id",
            recovery_package,
            expected_backup_id="another-backup",
        )


def test_restore_rejects_representative_key_fingerprint_mismatch(tmp_path):
    data_dir, database, recovery_package = make_installation(tmp_path)
    service = BackupService(data_dir, database)
    backup = service.create_backup(tmp_path / "backups", recovery_package)
    manifest_path = backup.path / "manifest.json"
    envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
    envelope["manifest"]["representative_key_fingerprint"] = "00" * 32
    envelope["hmac"] = service.sign_manifest(envelope["manifest"], recovery_package)
    manifest_path.write_text(json.dumps(envelope, sort_keys=True), encoding="utf-8")

    with pytest.raises(BackupError, match="key fingerprint"):
        service.restore_backup(backup.path, tmp_path / "restored", recovery_package)
