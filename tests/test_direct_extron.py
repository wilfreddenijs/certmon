from contextlib import contextmanager
from pathlib import Path

import pytest

from certmon.deployment import VerificationResult
from certmon.direct_extron import DirectExtronService, EndpointIdentity


class FakeDatabase:
    def __init__(self):
        self.settings = {}
        self.secrets = {}
        self.certificates = [
            {
                "id": "cert-1",
                "kind": "leaf",
                "issuer_type": "local_ca",
                "profile": "extron-rsa",
                "device_name": "Room A",
                "identifiers": ["10.0.0.10"],
            }
        ]

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    def put_setting(self, key, value):
        self.settings[key] = value

    def get_secret(self, key):
        return self.secrets.get(key)

    def put_secret(self, key, blob, metadata):
        self.secrets[key] = {"blob": blob, "metadata": metadata}

    def delete_secret(self, key):
        self.secrets.pop(key, None)

    def list_certificates(self):
        return list(self.certificates)


class FakeVault:
    def encrypt(self, value, *, purpose):
        return value

    def decrypt(self, blob, *, purpose):
        return blob


class FakeArtifacts:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.materializations = 0

    def has_certificate(self, certificate_id):
        return certificate_id == "cert-1"

    @contextmanager
    def materialize_private(self, certificate_id, name):
        self.materializations += 1
        path = self.tmp_path / f"{certificate_id}-{name}"
        path.write_text("combined private PEM", encoding="utf-8")
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)


class FakeTransport:
    def __init__(self, *, key="SHA256:known", ack=b"CertI1\r\n", delete_error=False):
        self.key = key
        self.ack = ack
        self.delete_error = delete_error
        self.auth_attempts = []
        self.sftp_writes = []
        self.sis_commands = []
        self.deleted = []
        self.probes = []

    def host_key_fingerprint(self, identity):
        self.probes.append(identity)
        return self.key

    def probe_credentials(self, identity, credentials):
        self.auth_attempts.append((identity, credentials))

    def stage(self, identity, credentials, local_path, remote_name):
        self.auth_attempts.append((identity, credentials))
        self.sftp_writes.append((identity, remote_name))

    def ingest(self, identity, credentials, command):
        self.auth_attempts.append((identity, credentials))
        self.sis_commands.append((identity, command))
        return self.ack

    def delete(self, identity, credentials, remote_name):
        self.auth_attempts.append((identity, credentials))
        if self.delete_error:
            raise OSError("delete failed")
        self.deleted.append((identity, remote_name))


def make_service(tmp_path, *, transport=None, verifier=None):
    database = FakeDatabase()
    artifacts = FakeArtifacts(tmp_path)
    transport = transport or FakeTransport()
    verifier = verifier or (lambda endpoint, material: VerificationResult(
        status="verified",
        expected_fingerprint="ab" * 32,
        observed_fingerprint="ab" * 32,
    ))
    service = DirectExtronService(
        database, artifacts, FakeVault(), transport=transport, verifier=verifier
    )
    service.save_shared_credentials(username="admin", password="shared-secret")
    return service, database, artifacts, transport


def approve(service, selector="10.0.0.10", nic=1):
    probe = service.probe_one(selector=selector, nic=nic)
    assert probe["status"] == "approval_required"
    return service.approve_host_key(
        selector=selector, nic=nic, fingerprint=probe["fingerprint"]
    )


def test_endpoint_identity_is_exact_and_lan_b_requires_a_distinct_endpoint(tmp_path):
    service, _, _, _ = make_service(tmp_path)

    lan_a = service.target_for("10.0.0.10", 1)
    assert lan_a.https == EndpointIdentity("10.0.0.10", 1, "https", "10.0.0.10", 443)
    with pytest.raises(ValueError, match="LAN B endpoint"):
        service.target_for("10.0.0.10", 2)

    service.save_lan_b_target("10.0.0.10", host="10.0.1.10", port=8443)
    lan_b = service.target_for("10.0.0.10", 2)
    assert lan_b.https == EndpointIdentity("10.0.0.10", 2, "https", "10.0.1.10", 8443)
    assert lan_b.sftp.port == 22022
    assert lan_b.sis.port == 22023


def test_unknown_or_changed_key_stops_before_any_authentication(tmp_path):
    transport = FakeTransport(key="SHA256:first")
    service, _, artifacts, transport = make_service(tmp_path, transport=transport)

    assert service.probe_one(selector="10.0.0.10", nic=1)["status"] == "approval_required"
    assert transport.auth_attempts == []
    assert artifacts.materializations == 0
    approve(service)
    transport.key = "SHA256:changed"

    result = service.activate_one(selector="10.0.0.10", certificate_id="cert-1", nic=1)
    assert result["status"] == "host_key_changed"
    assert transport.auth_attempts == []
    assert transport.sftp_writes == []


def test_probe_never_materializes_or_mutates_transport(tmp_path):
    service, _, artifacts, transport = make_service(tmp_path)
    approve(service)

    result = service.probe_one(selector="10.0.0.10", nic=1)

    assert result["status"] == "ready"
    assert artifacts.materializations == 0
    assert transport.sftp_writes == []
    assert transport.sis_commands == []


def test_activation_uses_selected_lan_b_and_fragmented_exact_ack_then_https(tmp_path):
    transport = FakeTransport(ack=(b"Cert" + b"I2\r"))
    verified = []

    def verifier(endpoint, material):
        verified.append(endpoint)
        return VerificationResult("verified", "ab" * 32, "ab" * 32)

    service, _, _, transport = make_service(tmp_path, transport=transport, verifier=verifier)
    service.save_lan_b_target("10.0.0.10", host="10.0.1.10", port=8443)
    approve(service, nic=2)

    result = service.activate_one(selector="10.0.0.10", certificate_id="cert-1", nic=2)

    assert result["status"] == "verified"
    assert transport.sftp_writes[0][0].nic == 2
    assert b"\x1b2,*" in transport.sis_commands[0][1]
    assert verified[0]["host"] == "10.0.1.10"
    assert verified[0]["port"] == 8443
    assert transport.deleted


@pytest.mark.parametrize("ack", [b"CertI1\r", b"CertI2", b"noise CertI2\r more"])
def test_wrong_or_ambiguous_ack_never_replays_sis(tmp_path, ack):
    transport = FakeTransport(ack=ack)
    service, _, _, transport = make_service(tmp_path, transport=transport)
    approve(service)

    result = service.activate_one(selector="10.0.0.10", certificate_id="cert-1", nic=1)

    assert result["status"] in {"ack_rejected", "cleanup_pending"}
    assert len(transport.sis_commands) == 1


def test_per_device_credentials_never_fall_back_after_authentication_failure(tmp_path):
    class RejectingTransport(FakeTransport):
        def probe_credentials(self, identity, credentials):
            super().probe_credentials(identity, credentials)
            raise PermissionError("bad password")

    transport = RejectingTransport()
    service, _, _, transport = make_service(tmp_path, transport=transport)
    service.save_credentials("10.0.0.10", username="operator", password="device-secret")
    approve(service)

    result = service.probe_one(selector="10.0.0.10", nic=1)

    assert result == {"status": "authentication_failed"}
    assert len(transport.auth_attempts) == 1
    assert transport.auth_attempts[0][1]["username"] == "operator"
    assert "secret" not in repr(result)


def test_delete_failure_is_durable_and_cleanup_never_reingests(tmp_path):
    transport = FakeTransport(delete_error=True)
    service, database, _, transport = make_service(tmp_path, transport=transport)
    approve(service)

    result = service.activate_one(selector="10.0.0.10", certificate_id="cert-1", nic=1)
    staged = result["staged_name"]
    assert result["status"] == "delete_failed"
    assert database.get_setting(service.STAGED_KEY)[staged]["status"] == "delete_failed"
    before = len(transport.sis_commands)
    transport.delete_error = False

    cleanup = service.cleanup_one(staged_name=staged, confirm_finished=True)

    assert cleanup["status"] == "deleted"
    assert len(transport.sis_commands) == before


def test_routes_and_ui_expose_only_server_side_direct_actions():
    html = Path(__file__).parents[1].joinpath("templates", "index.html").read_text(encoding="utf-8")
    app_source = Path(__file__).parents[1].joinpath("app.py").read_text(encoding="utf-8")

    for endpoint in ("probe", "host-keys/approve", "activate", "cleanup"):
        assert f"/api/direct-extron/{endpoint}" in html
        assert f"/api/direct-extron/{endpoint}" in app_source
    assert "LAN B HTTPS host" in html
    assert "combined_pem" not in html
    assert "private_key" not in html
