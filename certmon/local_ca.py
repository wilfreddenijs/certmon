import ipaddress
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from certmon.certificates import generate_private_key, serialize_private_key
from certmon.naming import new_certificate_id
from certmon.profiles import PROFILES


class LocalCAService:
    CA_CERTIFICATE_ID = "local-ca"
    CA_KEY_SIZE = 4096

    def __init__(self, database, artifacts, ca_key_factory=None):
        self.database = database
        self.artifacts = artifacts
        self.ca_key_factory = ca_key_factory or self._generate_ca_key

    def generate_ca(self):
        if self.artifacts.has_certificate(self.CA_CERTIFICATE_ID):
            raise FileExistsError("Local CA already exists")
        key = self.ca_key_factory()
        now = datetime.now(timezone.utc)
        subject = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, "CertMon Local CA"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CertMon"),
                x509.NameAttribute(NameOID.COUNTRY_NAME, "NL"),
            ]
        )
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=None), critical=True
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
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        metadata = {
            "kind": "local_ca",
            "subject": "CertMon Local CA",
            "not_after": certificate.not_valid_after_utc.isoformat(),
        }
        self._store_certificate(
            self.CA_CERTIFICATE_ID,
            {"certificate.pem": certificate.public_bytes(serialization.Encoding.PEM)},
            {"private-key.pem": serialize_private_key(key)},
            metadata,
        )
        return {"certificate_id": self.CA_CERTIFICATE_ID}

    def issue(self, *, identifiers, profile_name, device_name=None):
        profile = PROFILES[profile_name]
        ca_key, ca_certificate = self._load_ca()
        key = generate_private_key(profile)
        now = datetime.now(timezone.utc)
        sans = [_general_name(value) for value in identifiers]
        certificate = (
            x509.CertificateBuilder()
            .subject_name(
                x509.Name(
                    [
                        x509.NameAttribute(NameOID.COMMON_NAME, identifiers[0]),
                        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CertMon"),
                    ]
                )
            )
            .issuer_name(ca_certificate.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None), critical=True
            )
            .add_extension(_key_usage(profile), critical=True)
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
                critical=False,
            )
            .add_extension(_authority_key_identifier(ca_certificate), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        certificate_id = new_certificate_id(
            identifiers=identifiers,
            profile=profile_name,
            device_name=device_name or identifiers[0],
            issuer_type="local-ca",
        )
        certificate_pem = certificate.public_bytes(serialization.Encoding.PEM)
        private_key_pem = serialize_private_key(key)
        metadata = {
            "kind": "leaf",
            "issuer_type": "local_ca",
            "profile": profile_name,
            "device_name": device_name or identifiers[0],
            "identifiers": list(identifiers),
            "not_after": certificate.not_valid_after_utc.isoformat(),
        }
        self._store_certificate(
            certificate_id,
            {
                "certificate.pem": certificate_pem,
                "chain.pem": ca_certificate.public_bytes(serialization.Encoding.PEM),
            },
            {
                "private-key.pem": private_key_pem,
                "combined.pem": certificate_pem + private_key_pem,
            },
            metadata,
        )
        return {
            "certificate_id": certificate_id,
            "not_after": certificate.not_valid_after_utc.isoformat(),
        }

    def _load_ca(self):
        certificate = x509.load_pem_x509_certificate(
            self.artifacts.read_public(self.CA_CERTIFICATE_ID, "certificate.pem")
        )
        with self.artifacts.materialize_private(
            self.CA_CERTIFICATE_ID, "private-key.pem"
        ) as path:
            key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        return key, certificate

    def _generate_ca_key(self):
        return rsa.generate_private_key(
            public_exponent=65537, key_size=self.CA_KEY_SIZE
        )

    def _store_certificate(self, certificate_id, public_files, private_files, metadata):
        self.artifacts.create_certificate_set(
            certificate_id, public_files, private_files, metadata
        )
        try:
            self.database.put_certificate(certificate_id, metadata)
        except Exception:
            self.artifacts.delete_certificate_set(certificate_id)
            raise


def _general_name(value):
    try:
        return x509.IPAddress(ipaddress.ip_address(value))
    except ValueError:
        return x509.DNSName(value)


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


def _authority_key_identifier(ca_certificate):
    try:
        identifier = ca_certificate.extensions.get_extension_for_class(
            x509.SubjectKeyIdentifier
        ).value
        return x509.AuthorityKeyIdentifier(
            key_identifier=identifier.digest,
            authority_cert_issuer=[x509.DirectoryName(ca_certificate.subject)],
            authority_cert_serial_number=ca_certificate.serial_number,
        )
    except x509.ExtensionNotFound:
        return x509.AuthorityKeyIdentifier.from_issuer_public_key(
            ca_certificate.public_key()
        )
