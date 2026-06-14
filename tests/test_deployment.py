import importlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from certmon.db import Database
from certmon.models import RenewalState
from certmon.renewals import RenewalService


def load_app(tmp_data_dir):
    import app

    return importlib.reload(app)


def test_push_route_rejects_private_material_fields(tmp_data_dir):
    module = load_app(tmp_data_dir)
    client = module.app.test_client()

    response = client.post(
        "/api/upload/push",
        json={
            "device_id": "device-1",
            "certificate_id": "cert-1",
            "cert_pem": "-----BEGIN CERTIFICATE-----",
            "key_pem": "-----BEGIN PRIVATE KEY-----",
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "Private certificate material must not be sent to this API"


def test_push_route_requires_certificate_id_and_device_id_only(tmp_data_dir):
    module = load_app(tmp_data_dir)
    client = module.app.test_client()

    response = client.post(
        "/api/upload/push",
        json={"device_id": "device-1"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "certificate_id and device_id are required"


def test_push_route_rejects_fields_other_than_certificate_and_device_ids(tmp_data_dir):
    module = load_app(tmp_data_dir)
    client = module.app.test_client()

    response = client.post(
        "/api/upload/push",
        json={
            "device_id": "device-1",
            "certificate_id": "cert-1",
            "job_id": "job-1",
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "Unsupported fields: ['job_id']"


class FakeArtifacts:
    def __init__(self, tmp_path, certificate_pem):
        self.tmp_path = tmp_path
        self.certificate_pem = certificate_pem

    def has_certificate(self, certificate_id):
        return certificate_id == "cert-1"

    def read_public(self, certificate_id, name):
        if name != "certificate.pem":
            raise FileNotFoundError(name)
        return self.certificate_pem

    @contextmanager
    def materialize_private(self, certificate_id, name):
        path = self.tmp_path / f"{certificate_id}-{name}"
        path.write_text("PRIVATE KEY", encoding="utf-8")
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)


class InspectingAdapter:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.private_key_exists_during_call = None
        self.private_key_exists_after_call = None
        self.private_key_text = None

    def deploy(self, device, certificate):
        with certificate.materialize_private_key() as path:
            self.private_key_exists_during_call = path.exists()
            self.private_key_text = path.read_text(encoding="utf-8")
        self.private_key_exists_after_call = path.exists()
        if self.fail:
            raise RuntimeError("adapter boom")
        from certmon.deployment import DeploymentAttempt

        return DeploymentAttempt(success=True, log=("upload ok",))


def test_verified_deployment_transitions_job_and_records_event(tmp_path):
    from certmon.deployment import (
        DeploymentAttempt,
        DeploymentService,
        VerificationResult,
    )

    database = Database(tmp_path / "certmon.db")
    database.initialize()
    renewal_service = RenewalService(database)
    certificate_pem = make_certificate_pem("device.local")
    artifacts = FakeArtifacts(tmp_path, certificate_pem)
    adapter = InspectingAdapter()
    service = DeploymentService(
        database,
        artifacts,
        renewal_service,
        adapters={"extron": adapter},
        verifier=lambda device, material: VerificationResult(
            status="verified",
            expected_fingerprint=material.expected_fingerprint,
            observed_fingerprint=material.expected_fingerprint,
        ),
        public_artifact_url_builder=lambda certificate_id, name: f"/public/{certificate_id}/{name}",
    )
    database.put_certificate(
        "cert-1",
        {
            "kind": "leaf",
            "issuer_type": "local_ca",
            "profile": "extron-rsa",
            "identifiers": ["device.local"],
            "not_after": "2030-01-01T00:00:00+00:00",
        },
    )
    database.create_job(
        job_id="job-1",
        endpoint_host="device.local",
        endpoint_port=443,
        issuer_type="local_ca",
        state=RenewalState.ISSUED.value,
        identifiers=("device.local",),
        profile="extron-rsa",
        environment=None,
        dns_provider=None,
    )
    database.compare_and_set_job(
        "job-1",
        RenewalState.ISSUED.value,
        0,
        RenewalState.ISSUED.value,
        {"certificate_id": "cert-1"},
    )

    result = service.deploy_certificate(
        {
            "id": "device-1",
            "host": "device.local",
            "port": 443,
            "https": True,
            "device_type": "extron",
            "username": "admin",
            "password": "secret",
        },
        "cert-1",
    )

    assert result.ok is True
    assert result.verification.status == "verified"
    assert result.job["state"] == "deployed"
    assert adapter.private_key_exists_during_call is True
    assert adapter.private_key_exists_after_call is False
    assert adapter.private_key_text == "PRIVATE KEY"
    assert database.list_events("job-1")[-1]["event_type"] == "certificate_deployment"


def test_unverified_deployment_stays_pending_with_details(tmp_path):
    from certmon.deployment import DeploymentAttempt, DeploymentService, VerificationResult

    database = Database(tmp_path / "certmon.db")
    database.initialize()
    renewal_service = RenewalService(database)
    artifacts = FakeArtifacts(tmp_path, make_certificate_pem("device.local"))

    class SuccessfulAdapter:
        def deploy(self, device, certificate):
            return DeploymentAttempt(success=True, log=("upload ok",))

    service = DeploymentService(
        database,
        artifacts,
        renewal_service,
        adapters={"extron": SuccessfulAdapter()},
        verifier=lambda device, material: VerificationResult(
            status="different_certificate",
            expected_fingerprint=material.expected_fingerprint,
            observed_fingerprint="00" * 32,
        ),
        public_artifact_url_builder=lambda certificate_id, name: f"/public/{certificate_id}/{name}",
    )
    database.put_certificate(
        "cert-1",
        {
            "kind": "leaf",
            "issuer_type": "local_ca",
            "profile": "extron-rsa",
            "identifiers": ["device.local"],
            "not_after": "2030-01-01T00:00:00+00:00",
        },
    )
    database.create_job(
        job_id="job-1",
        endpoint_host="device.local",
        endpoint_port=443,
        issuer_type="local_ca",
        state=RenewalState.ISSUED.value,
        identifiers=("device.local",),
        profile="extron-rsa",
        environment=None,
        dns_provider=None,
    )
    database.compare_and_set_job(
        "job-1",
        RenewalState.ISSUED.value,
        0,
        RenewalState.ISSUED.value,
        {"certificate_id": "cert-1"},
    )

    result = service.deploy_certificate(
        {
            "id": "device-1",
            "host": "device.local",
            "port": 443,
            "https": True,
            "device_type": "extron",
            "username": "admin",
            "password": "secret",
        },
        "cert-1",
    )

    assert result.ok is False
    assert result.verification.status == "different_certificate"
    assert result.job["state"] == "deployment_pending"
    assert result.job["error_code"] == "deployment_verification_failed"
    assert "different_certificate" in result.job["error_message"]


def test_adapter_failure_removes_materialized_private_key(tmp_path):
    from certmon.deployment import DeploymentService

    database = Database(tmp_path / "certmon.db")
    database.initialize()
    database.put_certificate(
        "cert-1",
        {
            "kind": "leaf",
            "issuer_type": "local_ca",
            "profile": "extron-rsa",
            "identifiers": ["device.local"],
            "not_after": "2030-01-01T00:00:00+00:00",
        },
    )
    adapter = InspectingAdapter(fail=True)
    service = DeploymentService(
        database,
        FakeArtifacts(tmp_path, make_certificate_pem("device.local")),
        RenewalService(database),
        adapters={"extron": adapter},
    )

    result = service.deploy_certificate(
        {
            "id": "device-1",
            "host": "device.local",
            "port": 443,
            "https": True,
            "device_type": "extron",
        },
        "cert-1",
    )

    assert result.ok is False
    assert adapter.private_key_exists_during_call is True
    assert adapter.private_key_exists_after_call is False


def test_fingerprint_verification_reports_unreachable(monkeypatch):
    from certmon.deployment import verify_device_certificate

    def unavailable(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr("certmon.deployment.socket.create_connection", unavailable)

    result = verify_device_certificate(
        {"host": "device.local", "port": 443},
        SimpleNamespace(expected_fingerprint="ab" * 32),
    )

    assert result.status == "unreachable"
    assert result.observed_fingerprint is None


def make_certificate_pem(common_name):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, common_name)]
    )
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(common_name)]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM)
