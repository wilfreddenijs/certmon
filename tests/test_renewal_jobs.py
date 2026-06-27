import pytest

from certmon.db import ConcurrentUpdateError, Database
from certmon.models import InvalidTransition, RenewalState
from certmon.renewals import IdentifierError, RenewalService, normalize_identifiers


def make_service(tmp_path):
    db = Database(tmp_path / "certmon.db")
    db.initialize()
    return db, RenewalService(db)


def test_allowed_transition_records_event(tmp_path):
    db, service = make_service(tmp_path)
    job = service.create_job(
        endpoint_host="192.168.1.20",
        endpoint_port=443,
        issuer_type="acme",
        identifiers=["Device.Example.COM"],
        profile="generic-rsa",
    )

    updated = service.transition(
        job["id"], RenewalState.DRAFT, 0, RenewalState.AWAITING_DNS
    )

    assert updated["state"] == "awaiting_dns"
    assert db.list_events(job["id"])[-1]["event_type"] == "state_changed"


def test_invalid_transition_is_rejected(tmp_path):
    _, service = make_service(tmp_path)
    job = service.create_job(
        endpoint_host="device.local",
        endpoint_port=443,
        issuer_type="local_ca",
        identifiers=["device.local"],
        profile="generic-rsa",
    )

    with pytest.raises(InvalidTransition):
        service.transition(job["id"], RenewalState.DRAFT, 0, RenewalState.DEPLOYED)


def test_stale_transition_is_rejected(tmp_path):
    _, service = make_service(tmp_path)
    job = service.create_job(
        endpoint_host="device.local",
        endpoint_port=443,
        issuer_type="local_ca",
        identifiers=["device.local"],
        profile="generic-rsa",
    )
    service.transition(job["id"], RenewalState.DRAFT, 0, RenewalState.ISSUING)

    with pytest.raises(ConcurrentUpdateError):
        service.transition(job["id"], RenewalState.DRAFT, 0, RenewalState.ISSUING)


def test_identifier_normalization_keeps_endpoint_separate():
    identifiers = normalize_identifiers(
        ["Device.Example.COM", "device.example.com", "*.Example.com"]
    )

    assert identifiers == ("device.example.com", "*.example.com")
    assert "192.168.1.20" not in identifiers


@pytest.mark.parametrize("value", ["192.168.1.20", "device.local", "printer", "localhost"])
def test_public_acme_rejects_internal_identifiers(value):
    with pytest.raises(IdentifierError):
        normalize_identifiers([value], public_acme=True)


def test_cancellation_is_idempotent(tmp_path):
    _, service = make_service(tmp_path)
    job = service.create_job(
        endpoint_host="device.local",
        endpoint_port=443,
        issuer_type="external_ca",
        identifiers=["device.local"],
        profile="generic-rsa",
    )

    cancelled = service.cancel(job["id"])
    repeated = service.cancel(job["id"])

    assert cancelled["state"] == "cancelled"
    assert repeated["state"] == "cancelled"


def test_delete_terminal_job_removes_cancelled_job_and_events(tmp_path):
    db, service = make_service(tmp_path)
    job = service.create_job(
        endpoint_host="device.local",
        endpoint_port=443,
        issuer_type="external_ca",
        identifiers=["device.local"],
        profile="generic-rsa",
    )
    cancelled = service.cancel(job["id"])

    removed = service.delete_terminal_job(cancelled["id"])

    assert removed["state"] == "cancelled"
    assert db.get_job(job["id"]) is None
    assert db.list_events(job["id"]) == []


def test_delete_terminal_job_removes_deployment_pending_job(tmp_path):
    db, service = make_service(tmp_path)
    job = service.create_job(
        endpoint_host="device.local",
        endpoint_port=443,
        issuer_type="acme",
        identifiers=["device.example.com"],
        profile="generic-rsa",
    )
    issuing = service.transition(job["id"], "draft", job["version"], "issuing")
    issued = service.transition(issuing["id"], "issuing", issuing["version"], "issued")
    pending = service.transition(
        issued["id"], "issued", issued["version"], "deployment_pending"
    )

    removed = service.delete_terminal_job(pending["id"])

    assert removed["state"] == "deployment_pending"
    assert db.get_job(job["id"]) is None


def test_delete_terminal_job_removes_issued_job(tmp_path):
    db, service = make_service(tmp_path)
    job = service.create_job(
        endpoint_host="device.local",
        endpoint_port=443,
        issuer_type="external_ca",
        identifiers=["device.local"],
        profile="generic-rsa",
    )
    issuing = service.transition(job["id"], "draft", job["version"], "issuing")
    issued = service.transition(issuing["id"], "issuing", issuing["version"], "issued")

    removed = service.delete_terminal_job(issued["id"])

    assert removed["state"] == "issued"
    assert db.get_job(job["id"]) is None


def test_delete_terminal_job_removes_existing_import_draft_job(tmp_path):
    db, service = make_service(tmp_path)
    job = service.create_job(
        endpoint_host="device.local",
        endpoint_port=443,
        issuer_type="external_ca",
        identifiers=["device.local"],
        profile="generic-rsa",
        metadata={"external_ca_workflow": "existing"},
    )

    removed = service.delete_terminal_job(job["id"])

    assert removed["state"] == "draft"
    assert removed["metadata"]["external_ca_workflow"] == "existing"
    assert db.get_job(job["id"]) is None


def test_delete_terminal_job_rejects_active_job(tmp_path):
    _, service = make_service(tmp_path)
    job = service.create_job(
        endpoint_host="device.local",
        endpoint_port=443,
        issuer_type="acme",
        identifiers=["device.example.com"],
        profile="generic-rsa",
    )

    with pytest.raises(ValueError, match="cancelled, failed, issued, deployed, or deployment-pending"):
        service.delete_terminal_job(job["id"])


def test_recovery_leaves_paused_jobs_and_reconciles_active_acme_job(tmp_path):
    db, service = make_service(tmp_path)
    paused = service.create_job(
        endpoint_host="device.example.com",
        endpoint_port=443,
        issuer_type="acme",
        identifiers=["device.example.com"],
        profile="generic-rsa",
    )
    paused = service.transition(
        paused["id"], RenewalState.DRAFT, 0, RenewalState.AWAITING_DNS
    )
    active = service.create_job(
        endpoint_host="other.example.com",
        endpoint_port=443,
        issuer_type="acme",
        identifiers=["other.example.com"],
        profile="generic-rsa",
    )
    active = service.transition(
        active["id"], RenewalState.DRAFT, 0, RenewalState.ISSUING
    )

    class FakeACME:
        def __init__(self):
            self.seen = []

        def reconcile(self, job):
            self.seen.append(job["id"])
            return RenewalState.FAILED, {
                "error_code": "acme_interrupted",
                "error_message": "Order needs operator review",
            }

    fake = FakeACME()
    service.recover_interrupted_jobs(fake)

    assert db.get_job(paused["id"])["state"] == "awaiting_dns"
    assert db.get_job(active["id"])["state"] == "failed"
    assert fake.seen == [active["id"]]
