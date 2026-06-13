from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from certmon.artifacts import ArtifactStore
from certmon.db import Database
from certmon.external_ca import ExternalCAService
from certmon.renewals import RenewalService
from certmon.vault import MemoryKeyProtector, Vault


def make_services(tmp_path):
    database = Database(tmp_path / "certmon.db")
    database.initialize()
    vault = Vault(tmp_path / "vault", MemoryKeyProtector())
    vault.initialize()
    artifacts = ArtifactStore(tmp_path / "certificates", vault)
    return database, artifacts, RenewalService(database), ExternalCAService(
        database, artifacts
    )


def create_job(renewals, identifier="device.local"):
    return renewals.create_job(
        endpoint_host=identifier,
        endpoint_port=443,
        issuer_type="external_ca",
        identifiers=[identifier],
        profile="extron-rsa",
    )


def test_csr_creation_persists_across_service_restart(tmp_path):
    database, artifacts, renewals, service = make_services(tmp_path)
    job = create_job(renewals)

    artifact_name = service.create_csr_job(job["id"])

    assert artifact_name == "request.csr"
    assert database.get_job(job["id"])["state"] == "awaiting_external_ca"
    restarted = ExternalCAService(database, artifacts)
    csr = x509.load_pem_x509_csr(restarted.read_csr(job["id"]))
    assert csr.is_signature_valid
    assert csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "device.local"


def test_signed_csr_completion_links_certificate_and_removes_pending_key(tmp_path):
    database, artifacts, renewals, service = make_services(tmp_path)
    job = create_job(renewals)
    service.create_csr_job(job["id"])
    root_key, root = make_ca("Enterprise Root")
    service.import_trust_anchor("enterprise-root", root.public_bytes(serialization.Encoding.PEM))
    leaf = sign_csr(service.read_csr(job["id"]), root, root_key)

    certificate_id = service.complete_csr_job(
        job["id"],
        leaf.public_bytes(serialization.Encoding.PEM),
        root.public_bytes(serialization.Encoding.PEM),
        "enterprise-root",
    )

    updated = database.get_job(job["id"])
    assert updated["state"] == "issued"
    assert updated["certificate_id"] == certificate_id
    assert database.get_certificate(certificate_id)["trust_status"] == "explicit_private"
    assert artifacts.has_certificate(f"external-{job['id']}") is False
    with artifacts.materialize_private(certificate_id, "private-key.pem") as path:
        private_key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    assert private_key.public_key().public_numbers() == leaf.public_key().public_numbers()


def test_signed_completion_rejects_identifier_mismatch_without_writes(tmp_path):
    database, artifacts, renewals, service = make_services(tmp_path)
    job = create_job(renewals)
    service.create_csr_job(job["id"])
    root_key, root = make_ca("Private Root")
    wrong_csr_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_csr = make_csr("other.local", wrong_csr_key)
    leaf = sign_csr(wrong_csr.public_bytes(serialization.Encoding.PEM), root, root_key)

    with pytest.raises(ValueError, match="identifier_mismatch"):
        service.complete_csr_job(
            job["id"],
            leaf.public_bytes(serialization.Encoding.PEM),
            root.public_bytes(serialization.Encoding.PEM),
            None,
        )

    assert database.get_job(job["id"])["state"] == "awaiting_external_ca"
    assert artifacts.has_certificate(f"external-{job['id']}") is True


def test_import_existing_certificate_records_explicit_private_root(tmp_path):
    database, artifacts, renewals, service = make_services(tmp_path)
    job = create_job(renewals)
    root_key, root = make_ca("Customer Root")
    service.import_trust_anchor("customer-root", root.public_bytes(serialization.Encoding.PEM))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = sign_csr(
        make_csr("device.local", key).public_bytes(serialization.Encoding.PEM),
        root,
        root_key,
    )

    certificate_id = service.import_existing(
        job["id"],
        leaf.public_bytes(serialization.Encoding.PEM),
        root.public_bytes(serialization.Encoding.PEM),
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ),
        None,
        "customer-root",
    )

    assert database.get_job(job["id"])["state"] == "issued"
    assert database.get_certificate(certificate_id)["trust_status"] == "explicit_private"


def make_ca(common_name):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return key, certificate


def make_csr(common_name, key):
    return (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(common_name)]), critical=False
        )
        .sign(key, hashes.SHA256())
    )


def sign_csr(csr_pem, issuer, issuer_key):
    csr = x509.load_pem_x509_csr(csr_pem)
    now = datetime.now(timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(issuer.subject)
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    )
    for extension in csr.extensions:
        if not isinstance(extension.value, x509.BasicConstraints):
            builder = builder.add_extension(extension.value, extension.critical)
    return builder.sign(issuer_key, hashes.SHA256())
