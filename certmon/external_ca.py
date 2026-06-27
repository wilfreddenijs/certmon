from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

from certmon.certificates import (
    build_csr,
    generate_private_key,
    serialize_private_key,
    validate_certificate_import,
)
from certmon.models import RenewalState, validate_transition
from certmon.naming import new_certificate_id
from certmon.permissions import Permission, authorize
from certmon.profiles import PROFILES


class ExternalCAService:
    def __init__(
        self,
        database,
        artifacts,
        *,
        system_roots=(),
        enterprise_roots=(),
    ):
        self.database = database
        self.artifacts = artifacts
        self.system_roots = tuple(system_roots)
        self.enterprise_roots = tuple(enterprise_roots)

    def create_csr_job(self, job_id):
        authorize(Permission.ISSUE_CERTIFICATE)
        job = self._job(job_id, state=RenewalState.DRAFT)
        profile = PROFILES[job["profile"]]
        key = generate_private_key(profile)
        csr = build_csr(key, job["identifiers"], profile)
        pending_id = self._pending_id(job_id)
        self.artifacts.create_certificate_set(
            pending_id,
            {"request.csr": csr.public_bytes(serialization.Encoding.PEM)},
            {"private-key.pem": serialize_private_key(key)},
            {"kind": "external_csr", "job_id": job_id},
        )
        try:
            self.database.transition_job(
                job_id,
                RenewalState.DRAFT.value,
                job["version"],
                RenewalState.AWAITING_EXTERNAL_CA.value,
                {},
            )
        except Exception:
            self.artifacts.delete_certificate_set(pending_id)
            raise
        return "request.csr"

    def read_csr(self, job_id):
        authorize(Permission.DOWNLOAD_PUBLIC_CERTIFICATE)
        return self.artifacts.read_public(self._pending_id(job_id), "request.csr")

    def import_trust_anchor(self, trust_anchor_id, certificate_pem):
        authorize(Permission.ISSUE_CERTIFICATE)
        certificate = x509.load_pem_x509_certificate(certificate_pem)
        constraints = certificate.extensions.get_extension_for_class(
            x509.BasicConstraints
        ).value
        if not constraints.ca:
            raise ValueError("Trust anchor must be a CA certificate")
        metadata = {"kind": "trust_anchor", "subject": certificate.subject.rfc4514_string()}
        self.artifacts.create_certificate_set(
            trust_anchor_id,
            {"certificate.pem": certificate_pem},
            {},
            metadata,
        )
        try:
            self.database.put_certificate(trust_anchor_id, metadata)
        except Exception:
            self.artifacts.delete_certificate_set(trust_anchor_id)
            raise
        return trust_anchor_id

    def complete_csr_job(
        self, job_id, leaf, chain=None, trust_anchor_id=None
    ):
        authorize(Permission.ISSUE_CERTIFICATE)
        job = self._job(job_id, state=RenewalState.AWAITING_EXTERNAL_CA)
        pending_id = self._pending_id(job_id)
        with self.artifacts.materialize_private(pending_id, "private-key.pem") as path:
            private_key = path.read_bytes()
        return self._complete(
            job,
            leaf,
            chain,
            private_key,
            None,
            trust_anchor_id,
            pending_id=pending_id,
        )

    def import_existing(
        self,
        job_id,
        leaf,
        chain,
        private_key,
        passphrase,
        trust_anchor_id,
    ):
        authorize(Permission.ISSUE_CERTIFICATE)
        job = self._job(job_id, state=RenewalState.DRAFT)
        return self._complete(
            job,
            leaf,
            chain,
            private_key,
            passphrase,
            trust_anchor_id,
        )

    def _complete(
        self,
        job,
        leaf,
        chain,
        private_key,
        passphrase,
        trust_anchor_id,
        *,
        pending_id=None,
    ):
        trust_anchor = self._load_trust_anchor(trust_anchor_id)
        validation_chain = _append_anchor(chain, trust_anchor)
        validation = validate_certificate_import(
            leaf,
            private_key,
            chain_pem=validation_chain,
            passphrase=passphrase,
            expected_identifiers=job["identifiers"],
            system_roots=self.system_roots,
            enterprise_roots=self.enterprise_roots,
            explicit_private_roots=(trust_anchor,) if trust_anchor else (),
        )
        if not validation.cryptographically_valid:
            raise ValueError(",".join(validation.errors))
        certificate_id = new_certificate_id(
            identifiers=job["identifiers"],
            profile=job["profile"],
            issuer_type="external-ca",
        )
        leaf_certificate = validation.ordered_chain[0]
        ordered_chain = b"".join(
            certificate.public_bytes(serialization.Encoding.PEM)
            for certificate in validation.ordered_chain[1:]
        )
        key = serialization.load_pem_private_key(
            private_key,
            password=passphrase.encode("utf-8") if passphrase else None,
        )
        plain_key = serialize_private_key(key)
        metadata = {
            "kind": "leaf",
            "issuer_type": "external_ca",
            "profile": job["profile"],
            "identifiers": list(job["identifiers"]),
            "trust_status": validation.trust_status,
            "trust_anchor_id": trust_anchor_id,
            "not_after": leaf_certificate.not_valid_after_utc.isoformat(),
        }
        public_files = {"certificate.pem": leaf}
        if ordered_chain:
            public_files["chain.pem"] = ordered_chain
        self.artifacts.create_certificate_set(
            certificate_id,
            public_files,
            {
                "private-key.pem": plain_key,
                "combined.pem": leaf + ordered_chain + plain_key,
            },
            metadata,
        )
        try:
            validate_transition(job["state"], RenewalState.ISSUED)
            self.database.complete_job_with_certificate(
                job_id=job["id"],
                expected_state=job["state"],
                expected_version=job["version"],
                certificate_id=certificate_id,
                metadata=metadata,
            )
        except Exception:
            self.artifacts.delete_certificate_set(certificate_id)
            raise
        if pending_id:
            self.artifacts.delete_certificate_set(pending_id)
        return certificate_id

    def _load_trust_anchor(self, trust_anchor_id):
        if not trust_anchor_id:
            return None
        metadata = self.database.get_certificate(trust_anchor_id)
        if metadata is None or metadata.get("kind") != "trust_anchor":
            raise ValueError("Unknown trust anchor")
        return x509.load_pem_x509_certificate(
            self.artifacts.read_public(trust_anchor_id, "certificate.pem")
        )

    def _job(self, job_id, *, state):
        job = self.database.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if job["issuer_type"] != "external_ca":
            raise ValueError("Job is not an External CA renewal")
        if job["state"] != state.value:
            raise ValueError(f"Job must be in {state.value} state")
        return job

    @staticmethod
    def _pending_id(job_id):
        return f"external-{job_id}"


def _append_anchor(chain, trust_anchor):
    chain = chain or b""
    if trust_anchor is None:
        return chain
    anchor_pem = trust_anchor.public_bytes(serialization.Encoding.PEM)
    if trust_anchor.fingerprint(hashes.SHA256()) in {
        certificate.fingerprint(hashes.SHA256())
        for certificate in _certificates(chain)
    }:
        return chain
    return chain + anchor_pem


def _certificates(pem):
    if not pem:
        return ()
    return tuple(x509.load_pem_x509_certificates(pem))
