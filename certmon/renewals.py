import ipaddress
import hashlib
import json
import uuid

from cryptography.hazmat.primitives import serialization

from certmon.acme_service import ACMEOrderError
from certmon.certificates import build_csr, generate_private_key, serialize_private_key, validate_certificate_import
from certmon.dns.base import DNSChallengeRecord, PresentedRecord
from certmon.dns.manual import ManualChallengeExpired
from certmon.models import RenewalState, validate_transition
from certmon.permissions import Permission, authorize
from certmon.profiles import PROFILES


class IdentifierError(ValueError):
    pass


class CertificateValidationError(ValueError):
    def __init__(self, errors):
        self.errors = tuple(errors)
        super().__init__(",".join(self.errors))


class StagingRequired(RuntimeError):
    code = "staging_required"

    def __init__(self, job_id):
        super().__init__("A successful staging issuance is required first")
        self.action_url = f"/api/renewals/staging-copy/{job_id}"


def normalize_identifiers(values, *, public_acme=False):
    normalized = []
    seen = set()
    for raw in values:
        value = (raw or "").strip().rstrip(".")
        if not value:
            continue
        wildcard = value.startswith("*.")
        name = value[2:] if wildcard else value
        try:
            ipaddress.ip_address(name)
        except ValueError:
            pass
        else:
            if public_acme:
                raise IdentifierError("Public ACME does not accept IP identifiers")
            canonical = name
            if canonical not in seen:
                normalized.append(canonical)
                seen.add(canonical)
            continue

        try:
            ascii_name = name.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise IdentifierError(f"Invalid DNS identifier: {value}") from exc
        if public_acme and (
            "." not in ascii_name
            or ascii_name.endswith(".local")
            or ascii_name == "localhost"
        ):
            raise IdentifierError(f"Identifier is not eligible for public ACME: {value}")
        canonical = f"*.{ascii_name}" if wildcard else ascii_name
        if canonical not in seen:
            normalized.append(canonical)
            seen.add(canonical)
    if not normalized:
        raise IdentifierError("At least one certificate identifier is required")
    return tuple(normalized)


class RenewalService:
    def __init__(self, database):
        self.database = database

    def create_job(
        self,
        *,
        endpoint_host,
        endpoint_port,
        issuer_type,
        identifiers,
        profile,
        environment=None,
        dns_provider=None,
        metadata=None,
    ):
        authorize(Permission.ISSUE_CERTIFICATE)
        normalized = normalize_identifiers(
            identifiers, public_acme=issuer_type == "acme"
        )
        job_id = str(uuid.uuid4())
        self.database.create_job(
            job_id=job_id,
            endpoint_host=endpoint_host,
            endpoint_port=int(endpoint_port),
            issuer_type=issuer_type,
            state=RenewalState.DRAFT.value,
            identifiers=normalized,
            profile=profile,
            environment=environment,
            dns_provider=dns_provider,
            metadata=metadata,
        )
        return self.database.get_job(job_id)

    def transition(self, job_id, expected_state, expected_version, new_state, updates=None):
        authorize(Permission.ISSUE_CERTIFICATE)
        validate_transition(expected_state, new_state)
        return self.database.transition_job(
            job_id,
            RenewalState(expected_state).value,
            expected_version,
            RenewalState(new_state).value,
            updates or {},
        )

    def cancel(self, job_id):
        authorize(Permission.ISSUE_CERTIFICATE)
        job = self.database.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if job["state"] == RenewalState.CANCELLED.value:
            return job
        return self.transition(
            job_id,
            RenewalState(job["state"]),
            job["version"],
            RenewalState.CANCELLED,
        )

    def delete_terminal_job(self, job_id):
        authorize(Permission.ISSUE_CERTIFICATE)
        job = self.database.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if (
            job["state"] == RenewalState.DRAFT.value
            and job.get("metadata", {}).get("external_ca_workflow") == "existing"
        ):
            self.database.delete_job(job_id)
            return job
        if job["state"] not in {
            RenewalState.CANCELLED.value,
            RenewalState.DEPLOYED.value,
            RenewalState.DEPLOYMENT_PENDING.value,
            RenewalState.FAILED.value,
            RenewalState.ISSUED.value,
        }:
            raise ValueError(
                "Only cancelled, failed, issued, deployed, or deployment-pending renewal entries can be deleted"
            )
        self.database.delete_job(job_id)
        return job

    def recover_interrupted_jobs(self, acme_service):
        paused = {
            RenewalState.AWAITING_DNS.value,
            RenewalState.AWAITING_EXTERNAL_CA.value,
        }
        active = {RenewalState.VALIDATING.value, RenewalState.ISSUING.value}
        for job in self.database.list_jobs():
            if job["state"] in paused:
                continue
            if job["state"] not in active or job["issuer_type"] != "acme":
                continue
            target, updates = acme_service.reconcile(job)
            self.transition(
                job["id"],
                RenewalState(job["state"]),
                job["version"],
                RenewalState(target),
                updates,
            )


class ACMERenewalOrchestrator:
    def __init__(
        self,
        database,
        renewal_service,
        account_service,
        order_service,
        artifacts,
        dns_providers,
    ):
        self.database = database
        self.renewals = renewal_service
        self.accounts = account_service
        self.orders = order_service
        self.artifacts = artifacts
        self.dns_providers = dict(dns_providers)

    def start_acme(self, job_id, *, email, terms_of_service_agreed):
        authorize(Permission.ISSUE_CERTIFICATE)
        job = self._job(job_id, RenewalState.DRAFT)
        identifier_hash = self.identifier_hash(job["identifiers"])
        if job["environment"] == "production" and self.database.get_setting(
            f"acme-staging-proof:{identifier_hash}"
        ) is None:
            raise StagingRequired(job_id)
        self.accounts.register(
            job["environment"],
            email=email,
            terms_of_service_agreed=terms_of_service_agreed,
        )
        csr_pem = self._ensure_pending_key_and_csr(job)
        order = self.orders.create_order(job_id, csr_pem)
        presented = self._present(job, order["dns_challenges"])
        job = self.renewals.transition(
            job_id,
            RenewalState.DRAFT,
            job["version"],
            RenewalState.AWAITING_DNS,
        )
        if job["dns_provider"] == "cloudflare":
            return self._complete_dns(job, presented)
        return {**job, "dns_records": self._public_records(presented)}

    def continue_manual_dns(self, job_id):
        authorize(Permission.ISSUE_CERTIFICATE)
        job = self._job(job_id, RenewalState.AWAITING_DNS)
        if job["dns_provider"] != "manual":
            raise ValueError("Job does not use manual DNS")
        provider = self._provider(job)
        presented = self._load_presented(job_id)
        try:
            visibility = provider.check_visibility(presented)
        except ManualChallengeExpired:
            replacement = self.orders.create_order(
                job_id,
                self.artifacts.read_public(self._pending_id(job_id), "request.csr"),
            )
            presented = self._present(job, replacement["dns_challenges"])
            return {
                **self.database.get_job(job_id),
                "dns_records": self._public_records(presented),
                "replaced": True,
            }
        if not all(result.visible for result in visibility):
            return {
                **job,
                "dns_records": self._public_records(presented),
                "visible": False,
            }
        return self._complete_dns(job, presented)

    def cancel(self, job_id):
        job = self.database.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        presented = self._load_presented(job_id, required=False)
        if presented:
            cleanup = self._provider(job).cleanup(presented)
            if cleanup.errors:
                self.database.put_setting(
                    f"acme-cleanup-target:{job_id}", {"target": "cancelled"}
                )
                return self.renewals.transition(
                    job_id,
                    RenewalState(job["state"]),
                    job["version"],
                    RenewalState.CLEANUP_REQUIRED,
                    {
                        "error_code": "dns_cleanup_failed",
                        "error_message": "; ".join(cleanup.errors),
                    },
                )
        return self.renewals.cancel(job_id)

    def retry_cleanup(self, job_id):
        job = self._job(job_id, RenewalState.CLEANUP_REQUIRED)
        cleanup = self._provider(job).cleanup(
            self._load_presented(job_id, required=False)
        )
        if cleanup.errors:
            return job
        target = self.database.get_setting(
            f"acme-cleanup-target:{job_id}", {"target": "issued"}
        )["target"]
        return self.renewals.transition(
            job_id,
            RenewalState.CLEANUP_REQUIRED,
            job["version"],
            RenewalState(target),
            {"error_code": None, "error_message": None},
        )

    def _complete_dns(self, job, presented):
        job = self.renewals.transition(
            job["id"],
            RenewalState.AWAITING_DNS,
            job["version"],
            RenewalState.VALIDATING,
        )
        try:
            self.orders.answer_challenges(job["id"])
            self.orders.poll_authorizations(job["id"])
            job = self.renewals.transition(
                job["id"],
                RenewalState.VALIDATING,
                job["version"],
                RenewalState.ISSUING,
            )
            result = self.orders.finalize(job["id"])
            certificate_id = self._store_certificate(job, result)
        except ACMEOrderError as error:
            cleanup = self._provider(job).cleanup(presented)
            message = str(error)
            if error.retry_at:
                message = f"{message}; retry after {error.retry_at.isoformat()}"
            current = self.database.get_job(job["id"])
            target = (
                RenewalState.CLEANUP_REQUIRED
                if cleanup.errors
                else RenewalState.FAILED
            )
            return self.renewals.transition(
                job["id"],
                RenewalState(current["state"]),
                current["version"],
                target,
                {"error_code": error.code, "error_message": message},
            )
        except CertificateValidationError as error:
            cleanup = self._provider(job).cleanup(presented)
            current = self.database.get_job(job["id"])
            target = (
                RenewalState.CLEANUP_REQUIRED
                if cleanup.errors
                else RenewalState.FAILED
            )
            return self.renewals.transition(
                job["id"],
                RenewalState(current["state"]),
                current["version"],
                target,
                {
                    "error_code": "acme_certificate_invalid",
                    "error_message": (
                        "Certificate validation failed: "
                        + ", ".join(error.errors)
                    ),
                },
            )
        except Exception:
            cleanup = self._provider(job).cleanup(presented)
            current = self.database.get_job(job["id"])
            target = (
                RenewalState.CLEANUP_REQUIRED
                if cleanup.errors
                else RenewalState.FAILED
            )
            return self.renewals.transition(
                job["id"],
                RenewalState(current["state"]),
                current["version"],
                target,
                {
                    "error_code": "acme_certificate_invalid",
                    "error_message": "The ACME certificate response could not be validated",
                },
            )

        cleanup = self._provider(job).cleanup(presented)
        self.artifacts.delete_certificate_set(self._pending_id(job["id"]))
        if cleanup.errors:
            self.database.put_setting(
                f"acme-cleanup-target:{job['id']}", {"target": "issued"}
            )
            return self.renewals.transition(
                job["id"],
                RenewalState.ISSUING,
                job["version"],
                RenewalState.CLEANUP_REQUIRED,
                {
                    "certificate_id": certificate_id,
                    "error_code": "dns_cleanup_failed",
                    "error_message": "; ".join(cleanup.errors),
                },
            )
        completed = self.renewals.transition(
            job["id"],
            RenewalState.ISSUING,
            job["version"],
            RenewalState.ISSUED,
            {"certificate_id": certificate_id},
        )
        self.database.delete_setting(f"acme-dns:{job['id']}")
        if job["environment"] == "staging":
            self.database.put_setting(
                f"acme-staging-proof:{self.identifier_hash(job['identifiers'])}",
                {
                    "certificate_id": certificate_id,
                    "identifiers": job["identifiers"],
                },
            )
        return completed

    def _store_certificate(self, job, result):
        pending_id = self._pending_id(job["id"])
        with self.artifacts.materialize_private(pending_id, "private-key.pem") as path:
            private_key = path.read_bytes()
        validation = validate_certificate_import(
            result["certificate_pem"],
            private_key,
            chain_pem=result.get("chain_pem"),
            expected_identifiers=job["identifiers"],
        )
        if not validation.cryptographically_valid:
            raise CertificateValidationError(validation.errors)
        certificate_id = str(uuid.uuid4())
        chain = result.get("chain_pem") or b""
        metadata = {
            "kind": "leaf",
            "issuer_type": "acme",
            "environment": job["environment"],
            "profile": job["profile"],
            "identifiers": list(job["identifiers"]),
            "trust_status": validation.trust_status,
            "not_after": validation.ordered_chain[0].not_valid_after_utc.isoformat(),
        }
        public_files = {
            "certificate.pem": result["certificate_pem"],
            "full-chain.pem": result["certificate_pem"] + chain,
        }
        if chain:
            public_files["chain.pem"] = chain
        self.artifacts.create_certificate_set(
            certificate_id,
            public_files,
            {
                "private-key.pem": private_key,
                "combined.pem": result["certificate_pem"] + chain + private_key,
            },
            metadata,
        )
        try:
            self.database.put_certificate(certificate_id, metadata)
        except Exception:
            self.artifacts.delete_certificate_set(certificate_id)
            raise
        return certificate_id

    def _ensure_pending_key_and_csr(self, job):
        pending_id = self._pending_id(job["id"])
        if self.artifacts.has_certificate(pending_id):
            return self.artifacts.read_public(pending_id, "request.csr")
        profile = PROFILES[job["profile"]]
        key = generate_private_key(profile)
        csr = build_csr(key, job["identifiers"], profile)
        csr_pem = csr.public_bytes(serialization.Encoding.PEM)
        self.artifacts.create_certificate_set(
            pending_id,
            {"request.csr": csr_pem},
            {"private-key.pem": serialize_private_key(key)},
            {"kind": "acme_pending", "job_id": job["id"]},
        )
        return csr_pem

    def _present(self, job, challenges):
        records = tuple(
            DNSChallengeRecord(item["fqdn"], item["value"])
            for item in challenges
        )
        presented = self._provider(job).present(records)
        self.database.put_setting(
            f"acme-dns:{job['id']}",
            [self._serialize_presented(record) for record in presented],
        )
        return presented

    def _load_presented(self, job_id, *, required=True):
        records = self.database.get_setting(f"acme-dns:{job_id}")
        if records is None:
            if required:
                raise KeyError(f"No DNS records for job {job_id}")
            return ()
        return tuple(
            PresentedRecord(
                **{
                    **record,
                    "expires_at": _parse_datetime(record.get("expires_at")),
                }
            )
            for record in records
        )

    def _provider(self, job):
        try:
            return self.dns_providers[job["dns_provider"]]
        except KeyError as error:
            raise ValueError(f"Unknown DNS provider: {job['dns_provider']}") from error

    def _job(self, job_id, state):
        job = self.database.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if job["issuer_type"] != "acme" or job["state"] != state.value:
            raise ValueError(f"ACME job must be in {state.value} state")
        return job

    @staticmethod
    def identifier_hash(identifiers):
        payload = json.dumps(sorted(identifiers), separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _pending_id(job_id):
        return f"acme-{job_id}"

    @staticmethod
    def _serialize_presented(record):
        return {
            "fqdn": record.fqdn,
            "value": record.value,
            "provider": record.provider,
            "expires_at": (
                record.expires_at.isoformat() if record.expires_at else None
            ),
            "zone_id": record.zone_id,
            "record_id": record.record_id,
        }

    @staticmethod
    def _public_records(records):
        return tuple({"fqdn": record.fqdn, "value": record.value} for record in records)


def _parse_datetime(value):
    if not value:
        return None
    from datetime import datetime

    return datetime.fromisoformat(value)
