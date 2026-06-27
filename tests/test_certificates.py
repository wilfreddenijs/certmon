from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from certmon.certificates import (
    build_csr,
    generate_private_key,
    serialize_private_key,
    validate_certificate_import,
)
from certmon.profiles import PROFILES


def test_extron_profile_generates_rsa_csr_with_expected_extensions():
    profile = PROFILES["extron-rsa"]
    key = generate_private_key(profile)
    csr = build_csr(key, ["device.local", "192.168.1.20"], profile)

    assert isinstance(key, rsa.RSAPrivateKey)
    assert key.key_size == 2048
    assert csr.is_signature_valid
    sans = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "device.local" in sans.get_values_for_type(x509.DNSName)
    assert "192.168.1.20" in [str(value) for value in sans.get_values_for_type(x509.IPAddress)]
    eku = csr.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert ExtendedKeyUsageOID.SERVER_AUTH in eku


def test_modern_profile_generates_p256_key_and_encrypted_serialization():
    key = generate_private_key(PROFILES["generic-ecdsa"])
    pem = serialize_private_key(key, passphrase="secret")

    assert isinstance(key, ec.EllipticCurvePrivateKey)
    assert key.curve.name == "secp256r1"
    with pytest.raises(TypeError):
        serialization.load_pem_private_key(pem, password=None)
    assert serialization.load_pem_private_key(pem, password=b"secret")


def test_import_validates_matching_key_chain_and_explicit_private_root():
    root_key, root = _make_ca("Private Root")
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = _make_leaf("device.example.com", leaf_key, root, root_key)

    result = validate_certificate_import(
        leaf.public_bytes(serialization.Encoding.PEM),
        serialize_private_key(leaf_key),
        chain_pem=root.public_bytes(serialization.Encoding.PEM),
        expected_identifiers=("device.example.com",),
        explicit_private_root=True,
    )

    assert result.cryptographically_valid is True
    assert result.trust_status == "explicit_private"
    assert result.errors == ()


def test_import_rejects_mismatched_private_key():
    root_key, root = _make_ca("Private Root")
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = _make_leaf("device.example.com", leaf_key, root, root_key)

    result = validate_certificate_import(
        leaf.public_bytes(serialization.Encoding.PEM),
        serialize_private_key(wrong_key),
        chain_pem=root.public_bytes(serialization.Encoding.PEM),
        expected_identifiers=("device.example.com",),
    )

    assert result.cryptographically_valid is False
    assert "private_key_mismatch" in result.errors


def test_import_classifies_configured_system_root():
    root_key, root = _make_ca("Public Root")
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = _make_leaf("device.example.com", leaf_key, root, root_key)

    result = validate_certificate_import(
        leaf.public_bytes(serialization.Encoding.PEM),
        serialize_private_key(leaf_key),
        chain_pem=root.public_bytes(serialization.Encoding.PEM),
        system_roots=(root,),
    )

    assert result.cryptographically_valid is True
    assert result.trust_status == "system"


def test_import_rejects_chain_that_exceeds_ca_path_length():
    root_key, root = _make_ca("Restricted Root", path_length=0)
    intermediate_key, intermediate = _make_ca(
        "Intermediate", issuer=root, issuer_key=root_key, path_length=0
    )
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = _make_leaf("device.example.com", leaf_key, intermediate, intermediate_key)

    result = validate_certificate_import(
        leaf.public_bytes(serialization.Encoding.PEM),
        serialize_private_key(leaf_key),
        chain_pem=(
            root.public_bytes(serialization.Encoding.PEM)
            + intermediate.public_bytes(serialization.Encoding.PEM)
        ),
    )

    assert result.cryptographically_valid is False
    assert "chain_path_length_exceeded" in result.errors


def _make_ca(common_name, *, issuer=None, issuer_key=None, path_length=1):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    issuer = issuer or type("SelfSigned", (), {"subject": name})()
    issuer_key = issuer_key or key
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(issuer.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=path_length), critical=True
        )
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
        .sign(issuer_key, hashes.SHA256())
    )
    return key, cert


def _make_leaf(common_name, key, issuer, issuer_key):
    now = datetime.now(timezone.utc)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(common_name)]), critical=False
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(issuer_key, hashes.SHA256())
    )
