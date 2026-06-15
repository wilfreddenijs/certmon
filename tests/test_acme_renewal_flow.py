from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from certmon.acme_service import ACMEOrderError
from certmon.artifacts import ArtifactStore
from certmon.db import Database
from certmon.dns.base import CleanupResult, PresentedRecord
from certmon.dns.manual import ManualChallengeExpired
from certmon.renewals import (
    ACMERenewalOrchestrator,
    RenewalService,
    StagingRequired,
)
from certmon.vault import MemoryKeyProtector, Vault


class FakeAccounts:
    def __init__(self):
        self.calls = []

    def register(self, environment, **kwargs):
        self.calls.append((environment, kwargs))
        return {"environment": environment}


class FakeOrders:
    def __init__(self):
        self.created = 0
        self.answered = 0
        self.poll_error = None
        self.root_key, self.root = make_ca()

    def create_order(self, job_id, csr_pem):
        self.created += 1
        result = {
            "order_url": f"https://acme.test/order/{self.created}",
            "dns_challenges": [
                {
                    "fqdn": "_acme-challenge.device.example.com",
                    "value": f"value-{self.created}",
                }
            ],
        }
        self.database.put_setting(
            f"acme-order:{job_id}",
            {
                **result,
                "job_id": job_id,
                "environment": self.database.get_job(job_id)["environment"],
                "authorization_urls": [],
                "csr_pem": csr_pem.decode("utf-8"),
            },
        )
        return result

    def answer_challenges(self, job_id):
        self.answered += 1

    def poll_authorizations(self, job_id):
        if self.poll_error:
            raise self.poll_error
        return {"status": "ready"}

    def finalize(self, job_id):
        csr_pem = self.database.get_setting(f"acme-order:{job_id}")["csr_pem"]
        csr = x509.load_pem_x509_csr(csr_pem.encode("utf-8"))
        now = datetime.now(timezone.utc)
        leaf = (
            x509.CertificateBuilder()
            .subject_name(csr.subject)
            .issuer_name(self.root.subject)
            .public_key(csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=90))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
            .add_extension(
                csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value,
                False,
            )
            .sign(self.root_key, hashes.SHA256())
        )
        return {
            "status": "valid",
            "certificate_pem": leaf.public_bytes(serialization.Encoding.PEM),
            "chain_pem": self.root.public_bytes(serialization.Encoding.PEM),
        }


class FakeManualProvider:
    def __init__(self):
        self.visible = True
        self.expired = False
        self.presented = []

    def present(self, records):
        presented = tuple(
            PresentedRecord(r.fqdn, r.value, "manual") for r in records
        )
        self.presented.append(presented)
        return presented

    def check_visibility(self, presented):
        if self.expired:
            self.expired = False
            raise ManualChallengeExpired("expired")
        return tuple(type("Visibility", (), {"visible": self.visible})() for _ in presented)

    def cleanup(self, presented):
        return CleanupResult(cleaned=0)


class FakeCloudflareProvider:
    def __init__(self, *, cleanup_errors=()):
        self.presented = []
        self.cleaned = []
        self.cleanup_errors = cleanup_errors

    def present(self, records):
        result = tuple(
            PresentedRecord(r.fqdn, r.value, "cloudflare", zone_id="z", record_id="r")
            for r in records
        )
        self.presented.append(result)
        return result

    def cleanup(self, presented):
        self.cleaned.append(presented)
        return CleanupResult(
            cleaned=len(presented) if not self.cleanup_errors else 0,
            errors=tuple(self.cleanup_errors),
        )


def make_services(tmp_path, *, dns_provider="manual", provider=None):
    database = Database(tmp_path / "certmon.db")
    database.initialize()
    vault = Vault(tmp_path / "vault", MemoryKeyProtector())
    vault.initialize()
    artifacts = ArtifactStore(tmp_path / "certificates", vault)
    renewals = RenewalService(database)
    accounts = FakeAccounts()
    orders = FakeOrders()
    orders.database = database
    provider = provider or (
        FakeManualProvider() if dns_provider == "manual" else FakeCloudflareProvider()
    )
    orchestrator = ACMERenewalOrchestrator(
        database,
        renewals,
        accounts,
        orders,
        artifacts,
        {dns_provider: provider},
    )
    return database, artifacts, renewals, accounts, orders, provider, orchestrator


def create_job(renewals, *, environment="staging", dns_provider="manual"):
    return renewals.create_job(
        endpoint_host="device.example.com",
        endpoint_port=443,
        issuer_type="acme",
        identifiers=["device.example.com"],
        profile="generic-rsa",
        environment=environment,
        dns_provider=dns_provider,
    )


def test_manual_dns_pauses_then_resumes_to_encrypted_certificate(tmp_path):
    database, artifacts, renewals, _, orders, _, orchestrator = make_services(tmp_path)
    job = create_job(renewals)

    paused = orchestrator.start_acme(
        job["id"], email="admin@example.com", terms_of_service_agreed=True
    )
    completed = orchestrator.continue_manual_dns(job["id"])

    assert paused["state"] == "awaiting_dns"
    assert completed["state"] == "issued"
    assert orders.answered == 1
    certificate_id = completed["certificate_id"]
    assert artifacts.read_public(certificate_id, "certificate.pem").startswith(
        b"-----BEGIN CERTIFICATE-----"
    )
    with artifacts.materialize_private(certificate_id, "private-key.pem") as path:
        assert b"PRIVATE KEY" in path.read_bytes()
    assert database.get_setting(
        f"acme-staging-proof:{orchestrator.identifier_hash(job['identifiers'])}"
    )["certificate_id"] == certificate_id


def test_cloudflare_flow_runs_automatically_and_cleans_records(tmp_path):
    provider = FakeCloudflareProvider()
    _, _, renewals, _, _, _, orchestrator = make_services(
        tmp_path, dns_provider="cloudflare", provider=provider
    )
    job = create_job(renewals, dns_provider="cloudflare")

    result = orchestrator.start_acme(
        job["id"], email="admin@example.com", terms_of_service_agreed=True
    )

    assert result["state"] == "issued"
    assert len(provider.presented) == 1
    assert len(provider.cleaned) == 1


def test_production_requires_matching_staging_identifier_proof(tmp_path):
    database, _, renewals, accounts, _, _, orchestrator = make_services(tmp_path)
    job = create_job(renewals, environment="production")

    with pytest.raises(StagingRequired) as error:
        orchestrator.start_acme(
            job["id"], email="admin@example.com", terms_of_service_agreed=True
        )

    assert error.value.code == "staging_required"
    assert error.value.action_url.endswith(job["id"])
    assert accounts.calls == []
    database.put_setting(
        f"acme-staging-proof:{orchestrator.identifier_hash(job['identifiers'])}",
        {"certificate_id": "staging-cert"},
    )
    assert orchestrator.start_acme(
        job["id"], email="admin@example.com", terms_of_service_agreed=True
    )["state"] == "awaiting_dns"


def test_rate_limit_failure_records_retry_time(tmp_path):
    database, _, renewals, _, orders, _, orchestrator = make_services(tmp_path)
    job = create_job(renewals)
    orchestrator.start_acme(
        job["id"], email="admin@example.com", terms_of_service_agreed=True
    )
    retry_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    orders.poll_error = ACMEOrderError(
        "acme_rate_limited", "slow down", retry_at=retry_at
    )

    result = orchestrator.continue_manual_dns(job["id"])

    assert result["state"] == "failed"
    assert database.get_job(job["id"])["error_code"] == "acme_rate_limited"
    assert retry_at.isoformat() in database.get_job(job["id"])["error_message"]


def test_cleanup_failure_moves_issued_material_to_cleanup_required(tmp_path):
    provider = FakeCloudflareProvider(cleanup_errors=("delete failed",))
    database, _, renewals, _, _, _, orchestrator = make_services(
        tmp_path, dns_provider="cloudflare", provider=provider
    )
    job = create_job(renewals, dns_provider="cloudflare")

    result = orchestrator.start_acme(
        job["id"], email="admin@example.com", terms_of_service_agreed=True
    )

    assert result["state"] == "cleanup_required"
    assert database.get_job(job["id"])["certificate_id"]


def test_expired_manual_challenge_is_replaced_without_losing_job(tmp_path):
    _, _, renewals, _, orders, provider, orchestrator = make_services(tmp_path)
    job = create_job(renewals)
    orchestrator.start_acme(
        job["id"], email="admin@example.com", terms_of_service_agreed=True
    )
    provider.expired = True

    result = orchestrator.continue_manual_dns(job["id"])

    assert result["state"] == "awaiting_dns"
    assert result["replaced"] is True
    assert orders.created == 2


def test_cancellation_cleans_presented_records(tmp_path):
    provider = FakeCloudflareProvider()
    _, _, renewals, _, _, _, orchestrator = make_services(
        tmp_path, dns_provider="manual", provider=provider
    )
    job = create_job(renewals, dns_provider="manual")
    paused = orchestrator.start_acme(
        job["id"], email="admin@example.com", terms_of_service_agreed=True
    )
    assert paused["state"] == "awaiting_dns"

    result = orchestrator.cancel(job["id"])

    assert result["state"] == "cancelled"
    assert len(provider.cleaned) == 1


def test_manual_job_resumes_after_orchestrator_restart(tmp_path):
    database, artifacts, renewals, accounts, orders, provider, orchestrator = make_services(
        tmp_path
    )
    job = create_job(renewals)
    orchestrator.start_acme(
        job["id"], email="admin@example.com", terms_of_service_agreed=True
    )
    restarted = ACMERenewalOrchestrator(
        database,
        renewals,
        accounts,
        orders,
        artifacts,
        {"manual": provider},
    )

    assert restarted.continue_manual_dns(job["id"])["state"] == "issued"


def test_retry_cleanup_finishes_issued_job(tmp_path):
    provider = FakeCloudflareProvider(cleanup_errors=("delete failed",))
    _, _, renewals, _, _, _, orchestrator = make_services(
        tmp_path, dns_provider="cloudflare", provider=provider
    )
    job = create_job(renewals, dns_provider="cloudflare")
    result = orchestrator.start_acme(
        job["id"], email="admin@example.com", terms_of_service_agreed=True
    )
    assert result["state"] == "cleanup_required"
    provider.cleanup_errors = ()

    assert orchestrator.retry_cleanup(job["id"])["state"] == "issued"


def test_invalid_certificate_response_fails_without_leaking_details(tmp_path):
    database, _, renewals, _, orders, _, orchestrator = make_services(tmp_path)
    job = create_job(renewals)
    orchestrator.start_acme(
        job["id"], email="admin@example.com", terms_of_service_agreed=True
    )
    orders.finalize = lambda job_id: {
        "status": "valid",
        "certificate_pem": b"not a certificate",
        "chain_pem": b"",
    }

    result = orchestrator.continue_manual_dns(job["id"])

    assert result["state"] == "failed"
    assert database.get_job(job["id"])["error_code"] == "acme_certificate_invalid"
    assert "not a certificate" not in database.get_job(job["id"])["error_message"]


def make_ca():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test ACME Root")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=1), True)
        .add_extension(
            x509.KeyUsage(True, False, False, False, False, True, True, False, False),
            True,
        )
        .sign(key, hashes.SHA256())
    )
    return key, certificate
