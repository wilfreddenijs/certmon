from contextlib import contextmanager
import importlib
from pathlib import Path

import pytest

from certmon.deployment import VerificationResult
from certmon.direct_extron import DirectExtronService, EndpointIdentity, SISExchange, ParamikoDirectTransport
from tests.test_auth_api import load_app as load_server_app


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
        self.expected_fingerprints = []

    def host_key_fingerprint(self, identity):
        self.probes.append(identity)
        return self.key

    def probe_credentials(self, identity, credentials, **kwargs):
        self.auth_attempts.append((identity, credentials))
        self.expected_fingerprints.append(kwargs.get("expected_fingerprint"))

    def stage(self, identity, credentials, local_path, remote_name, **kwargs):
        self.auth_attempts.append((identity, credentials))
        self.expected_fingerprints.append(kwargs.get("expected_fingerprint"))
        self.sftp_writes.append((identity, remote_name))

    def ingest(self, identity, credentials, command, **kwargs):
        self.auth_attempts.append((identity, credentials))
        self.expected_fingerprints.append(kwargs.get("expected_fingerprint"))
        self.sis_commands.append((identity, command))
        return self.ack

    def delete(self, identity, credentials, remote_name, **kwargs):
        self.auth_attempts.append((identity, credentials))
        self.expected_fingerprints.append(kwargs.get("expected_fingerprint"))
        if self.delete_error:
            raise OSError("delete failed")
        self.deleted.append((identity, remote_name))


class FakeRouteService:
    def __init__(self):
        self.calls = []

    def probe_one(self, **kwargs):
        self.calls.append(("probe", kwargs))
        return {"status": "ready", "target": {"host": "10.0.0.10"}}

    def approve_host_key(self, **kwargs):
        self.calls.append(("approve", kwargs))
        return {"status": "approved", "fingerprint": kwargs["fingerprint"]}

    def activate_one(self, **kwargs):
        self.calls.append(("activate", kwargs))
        return {"status": "verified", "staged_name": "certmon-safe.pem"}

    def cleanup_one(self, **kwargs):
        self.calls.append(("cleanup", kwargs))
        return {"status": "deleted", "staged_name": kwargs["staged_name"]}

    def recover_staged(self):
        return []


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
    for _ in range(2):
        probe = service.probe_one(selector=selector, nic=nic)
        if probe["status"] == "ready":
            return
        assert probe["status"] == "approval_required"
        service.approve_host_key(selector=selector, nic=nic, fingerprint=probe["fingerprint"])


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
    assert [identity.connection for identity, _ in transport.auth_attempts] == ["sftp", "sis"]


def test_each_port_requires_its_own_host_key_approval(tmp_path):
    class DifferentKeys(FakeTransport):
        def host_key_fingerprint(self, identity):
            return ("ssh-ed25519", "SHA256:" + identity.connection)

    service, database, _, transport = make_service(tmp_path, transport=DifferentKeys())
    for connection in ("sftp", "sis"):
        result = service.probe_one(selector="10.0.0.10")
        assert result["identity"]["connection"] == connection
        assert transport.auth_attempts == []
        service.approve_host_key(selector="10.0.0.10", connection=connection, fingerprint=result["fingerprint"])
    assert len(database.get_setting(service.HOST_KEYS_KEY)) == 2
    assert service.probe_one(selector="10.0.0.10")["status"] == "ready"


def test_cleanup_uses_staged_endpoint_even_after_lan_b_target_changes(tmp_path):
    service, _, _, transport = make_service(tmp_path, transport=FakeTransport(delete_error=True, ack=b"CertI2\r"))
    service.save_lan_b_target("10.0.0.10", host="10.0.1.10", port=8443)
    approve(service, nic=2)
    result = service.activate_one(selector="10.0.0.10", certificate_id="cert-1", nic=2)
    service.save_lan_b_target("10.0.0.10", host="10.0.2.10", port=443)
    transport.delete_error = False
    assert service.cleanup_one(staged_name=result["staged_name"], confirm_finished=True)["status"] == "deleted"
    assert transport.deleted[-1][0].host == "10.0.1.10"


def test_disconnect_after_send_verifies_without_retrying(tmp_path):
    class Disconnect(FakeTransport):
        def ingest(self, *args, **kwargs):
            super().ingest(*args, **kwargs)
            raise OSError("disconnected")

    observations = []
    service, _, _, transport = make_service(tmp_path, transport=Disconnect(), verifier=lambda endpoint, material: (observations.append(endpoint) or VerificationResult("verified", "a", "a")))
    approve(service)
    result = service.activate_one(selector="10.0.0.10", certificate_id="cert-1")
    assert result["status"] == "cleanup_pending"
    assert result["verification"] == "verified"
    assert len(observations) == len(transport.sis_commands) == 1
    assert not transport.deleted


def test_transport_opens_shell_and_collects_fragmented_ack(monkeypatch):
    class Channel:
        def __init__(self):
            self.shell = False
            self.sent = False
            self.chunks = [b"Cert", b"I1\r"]

        def settimeout(self, value):
            pass

        def invoke_shell(self):
            self.shell = True

        def recv_ready(self):
            return self.sent and bool(self.chunks)

        def recv(self, size):
            return self.chunks.pop(0)

        def sendall(self, command):
            assert self.shell
            assert command == b"\x1bI1*certmon-test.pem CERT\r"
            self.sent = True

        def close(self):
            pass

    class Connection:
        def open_session(self, timeout):
            return channel

        def close(self):
            pass

    channel = Channel()
    transport = ParamikoDirectTransport()
    monkeypatch.setattr(transport, "_authenticated_transport", lambda *args: Connection())
    result = transport.ingest(EndpointIdentity("10.0.0.10", 1, "sis", "10.0.0.10", 22023), {}, b"\x1bI1*certmon-test.pem CERT\r", expected_fingerprint="SHA256:known")
    assert result.write_confirmed and result.received == b"CertI1\r"


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
    assert transport.sis_commands[0][1] == b"\x1bI2*" + transport.sftp_writes[0][1].encode("ascii") + b" CERT\r"
    assert verified[0]["host"] == "10.0.1.10"
    assert verified[0]["port"] == 8443
    assert transport.deleted
    assert transport.expected_fingerprints == ["SHA256:known"] * 3


@pytest.mark.parametrize("ack", [b"CertI2\r", b"CertI1", b"noise CertI2\r more"])
def test_wrong_or_ambiguous_ack_never_replays_sis(tmp_path, ack):
    transport = FakeTransport(ack=ack)
    service, _, _, transport = make_service(tmp_path, transport=transport)
    approve(service)

    result = service.activate_one(selector="10.0.0.10", certificate_id="cert-1", nic=1)

    assert result["status"] in {"ack_rejected", "cleanup_pending"}
    assert len(transport.sis_commands) == 1


def test_preloaded_ack_verifies_first_and_survives_restart_for_guarded_cleanup(tmp_path):
    class PreloadedTransport(FakeTransport):
        def ingest(self, identity, credentials, command, **kwargs):
            super().ingest(identity, credentials, command, **kwargs)
            return SISExchange(preloaded=b"CertI1\r", received=b"", write_confirmed=False)

    transport = PreloadedTransport()
    service, database, artifacts, transport = make_service(tmp_path, transport=transport)
    approve(service)

    result = service.activate_one(selector="10.0.0.10", certificate_id="cert-1", nic=1)

    assert result["status"] == "cleanup_pending"
    assert result["verification"] == "verified"
    assert transport.deleted == []
    restarted = DirectExtronService(database, artifacts, FakeVault(), transport=transport)
    pending = restarted.recover_staged()
    assert pending[0]["staged_name"] == result["staged_name"]
    assert restarted.cleanup_one(staged_name=result["staged_name"], confirm_finished=True)["status"] == "cleanup_pending"
    assert len(transport.sis_commands) == 1


def test_per_device_credentials_never_fall_back_after_authentication_failure(tmp_path):
    class RejectingTransport(FakeTransport):
        def probe_credentials(self, identity, credentials, **kwargs):
            super().probe_credentials(identity, credentials, **kwargs)
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
    direct_panel = html.split('id="direct-extron-upload"', 1)[1].split('id="toolbelt-batch"', 1)[0]

    for endpoint in ("probe", "host-keys/approve", "activate", "cleanup"):
        assert f"/api/direct-extron/{endpoint}" in html
        assert f"/api/direct-extron/{endpoint}" in app_source
    assert "LAN B HTTPS host" in direct_panel
    assert "combined_pem" not in direct_panel
    assert "private_key" not in direct_panel


def test_direct_routes_use_injected_service_and_reject_private_browser_fields(
    tmp_data_dir, monkeypatch
):
    import app

    module = importlib.reload(app)
    service = FakeRouteService()
    module.direct_extron_service = service
    module.artifact_store = object()
    module.vault = object()
    authorized = []
    monkeypatch.setattr(module, "authorize", lambda permission: authorized.append(permission))
    client = module.app.test_client()

    rejected = client.post(
        "/api/direct-extron/activate",
        json={"selector": "10.0.0.10", "certificate_id": "cert-1", "combined_pem": "secret"},
    )
    assert rejected.status_code == 400
    assert service.calls == []

    assert client.post("/api/direct-extron/probe", json={"selector": "10.0.0.10", "nic": 1}).get_json()["status"] == "ready"
    assert client.post("/api/direct-extron/host-keys/approve", json={"selector": "10.0.0.10", "nic": 1, "fingerprint": "SHA256:known"}).get_json()["status"] == "approved"
    activated = client.post("/api/direct-extron/activate", json={"selector": "10.0.0.10", "nic": 1, "certificate_id": "cert-1"})
    assert activated.status_code == 200
    assert "secret" not in activated.get_data(as_text=True)
    assert client.post("/api/direct-extron/cleanup", json={"staged_name": "certmon-safe.pem", "confirm_finished": True}).get_json()["status"] == "deleted"
    assert [name for name, _ in service.calls] == ["probe", "approve", "activate", "cleanup"]
    assert len(authorized) == 5


def test_direct_activation_uses_existing_server_auth_and_csrf_guards(
    tmp_data_dir, monkeypatch
):
    module = load_server_app(tmp_data_dir, monkeypatch)
    service = FakeRouteService()
    module.direct_extron_service = service
    module.artifact_store = object()
    module.vault = object()
    client = module.app.test_client()

    assert client.post("/api/direct-extron/activate", json={}).status_code == 401
    client.post(
        "/api/auth/setup-first-admin",
        json={"username": "admin", "password": "correct horse", "password_confirmation": "correct horse"},
    )
    assert client.post("/api/direct-extron/activate", json={}).status_code == 403
    status = client.get("/api/auth/status").get_json()
    response = client.post(
        "/api/direct-extron/activate",
        json={"selector": "10.0.0.10", "nic": 1, "certificate_id": "cert-1"},
        headers={status["csrf_header"]: status["csrf_token"]},
    )
    assert response.status_code == 200
    assert [name for name, _ in service.calls] == ["activate"]


def test_direct_upload_browser_starts_without_network_or_activation(page, live_certmon):
    from playwright.sync_api import expect

    certmon = live_certmon(server_mode=False)
    requests = []
    page.on("request", lambda request: requests.append(request.url))
    page.goto(certmon.base_url)
    page.wait_for_function("typeof switchTab === 'function'")
    page.evaluate("switchTab('upload')")
    expect(page.locator('#direct-extron-upload')).to_be_visible()
    expect(page.locator('#toolbelt-batch')).to_be_visible()
    expect(page.locator('#direct-extron-activate')).to_be_disabled()
    assert not any('/api/direct-extron/probe' in url or '/api/direct-extron/activate' in url for url in requests)
    page.screenshot(path=str(Path(__file__).parents[1] / '.tmp' / 'direct-upload-desktop.png'), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    expect(page.locator('#direct-extron-upload')).to_be_visible()
    bounds = page.locator('#direct-extron-upload').bounding_box()
    assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 390
    page.screenshot(path=str(Path(__file__).parents[1] / '.tmp' / 'direct-upload-mobile.png'), full_page=True)


def test_device_dialog_selects_direct_upload_without_typing_or_network(page, live_certmon):
    from playwright.sync_api import expect

    certmon = live_certmon(server_mode=False)
    certificate = {"certificate_id": "prepared-cert", "issuer_type": "local_ca", "profile": "extron-rsa", "identifiers": ["192.168.0.112"]}
    device = {"selector": "192.168.0.112", "certificate_id": "prepared-cert", "label": "DMP 128", "extron_ready": True, "selected": True}
    page.route('**/api/certificates/public', lambda route: route.fulfill(json=[certificate]))
    page.route('**/api/toolbelt/devices', lambda route: route.fulfill(json={"devices": [device]}))
    page.route('**/api/toolbelt/reset-upload-tab', lambda route: route.fulfill(json={"devices": [device]}))
    requests = []
    page.on('request', lambda request: requests.append(request.url))
    page.goto(certmon.base_url)
    page.wait_for_function("typeof openDeviceLocalCAModal === 'function'")
    page.evaluate("async () => { await loadAvailableCertificates(); openDeviceLocalCAModal('192.168.0.112', 'DMP 128', 'prepared-cert'); }")
    page.locator('#device-ca-use-existing').click()
    expect(page.locator('#direct-extron-selector')).to_have_value('192.168.0.112')
    expect(page.locator('#direct-extron-certificate')).to_have_value('prepared-cert')
    expect(page.locator('#direct-extron-certificate')).to_have_attribute('readonly', '')
    expect(page.locator('#direct-extron-activate')).to_be_disabled()
    assert not any('/api/direct-extron/probe' in url or '/api/direct-extron/activate' in url for url in requests)
