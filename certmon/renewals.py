import ipaddress
import uuid

from certmon.models import RenewalState, validate_transition
from certmon.permissions import Permission, authorize


class IdentifierError(ValueError):
    pass


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
