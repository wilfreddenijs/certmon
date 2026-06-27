from datetime import timedelta

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from certmon.artifacts import ArtifactStore
from certmon.db import Database
from certmon.local_ca import LocalCAService
from certmon.vault import MemoryKeyProtector, Vault


def make_service(tmp_path):
    database = Database(tmp_path / "certmon.db")
    database.initialize()
    vault = Vault(tmp_path / "vault", MemoryKeyProtector())
    vault.initialize()
    store = ArtifactStore(tmp_path / "certificates", vault)
    return database, store, LocalCAService(
        database,
        store,
        ca_key_factory=lambda: rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        ),
    )


def test_generate_ca_creates_ten_year_encrypted_ca(tmp_path):
    database, store, service = make_service(tmp_path)

    result = service.generate_ca()

    assert result == {"certificate_id": "local-ca"}
    cert = x509.load_pem_x509_certificate(
        store.read_public("local-ca", "certificate.pem")
    )
    assert isinstance(cert.public_key(), rsa.RSAPublicKey)
    assert cert.public_key().key_size == 2048
    assert LocalCAService.CA_KEY_SIZE == 4096
    assert timedelta(days=3649) < cert.not_valid_after_utc - cert.not_valid_before_utc
    assert database.get_certificate("local-ca")["kind"] == "local_ca"
    with store.materialize_private("local-ca", "private-key.pem") as path:
        assert serialization.load_pem_private_key(path.read_bytes(), password=None)


def test_issue_extron_leaf_preserves_profile_and_combined_pem_order(tmp_path):
    database, store, service = make_service(tmp_path)
    service.generate_ca()

    result = service.issue(
        identifiers=("device.local", "192.168.1.20"),
        profile_name="extron-rsa",
        device_name="Extron Room 1",
    )

    assert set(result) == {"certificate_id", "not_after"}
    certificate_id = result["certificate_id"]
    assert certificate_id.startswith("extron-room-1-device.local-local-ca-extron-rsa-")
    leaf = x509.load_pem_x509_certificate(
        store.read_public(certificate_id, "certificate.pem")
    )
    sans = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "device.local" in sans.get_values_for_type(x509.DNSName)
    assert "192.168.1.20" in [
        str(value) for value in sans.get_values_for_type(x509.IPAddress)
    ]
    assert timedelta(days=824) < leaf.not_valid_after_utc - leaf.not_valid_before_utc
    assert leaf.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)
    usage = leaf.extensions.get_extension_for_class(x509.KeyUsage).value
    assert usage.digital_signature
    assert usage.content_commitment
    assert usage.key_encipherment
    assert usage.data_encipherment
    assert database.get_certificate(certificate_id)["profile"] == "extron-rsa"

    with store.materialize_private(certificate_id, "combined.pem") as path:
        combined = path.read_bytes()
    assert combined.startswith(b"-----BEGIN CERTIFICATE-----")
    assert combined.find(b"-----BEGIN RSA PRIVATE KEY-----") > combined.find(
        b"-----END CERTIFICATE-----"
    )
