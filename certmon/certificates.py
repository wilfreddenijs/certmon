import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, ed448, padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


@dataclass(frozen=True)
class ChainValidation:
    cryptographically_valid: bool
    trust_status: Literal["system", "enterprise", "explicit_private", "untrusted"]
    ordered_chain: tuple[x509.Certificate, ...]
    errors: tuple[str, ...]


def generate_private_key(profile):
    if profile.key_type == "rsa":
        return rsa.generate_private_key(
            public_exponent=65537, key_size=profile.key_size
        )
    if profile.key_type == "ecdsa" and profile.curve == "secp256r1":
        return ec.generate_private_key(ec.SECP256R1())
    raise ValueError(f"Unsupported certificate profile: {profile.name}")


def build_csr(key, identifiers, profile):
    if not identifiers:
        raise ValueError("At least one identifier is required")
    san_values = []
    for value in identifiers:
        try:
            san_values.append(x509.IPAddress(ipaddress.ip_address(value)))
        except ValueError:
            san_values.append(x509.DNSName(value))
    builder = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, identifiers[0])])
        )
        .add_extension(x509.SubjectAlternativeName(san_values), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(_key_usage(profile), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
    )
    return builder.sign(key, hashes.SHA256())


def serialize_private_key(key, passphrase=None):
    encryption = (
        serialization.BestAvailableEncryption(passphrase.encode("utf-8"))
        if passphrase
        else serialization.NoEncryption()
    )
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        encryption,
    )


def validate_certificate_import(
    leaf_pem,
    private_key_pem,
    *,
    chain_pem=None,
    passphrase=None,
    expected_identifiers=(),
    system_roots=(),
    enterprise_roots=(),
    explicit_private_roots=(),
    explicit_private_root=False,
):
    errors = []
    leaf = x509.load_pem_x509_certificate(leaf_pem)
    password = passphrase.encode("utf-8") if passphrase else None
    key = serialization.load_pem_private_key(private_key_pem, password=password)
    if _public_bytes(leaf.public_key()) != _public_bytes(key.public_key()):
        errors.append("private_key_mismatch")

    now = datetime.now(timezone.utc)
    if leaf.not_valid_before_utc > now:
        errors.append("certificate_not_yet_valid")
    if leaf.not_valid_after_utc <= now:
        errors.append("certificate_expired")
    try:
        if leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            errors.append("leaf_is_ca")
    except x509.ExtensionNotFound:
        pass

    actual_identifiers = _identifiers(leaf)
    if expected_identifiers and not set(expected_identifiers).issubset(actual_identifiers):
        errors.append("identifier_mismatch")

    supplied = _load_certificates(chain_pem or b"")
    ordered = _order_chain(leaf, supplied)
    if supplied and len(ordered) != len(supplied) + 1:
        errors.append("chain_incomplete")
    for index in range(len(ordered) - 1):
        child, issuer = ordered[index], ordered[index + 1]
        if child.issuer != issuer.subject:
            errors.append("chain_issuer_mismatch")
            break
        if not _verify_signature(child, issuer.public_key()):
            errors.append("chain_signature_invalid")
            break
        if issuer.not_valid_before_utc > now or issuer.not_valid_after_utc <= now:
            errors.append("chain_certificate_invalid_time")
        try:
            constraints = issuer.extensions.get_extension_for_class(
                x509.BasicConstraints
            ).value
            if not constraints.ca:
                errors.append("chain_issuer_not_ca")
            elif constraints.path_length is not None:
                subordinate_ca_count = sum(
                    _is_ca(cert) for cert in ordered[1 : index + 1]
                )
                if subordinate_ca_count > constraints.path_length:
                    errors.append("chain_path_length_exceeded")
        except x509.ExtensionNotFound:
            errors.append("chain_issuer_missing_ca_constraint")
        try:
            usage = issuer.extensions.get_extension_for_class(x509.KeyUsage).value
            if not usage.key_cert_sign:
                errors.append("chain_issuer_cannot_sign")
        except x509.ExtensionNotFound:
            pass

    root = ordered[-1] if len(ordered) > 1 else None
    system_fingerprints = {
        cert.fingerprint(hashes.SHA256()) for cert in system_roots
    }
    enterprise_fingerprints = {
        cert.fingerprint(hashes.SHA256()) for cert in enterprise_roots
    }
    explicit_private_fingerprints = {
        cert.fingerprint(hashes.SHA256()) for cert in explicit_private_roots
    }
    if root is not None and root.fingerprint(hashes.SHA256()) in system_fingerprints:
        trust_status = "system"
    elif root is not None and root.fingerprint(hashes.SHA256()) in enterprise_fingerprints:
        trust_status = "enterprise"
    elif root is not None and (
        root.fingerprint(hashes.SHA256()) in explicit_private_fingerprints
        or explicit_private_root
    ):
        trust_status = "explicit_private"
    else:
        trust_status = "untrusted"

    return ChainValidation(
        cryptographically_valid=not errors,
        trust_status=trust_status,
        ordered_chain=tuple(ordered),
        errors=tuple(dict.fromkeys(errors)),
    )


def _key_usage(profile):
    names = profile.key_usage
    return x509.KeyUsage(
        digital_signature="digital_signature" in names,
        content_commitment="content_commitment" in names,
        key_encipherment="key_encipherment" in names,
        data_encipherment="data_encipherment" in names,
        key_agreement="key_agreement" in names,
        key_cert_sign=False,
        crl_sign=False,
        encipher_only=False,
        decipher_only=False,
    )


def _public_bytes(key):
    return key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _identifiers(cert):
    values = set()
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        values.update(san.get_values_for_type(x509.DNSName))
        values.update(str(value) for value in san.get_values_for_type(x509.IPAddress))
    except x509.ExtensionNotFound:
        pass
    try:
        values.add(cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value)
    except IndexError:
        pass
    return values


def _is_ca(cert):
    try:
        return cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    except x509.ExtensionNotFound:
        return False


def _load_certificates(pem):
    blocks = re.findall(
        b"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
        pem,
        flags=re.DOTALL,
    )
    return [x509.load_pem_x509_certificate(block) for block in blocks]


def _order_chain(leaf, supplied):
    ordered = [leaf]
    remaining = list(supplied)
    while remaining:
        match = next(
            (cert for cert in remaining if ordered[-1].issuer == cert.subject), None
        )
        if match is None:
            break
        ordered.append(match)
        remaining.remove(match)
        if match.subject == match.issuer:
            break
    return ordered


def _verify_signature(cert, public_key):
    try:
        if isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(
                cert.signature,
                cert.tbs_certificate_bytes,
                padding.PKCS1v15(),
                cert.signature_hash_algorithm,
            )
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(
                cert.signature,
                cert.tbs_certificate_bytes,
                ec.ECDSA(cert.signature_hash_algorithm),
            )
        elif isinstance(public_key, (ed25519.Ed25519PublicKey, ed448.Ed448PublicKey)):
            public_key.verify(cert.signature, cert.tbs_certificate_bytes)
        else:
            return False
        return True
    except Exception:
        return False
