import json
import zipfile

import pytest

from certmon.db import Database
from certmon.server_backup import (
    ServerBackupConflictError,
    ServerBackupPackageError,
    ServerBackupPackageService,
)
from certmon.vault import MemoryKeyProtector, Vault


def make_service(tmp_path, *, runtime_protector=None):
    data_dir = tmp_path / "active"
    database = Database(data_dir / "certmon.db")
    database.initialize()
    database.put_certificate("cert-1", {"identifiers": ["device.local"]})
    source_protector = MemoryKeyProtector(b"source-account")
    vault = Vault(data_dir / "secrets", source_protector)
    vault.initialize()
    encrypted = vault.encrypt(b"private-value", purpose="certificate-artifact:cert-1:private-key.pem")
    certificate_dir = data_dir / "certificates" / "cert-1"
    certificate_dir.mkdir(parents=True)
    (certificate_dir / "private-key.pem.enc").write_bytes(encrypted.ciphertext)
    runtime_protector = runtime_protector or MemoryKeyProtector(b"destination-account")
    return (
        ServerBackupPackageService(
            data_dir, database, vault, runtime_protector
        ),
        data_dir,
        runtime_protector,
    )


def export_package(tmp_path):
    service, data_dir, protector = make_service(tmp_path)
    package = tmp_path / "server-backup.zip"
    result = service.export_package("correct passphrase", package)
    return service, data_dir, protector, package, result


def rewrite_archive(package, mutate):
    with zipfile.ZipFile(package, "r") as source:
        members = [(info, source.read(info)) for info in source.infolist()]
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for info, content in members:
            name, content = mutate(info.filename, content)
            target.writestr(name, content)


def test_export_has_only_versioned_encrypted_layout(tmp_path):
    _, _, _, package, result = export_package(tmp_path)

    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        recovery = json.loads(archive.read("recovery-package.json"))
        all_content = b"".join(archive.read(name) for name in names)

    assert result.path == package
    assert {"backup/manifest.json", "backup/certmon.db", "recovery-package.json", "README.txt"} <= names
    assert all(name in {"recovery-package.json", "README.txt"} or name.startswith("backup/") for name in names)
    assert recovery["ciphertext"]
    assert b"private-value" not in all_content


def test_valid_package_stages_sibling_and_reprotects_vault(tmp_path):
    service, data_dir, protector, package, exported = export_package(tmp_path)
    before = {path.relative_to(data_dir): path.read_bytes() for path in data_dir.rglob("*") if path.is_file()}

    restored = service.stage_restore(package, "correct passphrase", data_dir.parent)

    assert restored.backup_id == exported.backup_id
    assert restored.staged_path.parent == data_dir.parent
    assert restored.staged_path != data_dir
    assert Database(restored.staged_path / "certmon.db").get_certificate("cert-1")
    Vault(restored.staged_path / "secrets", protector).initialize()
    after = {path.relative_to(data_dir): path.read_bytes() for path in data_dir.rglob("*") if path.is_file()}
    assert before == after


@pytest.mark.parametrize(
    "mutation",
    [
        lambda name, content: ("../escape.txt", content) if name == "README.txt" else (name, content),
        lambda name, content: ("unexpected.txt", content) if name == "README.txt" else (name, content),
        lambda name, content: (name, b"tampered") if name.endswith("private-key.pem.enc") else (name, content),
    ],
)
def test_restore_rejects_unsafe_or_tampered_archives_without_final_directory(tmp_path, mutation):
    service, data_dir, _, package, exported = export_package(tmp_path)
    rewrite_archive(package, mutation)
    final_path = data_dir.parent / f"{data_dir.name}-restore-{exported.backup_id}"

    with pytest.raises(ServerBackupPackageError):
        service.stage_restore(package, "correct passphrase", data_dir.parent)

    assert not final_path.exists()


def test_restore_rejects_wrong_passphrase_and_existing_destination(tmp_path):
    service, data_dir, _, package, exported = export_package(tmp_path)
    final_path = data_dir.parent / f"{data_dir.name}-restore-{exported.backup_id}"

    with pytest.raises(ServerBackupPackageError):
        service.stage_restore(package, "wrong passphrase", data_dir.parent)
    assert not final_path.exists()

    final_path.mkdir()
    with pytest.raises(ServerBackupConflictError):
        service.stage_restore(package, "correct passphrase", data_dir.parent)
    assert list(final_path.iterdir()) == []


def test_restore_rejects_declared_archive_bomb(tmp_path, monkeypatch):
    service, data_dir, _, package, exported = export_package(tmp_path)
    monkeypatch.setattr(service, "MAX_UNCOMPRESSED_BYTES", 1)

    with pytest.raises(ServerBackupPackageError, match="too large"):
        service.stage_restore(package, "correct passphrase", data_dir.parent)

    assert not (data_dir.parent / f"{data_dir.name}-restore-{exported.backup_id}").exists()
