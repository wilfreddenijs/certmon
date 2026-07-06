import json

import pytest
from cryptography import x509

from certmon.local_ca import LocalCAService
from certmon.local_ca_backup import LocalCABackupError, LocalCABackupService
from tests.test_local_ca import make_service


def test_local_ca_backup_exports_encrypted_private_key_and_imports_into_new_store(tmp_path):
    database, store, service = make_service(tmp_path / "source")
    service.generate_ca()
    source_cert = store.read_public("local-ca", "certificate.pem")
    package = LocalCABackupService(database, store).export_package("correct horse battery staple")
    decoded = json.loads(package)

    assert decoded["format"] == "certmon-local-ca-backup"
    assert "BEGIN CERTIFICATE" in decoded["ca"]["certificate_pem"]
    assert "BEGIN PRIVATE KEY" not in package.decode("utf-8")
    assert "BEGIN RSA PRIVATE KEY" not in package.decode("utf-8")

    target_database, target_store, _ = make_service(tmp_path / "target")
    result = LocalCABackupService(target_database, target_store).import_package(
        package,
        "correct horse battery staple",
    )

    assert result["certificate_id"] == "local-ca"
    assert target_store.read_public("local-ca", "certificate.pem") == source_cert
    assert target_database.get_certificate("local-ca")["kind"] == "local_ca"
    with target_store.materialize_private("local-ca", "private-key.pem") as path:
        assert path.read_bytes().startswith(b"-----BEGIN")


def test_local_ca_backup_rejects_wrong_passphrase(tmp_path):
    database, store, service = make_service(tmp_path)
    service.generate_ca()
    package = LocalCABackupService(database, store).export_package("correct")

    target_database, target_store, _ = make_service(tmp_path / "target")
    with pytest.raises(LocalCABackupError, match="decrypt"):
        LocalCABackupService(target_database, target_store).import_package(package, "wrong")


def test_local_ca_backup_import_tolerates_prompt_whitespace_and_pem_line_endings(tmp_path):
    database, store, service = make_service(tmp_path / "source")
    service.generate_ca()
    package = LocalCABackupService(database, store).export_package(" extron ")
    payload = json.loads(package.decode("utf-8"))
    payload["ca"]["certificate_pem"] = payload["ca"]["certificate_pem"].replace("\n", "\r\n")
    transferred_package = json.dumps(payload).encode("utf-8")

    target_database, target_store, _ = make_service(tmp_path / "target")
    result = LocalCABackupService(target_database, target_store).import_package(
        transferred_package,
        "extron\r\n",
    )

    assert result["certificate_id"] == "local-ca"
    assert target_store.has_certificate("local-ca")


def test_local_ca_backup_import_tolerates_utf8_bom_package(tmp_path):
    database, store, service = make_service(tmp_path / "source")
    service.generate_ca()
    package = b"\xef\xbb\xbf" + LocalCABackupService(database, store).export_package("extron")

    target_database, target_store, _ = make_service(tmp_path / "target")
    result = LocalCABackupService(target_database, target_store).import_package(
        package,
        "extron",
    )

    assert result["certificate_id"] == "local-ca"
    assert target_store.has_certificate("local-ca")


def test_local_ca_backup_import_requires_replace_when_ca_exists(tmp_path):
    source_database, source_store, source_service = make_service(tmp_path / "source")
    source_service.generate_ca()
    package = LocalCABackupService(source_database, source_store).export_package("correct")

    target_database, target_store, target_service = make_service(tmp_path / "target")
    target_service.generate_ca()

    with pytest.raises(LocalCABackupError, match="already exists"):
        LocalCABackupService(target_database, target_store).import_package(package, "correct")


def test_local_ca_backup_replace_handles_half_existing_local_ca_state(tmp_path):
    source_database, source_store, source_service = make_service(tmp_path / "source")
    source_service.generate_ca()
    package = LocalCABackupService(source_database, source_store).export_package("correct")

    db_only_database, db_only_store, db_only_service = make_service(tmp_path / "db-only")
    db_only_service.generate_ca()
    db_only_store.delete_certificate_set("local-ca")

    result = LocalCABackupService(db_only_database, db_only_store).import_package(
        package,
        "correct",
        replace=True,
    )
    assert result["certificate_id"] == "local-ca"
    assert db_only_store.has_certificate("local-ca")

    artifact_only_database, artifact_only_store, artifact_only_service = make_service(
        tmp_path / "artifact-only"
    )
    artifact_only_service.generate_ca()
    artifact_only_database.delete_certificate("local-ca")

    result = LocalCABackupService(artifact_only_database, artifact_only_store).import_package(
        package,
        "correct",
        replace=True,
    )
    assert result["certificate_id"] == "local-ca"
    assert artifact_only_database.get_certificate("local-ca") is not None
    assert artifact_only_store.has_certificate("local-ca")


def test_local_ca_backup_replace_removes_old_local_ca_leaf_certificates(tmp_path):
    source_database, source_store, source_service = make_service(tmp_path / "source")
    source_service.generate_ca()
    package = LocalCABackupService(source_database, source_store).export_package("correct")

    target_database, target_store, target_service = make_service(tmp_path / "target")
    target_service.generate_ca()
    leaf_id = target_service.issue(
        identifiers=("10.0.0.10",),
        profile_name="extron-rsa",
        device_name="Old device",
    )["certificate_id"]
    assert target_store.has_certificate(leaf_id)

    LocalCABackupService(target_database, target_store).import_package(
        package,
        "correct",
        replace=True,
    )

    assert target_store.has_certificate("local-ca")
    assert not target_store.has_certificate(leaf_id)
    assert target_database.get_certificate(leaf_id) is None
    cert = x509.load_pem_x509_certificate(target_store.read_public("local-ca", "certificate.pem"))
    assert cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is True
