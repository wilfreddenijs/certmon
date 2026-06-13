import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization


@dataclass(frozen=True)
class CAMigrationResult:
    ca_certificate_id: str
    imported_certificate_ids: tuple[str, ...]
    backup_path: Path


class LegacyCAMigrator:
    def __init__(self, legacy_dir: Path, artifact_store):
        self.legacy_dir = Path(legacy_dir)
        self.artifact_store = artifact_store

    def migrate(self):
        if self.artifact_store.has_certificate("local-ca"):
            raise FileExistsError("Local CA has already been migrated")
        ca_cert_path = self.legacy_dir / "certmon-ca.crt"
        ca_key_path = self.legacy_dir / "certmon-ca.key"
        if not ca_cert_path.exists() or not ca_key_path.exists():
            raise FileNotFoundError("Legacy CertMon CA certificate and key are required")

        ca_cert_pem = ca_cert_path.read_bytes()
        ca_key_pem = ca_key_path.read_bytes()
        ca_cert, ca_key = _load_matching_pair(ca_cert_pem, ca_key_pem)

        leaf_sets = []
        for cert_path in sorted(self.legacy_dir.glob("*.crt")):
            if cert_path.name == "certmon-ca.crt":
                continue
            key_path = cert_path.with_suffix(".key")
            if not key_path.exists():
                continue
            cert_pem = cert_path.read_bytes()
            key_pem = key_path.read_bytes()
            cert, _ = _load_matching_pair(cert_pem, key_pem)
            combined_path = cert_path.with_suffix(".pem")
            combined = (
                combined_path.read_bytes()
                if combined_path.exists()
                else cert_pem + key_pem
            )
            leaf_sets.append(
                (
                    _certificate_id(cert, cert_path.stem),
                    cert_pem,
                    key_pem,
                    combined,
                    cert,
                )
            )

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = self.legacy_dir.with_name(
            f"{self.legacy_dir.name}.migration-backup-{timestamp}"
        )
        shutil.copytree(self.legacy_dir, backup_path)

        self.artifact_store.create_certificate_set(
            "local-ca",
            {"certificate.pem": ca_cert_pem},
            {"private-key.pem": ca_key_pem},
            _metadata(ca_cert, profile="local-ca", legacy_source=str(self.legacy_dir)),
        )
        imported = []
        for certificate_id, cert_pem, key_pem, combined, cert in leaf_sets:
            self.artifact_store.create_certificate_set(
                certificate_id,
                {"certificate.pem": cert_pem},
                {"private-key.pem": key_pem, "combined.pem": combined},
                _metadata(
                    cert,
                    profile="extron-rsa",
                    legacy_source=str(self.legacy_dir),
                ),
            )
            imported.append(certificate_id)

        return CAMigrationResult("local-ca", tuple(imported), backup_path)


def _load_matching_pair(cert_pem, key_pem):
    cert = x509.load_pem_x509_certificate(cert_pem)
    key = serialization.load_pem_private_key(key_pem, password=None)
    cert_public = cert.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_public = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if cert_public != key_public:
        raise ValueError("Certificate does not match private key")
    return cert, key


def _certificate_id(cert, fallback):
    try:
        common_name = cert.subject.get_attributes_for_oid(
            x509.NameOID.COMMON_NAME
        )[0].value
    except (IndexError, AttributeError):
        common_name = fallback
    value = re.sub(r"[^a-z0-9]+", "-", common_name.lower()).strip("-")
    return value or fallback.lower().replace("_", "-")


def _metadata(cert, *, profile, legacy_source):
    return {
        "profile": profile,
        "subject": cert.subject.rfc4514_string(),
        "issuer": cert.issuer.rfc4514_string(),
        "serial": str(cert.serial_number),
        "not_before": cert.not_valid_before_utc.isoformat(),
        "not_after": cert.not_valid_after_utc.isoformat(),
        "legacy_source": legacy_source,
    }
