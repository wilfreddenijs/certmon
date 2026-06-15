from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.x509.oid import NameOID

from certmon.artifacts import ArtifactStore
from certmon.ca_migration import LegacyCAMigrator, migrate_legacy_ca_if_present
from certmon.vault import MemoryKeyProtector, Vault


def _certificate(common_name, key, issuer_cert=None, issuer_key=None):
    now = datetime.now(timezone.utc)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    issuer_cert = issuer_cert or subject
    issuer_key = issuer_key or key
    issuer_name = issuer_cert.subject if hasattr(issuer_cert, "subject") else issuer_cert
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(
            x509.BasicConstraints(ca=issuer_cert == subject, path_length=None),
            critical=True,
        )
        .sign(issuer_key, None)
    )


def _write_key(path, key):
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


def test_migrates_ca_and_issued_certificate_without_removing_originals(tmp_path):
    legacy = tmp_path / "legacy-ca"
    legacy.mkdir()
    ca_key = ed25519.Ed25519PrivateKey.from_private_bytes(b"a" * 32)
    ca_cert = _certificate("CertMon Local CA", ca_key)
    leaf_key = ed25519.Ed25519PrivateKey.from_private_bytes(b"b" * 32)
    leaf_cert = _certificate("device.local", leaf_key, ca_cert, ca_key)
    (legacy / "certmon-ca.crt").write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    _write_key(legacy / "certmon-ca.key", ca_key)
    (legacy / "device_local.crt").write_bytes(leaf_cert.public_bytes(serialization.Encoding.PEM))
    _write_key(legacy / "device_local.key", leaf_key)
    (legacy / "device_local.pem").write_bytes(
        leaf_cert.public_bytes(serialization.Encoding.PEM)
        + leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    vault = Vault(tmp_path / "vault", MemoryKeyProtector())
    vault.initialize()
    store = ArtifactStore(tmp_path / "certificates", vault)

    result = LegacyCAMigrator(legacy, store).migrate()

    assert result.ca_certificate_id == "local-ca"
    assert result.imported_certificate_ids == ("device-local",)
    assert (legacy / "certmon-ca.key").exists()
    assert store.read_public("local-ca", "certificate.pem").startswith(b"-----BEGIN CERTIFICATE-----")
    with store.materialize_private("device-local", "private-key.pem") as key_path:
        assert key_path.read_bytes().startswith(b"-----BEGIN PRIVATE KEY-----")


def test_rejects_mismatched_certificate_and_key(tmp_path):
    legacy = tmp_path / "legacy-ca"
    legacy.mkdir()
    cert_key = ed25519.Ed25519PrivateKey.from_private_bytes(b"c" * 32)
    wrong_key = ed25519.Ed25519PrivateKey.from_private_bytes(b"d" * 32)
    cert = _certificate("CertMon Local CA", cert_key)
    (legacy / "certmon-ca.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _write_key(legacy / "certmon-ca.key", wrong_key)
    vault = Vault(tmp_path / "vault", MemoryKeyProtector())
    vault.initialize()

    try:
        LegacyCAMigrator(legacy, ArtifactStore(tmp_path / "certificates", vault)).migrate()
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("Expected mismatched key rejection")


def test_migrates_first_existing_legacy_ca_directory(tmp_path):
    missing = tmp_path / "missing-ca"
    legacy = tmp_path / "legacy-ca"
    legacy.mkdir()
    ca_key = ed25519.Ed25519PrivateKey.from_private_bytes(b"e" * 32)
    ca_cert = _certificate("CertMon Local CA", ca_key)
    (legacy / "certmon-ca.crt").write_bytes(
        ca_cert.public_bytes(serialization.Encoding.PEM)
    )
    _write_key(legacy / "certmon-ca.key", ca_key)
    vault = Vault(tmp_path / "vault", MemoryKeyProtector())
    vault.initialize()
    store = ArtifactStore(tmp_path / "certificates", vault)

    result = migrate_legacy_ca_if_present(store, (missing, legacy))

    assert result is not None
    assert result.ca_certificate_id == "local-ca"
    assert store.has_certificate("local-ca")


def test_legacy_ca_discovery_does_nothing_after_migration(tmp_path):
    legacy = tmp_path / "legacy-ca"
    legacy.mkdir()
    vault = Vault(tmp_path / "vault", MemoryKeyProtector())
    vault.initialize()
    store = ArtifactStore(tmp_path / "certificates", vault)
    store.create_certificate_set(
        "local-ca",
        {"certificate.pem": b"existing"},
        {"private-key.pem": b"existing-key"},
        {},
    )

    result = migrate_legacy_ca_if_present(store, (legacy,))

    assert result is None
    assert store.read_public("local-ca", "certificate.pem") == b"existing"
