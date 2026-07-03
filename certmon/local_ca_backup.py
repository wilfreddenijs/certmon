import base64
import json
import os
from datetime import datetime, timezone

from cryptography import x509
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from certmon.local_ca import LocalCAService


PACKAGE_VERSION = 1
KDF_ITERATIONS = 390000


class LocalCABackupError(ValueError):
    pass


class LocalCABackupService:
    def __init__(self, database, artifacts):
        self.database = database
        self.artifacts = artifacts

    def export_package(self, passphrase):
        passphrase = _normalize_passphrase(passphrase)
        if not passphrase:
            raise LocalCABackupError("Passphrase is required")
        if not self.artifacts.has_certificate(LocalCAService.CA_CERTIFICATE_ID):
            raise LocalCABackupError("No Local CA exists")

        certificate_pem = self.artifacts.read_public(
            LocalCAService.CA_CERTIFICATE_ID, "certificate.pem"
        )
        with self.artifacts.materialize_private(
            LocalCAService.CA_CERTIFICATE_ID, "private-key.pem"
        ) as path:
            private_key_pem = path.read_bytes()

        certificate = x509.load_pem_x509_certificate(certificate_pem)
        _validate_ca_key_pair(certificate, private_key_pem)

        salt = os.urandom(16)
        nonce = os.urandom(12)
        key = _derive_key(passphrase, salt)
        encrypted_key = AESGCM(key).encrypt(nonce, private_key_pem, certificate_pem)
        package = {
            "format": "certmon-local-ca-backup",
            "version": PACKAGE_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "ca": {
                "certificate_pem": certificate_pem.decode("utf-8"),
                "fingerprint_sha256": certificate.fingerprint(hashes.SHA256()).hex(),
                "subject": certificate.subject.rfc4514_string(),
                "not_after": certificate.not_valid_after_utc.isoformat(),
            },
            "private_key": {
                "algorithm": "AES-256-GCM",
                "kdf": "PBKDF2-HMAC-SHA256",
                "iterations": KDF_ITERATIONS,
                "salt": _b64(salt),
                "nonce": _b64(nonce),
                "ciphertext": _b64(encrypted_key),
            },
        }
        return json.dumps(package, indent=2, sort_keys=True).encode("utf-8")

    def import_package(self, package_bytes, passphrase, *, replace=False):
        passphrase = _normalize_passphrase(passphrase)
        if not passphrase:
            raise LocalCABackupError("Passphrase is required")
        package = _load_package(package_bytes)
        certificate_pem = package["ca"]["certificate_pem"].encode("utf-8")
        encrypted = package["private_key"]
        private_key_pem = _decrypt_private_key(encrypted, passphrase, certificate_pem)

        certificate = x509.load_pem_x509_certificate(certificate_pem)
        _validate_ca_key_pair(certificate, private_key_pem)

        if self.artifacts.has_certificate(LocalCAService.CA_CERTIFICATE_ID):
            if not replace:
                raise LocalCABackupError("Local CA already exists")
            self._delete_existing_local_ca_material()

        metadata = {
            "kind": "local_ca",
            "subject": certificate.subject.rfc4514_string(),
            "not_after": certificate.not_valid_after_utc.isoformat(),
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "fingerprint_sha256": certificate.fingerprint(hashes.SHA256()).hex(),
        }
        self.artifacts.create_certificate_set(
            LocalCAService.CA_CERTIFICATE_ID,
            {"certificate.pem": certificate_pem},
            {"private-key.pem": private_key_pem},
            metadata,
        )
        self.database.put_certificate(LocalCAService.CA_CERTIFICATE_ID, metadata)
        return {
            "certificate_id": LocalCAService.CA_CERTIFICATE_ID,
            "fingerprint_sha256": metadata["fingerprint_sha256"],
            "not_after": metadata["not_after"],
        }

    def _delete_existing_local_ca_material(self):
        for cert in list(self.database.list_certificates()):
            if cert.get("id") == LocalCAService.CA_CERTIFICATE_ID or cert.get("issuer_type") == "local_ca":
                self.artifacts.delete_certificate_set(cert["id"])
                self.database.delete_certificate(cert["id"])


def _load_package(package_bytes):
    try:
        package = json.loads(package_bytes.decode("utf-8"))
    except Exception as exc:
        raise LocalCABackupError("Invalid Local CA backup package") from exc
    if package.get("format") != "certmon-local-ca-backup" or package.get("version") != PACKAGE_VERSION:
        raise LocalCABackupError("Unsupported Local CA backup package")
    try:
        package["ca"]["certificate_pem"]
        package["private_key"]["ciphertext"]
    except Exception as exc:
        raise LocalCABackupError("Incomplete Local CA backup package") from exc
    return package


def _decrypt_private_key(encrypted, passphrase, certificate_pem):
    try:
        key = _derive_key(passphrase, _unb64(encrypted["salt"]), encrypted["iterations"])
        nonce = _unb64(encrypted["nonce"])
        ciphertext = _unb64(encrypted["ciphertext"])
    except (KeyError, ValueError) as exc:
        raise LocalCABackupError("Incomplete Local CA backup package") from exc

    aesgcm = AESGCM(key)
    errors = []
    for aad in _certificate_aad_candidates(certificate_pem):
        try:
            return aesgcm.decrypt(nonce, ciphertext, aad)
        except InvalidTag as exc:
            errors.append(exc)
    raise LocalCABackupError(
        "Could not decrypt Local CA backup. Check the file and passphrase."
    ) from (errors[-1] if errors else None)


def _certificate_aad_candidates(certificate_pem):
    normalized_lf = certificate_pem.replace(b"\r\n", b"\n")
    normalized_crlf = normalized_lf.replace(b"\n", b"\r\n")
    candidates = []
    for value in (certificate_pem, normalized_lf, normalized_crlf, None):
        if value not in candidates:
            candidates.append(value)
    return candidates


def _validate_ca_key_pair(certificate, private_key_pem):
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

    try:
        key = serialization.load_pem_private_key(private_key_pem, password=None)
    except Exception as exc:
        raise LocalCABackupError("Backup private key is invalid") from exc
    if not _is_ca(certificate):
        raise LocalCABackupError("Backup certificate is not a CA certificate")
    challenge = b"certmon-local-ca-backup-key-check"
    public_key = certificate.public_key()
    if isinstance(key, rsa.RSAPrivateKey):
        signature = key.sign(challenge, padding.PKCS1v15(), hashes.SHA256())
        try:
            public_key.verify(signature, challenge, padding.PKCS1v15(), hashes.SHA256())
        except InvalidSignature as exc:
            raise LocalCABackupError("Backup certificate and private key do not match") from exc
        return
    if isinstance(key, ec.EllipticCurvePrivateKey):
        signature = key.sign(challenge, ec.ECDSA(hashes.SHA256()))
        try:
            public_key.verify(signature, challenge, ec.ECDSA(hashes.SHA256()))
        except InvalidSignature as exc:
            raise LocalCABackupError("Backup certificate and private key do not match") from exc
        return
    raise LocalCABackupError("Unsupported Local CA private key type")


def _is_ca(certificate):
    try:
        return certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    except x509.ExtensionNotFound:
        return False


def _derive_key(passphrase, salt, iterations=KDF_ITERATIONS):
    return PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=int(iterations),
    ).derive(passphrase.encode("utf-8"))


def _normalize_passphrase(passphrase):
    if passphrase is None:
        return ""
    return str(passphrase).strip()


def _b64(value):
    return base64.b64encode(value).decode("ascii")


def _unb64(value):
    return base64.b64decode(value.encode("ascii"))
