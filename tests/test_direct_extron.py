from contextlib import contextmanager
import importlib
import errno
from pathlib import Path

import pytest
import paramiko

from certmon.deployment import VerificationResult
from certmon.direct_extron import DirectConnectionError, DirectExtronService, EndpointIdentity, SISExchange, ParamikoDirectTransport
from tests.test_auth_api import load_app as load_server_app


class FakeDatabase:
    def __init__(self):
        self.settings = {}
        self.secrets = {}
        self.audit_events = []
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

    def record_audit_event(self, **event):
        self.audit_events.append(event)

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
        return {"transfer_verified": True, "remote_size": Path(local_path).stat().st_size}

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

    def remove_certificate(self, **kwargs):
        self.calls.append(("remove", kwargs))
        return {"status": "removal_acknowledged", "nic": kwargs["nic"]}

    def cleanup_one(self, **kwargs):
        self.calls.append(("cleanup", kwargs))
        return {"status": "deleted", "staged_name": kwargs["staged_name"]}

    def recover_staged(self):
        return []


@pytest.mark.parametrize("port", [22022, 22023])
@pytest.mark.parametrize("error,reason", [
    (TimeoutError("sensitive diagnostic"), "timed out"),
    (ConnectionRefusedError("sensitive diagnostic"), "refused"),
    (paramiko.SSHException("sensitive diagnostic"), "SSH negotiation failed"),
])
def test_host_key_network_failure_is_safe_and_prevents_authentication(tmp_path, port, error, reason):
    class UnreachableTransport(FakeTransport):
        def host_key_fingerprint(self, identity):
            if identity.port == port:
                raise error
            return super().host_key_fingerprint(identity)

    service, database, artifacts, transport = make_service(tmp_path, transport=UnreachableTransport())
    with pytest.raises(DirectConnectionError) as failure:
        service.probe_one(selector="10.0.0.10")
    assert f"10.0.0.10:{port}" in str(failure.value)
    assert reason in str(failure.value)
    assert "sensitive diagnostic" not in str(failure.value)
    assert transport.auth_attempts == []
    assert artifacts.materializations == 0
    assert database.settings == {}


@pytest.mark.parametrize("endpoint,method", [
    ("probe", "probe_one"), ("host-keys/approve", "approve_host_key"), ("activate", "activate_one"),
])
def test_host_key_network_failure_routes_return_json(tmp_data_dir, monkeypatch, endpoint, method):
    import app

    module = importlib.reload(app)
    service = FakeRouteService()
    def fail(**kwargs):
        raise DirectConnectionError(EndpointIdentity("10.0.0.10", 1, "sis", "10.0.0.10", 22023), "connection refused")
    monkeypatch.setattr(service, method, fail)
    module.direct_extron_service = service
    module.artifact_store = object()
    module.vault = object()
    monkeypatch.setattr(module, "authorize", lambda permission: None)
    response = module.app.test_client().post(f"/api/direct-extron/{endpoint}", json={"selector": "10.0.0.10"})
    assert response.status_code == 502
    assert response.is_json
    assert response.get_json()["status"] == "connection_failed"
    assert "10.0.0.10:22023" in response.get_json()["error"]


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


class CertificateRemovalTransport(FakeTransport):
    def __init__(self, *, delete_reply=None, view_reply=None):
        super().__init__()
        self.delete_reply = delete_reply
        self.view_reply = view_reply

    def certificate_command(self, identity, credentials, command, **kwargs):
        self.auth_attempts.append((identity, credentials))
        self.sis_commands.append((identity, command))
        if kwargs["response_kind"] == "delete":
            return self.delete_reply if self.delete_reply is not None else f"CertX{identity.nic}\r\r\n".encode()
        return self.view_reply if self.view_reply is not None else b'{"C":"test-default"}\r\n'


@pytest.mark.parametrize("nic", [1, 2])
def test_certificate_removal_targets_one_interface_and_preserves_artifacts(tmp_path, nic):
    service, database, artifacts, transport = make_service(tmp_path, transport=CertificateRemovalTransport())
    if nic == 2:
        service.save_lan_b_target("10.0.0.10", host="10.0.1.10")
    approve(service, nic=nic)
    result = service.remove_certificate(selector="10.0.0.10", nic=nic, confirm_delete=True)
    assert result["status"] == "removal_acknowledged"
    assert result["certificate_information"] == {"C": "test-default"}
    assert [command for _, command in transport.sis_commands] == [f"\x1bX{nic}CERT\r".encode(), f"\x1bV{nic}CERT\r".encode()]
    assert all(identity.nic == nic and identity.host == ("10.0.0.10" if nic == 1 else "10.0.1.10") for identity, _ in transport.sis_commands)
    assert artifacts.has_certificate("cert-1") and artifacts.materializations == 0
    assert transport.sftp_writes == [] and transport.deleted == []
    assert database.get_setting(service.STAGED_KEY, {}) == {}


@pytest.mark.parametrize("confirmation,nic", [(False, 1), ("true", 1), (True, True), (True, "1"), (True, 3)])
def test_certificate_removal_requires_strict_confirmation_and_nic(tmp_path, confirmation, nic):
    service, _, _, transport = make_service(tmp_path, transport=CertificateRemovalTransport())
    with pytest.raises(ValueError):
        service.remove_certificate(selector="10.0.0.10", nic=nic, confirm_delete=confirmation)
    assert transport.sis_commands == [] and transport.probes == []


def test_certificate_mutations_cannot_overlap(tmp_path):
    service, _, _, transport = make_service(tmp_path, transport=CertificateRemovalTransport())
    with service._certificate_operation():
        with pytest.raises(ValueError, match='already running'):
            service.remove_certificate(selector='10.0.0.10', nic=1, confirm_delete=True)
        with pytest.raises(ValueError, match='already running'):
            service.activate_one(selector='10.0.0.10', certificate_id='cert-1')
    assert transport.sis_commands == [] and transport.probes == []
    with pytest.raises(ValueError):
        service.remove_certificate(selector='10.0.0.10', nic=1, confirm_delete=False)
    assert service.remove_certificate(selector='10.0.0.10', nic=1, confirm_delete=True)['status'] == 'approval_required'


@pytest.mark.parametrize("reply", [b"", b"CertX2\r\n", b"CertX1\r\nCertX1\r\n", b"E13\r\n"])
def test_certificate_removal_does_not_replay_or_claim_success_for_invalid_ack(tmp_path, reply):
    service, _, _, transport = make_service(tmp_path, transport=CertificateRemovalTransport(delete_reply=reply))
    approve(service)
    result = service.remove_certificate(selector="10.0.0.10", nic=1, confirm_delete=True)
    assert result["status"] == "removal_unconfirmed"
    assert len(transport.sis_commands) == 2


@pytest.mark.parametrize("reply", [b"", b"E13\r\n", b'CertV2{"C":"US"}\r\n', b'{}\r\n', b'{"C":"US"}\r\nnoise\r\n'])
def test_certificate_removal_reports_unrecognized_readback_without_guessing(tmp_path, reply):
    service, _, _, transport = make_service(tmp_path, transport=CertificateRemovalTransport(view_reply=reply))
    approve(service)
    result = service.remove_certificate(selector="10.0.0.10", nic=1, confirm_delete=True)
    assert result["status"] == "removal_acknowledged"
    assert "certificate_information" not in result
    assert len(transport.sis_commands) == 2


def test_certificate_removal_blocks_pending_uploads_and_unapproved_keys(tmp_path):
    service, database, _, transport = make_service(tmp_path, transport=CertificateRemovalTransport())
    assert service.remove_certificate(selector="10.0.0.10", nic=1, confirm_delete=True)["status"] == "approval_required"
    assert transport.sis_commands == []
    approve(service)
    service._record_staged("certmon-pending.pem", service.target_for("10.0.0.10"), "cert-1")
    with pytest.raises(ValueError, match="pending"):
        service.remove_certificate(selector="10.0.0.10", nic=1, confirm_delete=True)
    assert transport.sis_commands == []
    database.put_setting(service.STAGED_KEY, {})
    transport.key = "SHA256:changed"
    assert service.remove_certificate(selector="10.0.0.10", nic=1, confirm_delete=True)["status"] == "host_key_changed"
    assert transport.sis_commands == []


def test_certificate_readback_accepts_exact_echo_and_verbose_prefix():
    command = b"\x1bV1CERT\r"
    exchange = SISExchange(b"", b'^[V1CERT\r\nCertV1{"C":"US"}\r\r\n', True)
    assert DirectExtronService._certificate_information(exchange, 1, command) == {"C": "US"}
    assert DirectExtronService._certificate_information(SISExchange(b"CertV1", exchange.received, True), 1, command) is None


@pytest.mark.parametrize("kind,chunks,expected", [
    ("delete", [b'^[X1CERT\r\n', b'CertX1\r\r\n'], b'^[X1CERT\r\nCertX1\r\r\n'),
    ("view", [b'^[V1CERT\r\n', b'CertV1{"C":', b'"US"}\r\r\n'], b'^[V1CERT\r\nCertV1{"C":"US"}\r\r\n'),
])
def test_certificate_command_reader_waits_past_echo_for_complete_reply(kind, chunks, expected):
    class Channel:
        def recv_ready(self):
            return bool(chunks)

        def recv(self, size):
            return chunks.pop(0)
    assert ParamikoDirectTransport()._read_response(Channel(), response_kind=kind) == expected


def test_certificate_removal_keeps_acknowledgement_after_readback_disconnect(tmp_path):
    class DisconnectingTransport(CertificateRemovalTransport):
        def certificate_command(self, identity, credentials, command, **kwargs):
            if kwargs['response_kind'] == 'view':
                raise OSError('Disconnected')
            return super().certificate_command(identity, credentials, command, **kwargs)
    service, _, _, transport = make_service(tmp_path, transport=DisconnectingTransport())
    approve(service)
    result = service.remove_certificate(selector='10.0.0.10', nic=1, confirm_delete=True)
    assert result['status'] == 'removal_acknowledged'
    assert result['response'] == 'transport_interrupted'
    assert len(transport.sis_commands) == 1


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
            self.terminal = False
            self.sent = False
            self.chunks = [b"Cert", b"I1\r"]

        def settimeout(self, value):
            pass

        def invoke_shell(self):
            assert self.terminal
            self.shell = True

        def get_pty(self, term):
            assert term == "vt100"
            self.terminal = True

        def recv_ready(self):
            return self.sent and bool(self.chunks)

        def recv(self, size):
            return self.chunks.pop(0)

        def sendall(self, command):
            assert self.shell
            assert command == b"\x1bI1*certmon-test.pemCERT\r"
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
    result = transport.ingest(EndpointIdentity("10.0.0.10", 1, "sis", "10.0.0.10", 22023), {}, b"\x1bI1*certmon-test.pemCERT\r", expected_fingerprint="SHA256:known")
    assert result.write_confirmed and result.received == b"CertI1\r"


def test_sis_reply_after_five_seconds_is_collected_without_resending(monkeypatch):
    elapsed = [0.0]
    monkeypatch.setattr("certmon.direct_extron.time.monotonic", lambda: elapsed[0])
    monkeypatch.setattr("certmon.direct_extron.time.sleep", lambda duration: elapsed.__setitem__(0, elapsed[0] + duration))
    class LateChannel:
        def recv_ready(self):
            return elapsed[0] >= 6
        def recv(self, size):
            return b"CertI1\r"
    transport = ParamikoDirectTransport()
    assert transport._read_response(LateChannel()) == b"CertI1\r"
    assert 6 <= elapsed[0] < 7


def test_sis_missing_reply_has_bounded_wait(monkeypatch):
    elapsed = [0.0]
    monkeypatch.setattr("certmon.direct_extron.time.monotonic", lambda: elapsed[0])
    monkeypatch.setattr("certmon.direct_extron.time.sleep", lambda duration: elapsed.__setitem__(0, elapsed[0] + duration))
    class SilentChannel:
        def recv_ready(self):
            return False
    assert ParamikoDirectTransport()._read_response(SilentChannel()) == b""
    assert 30 <= elapsed[0] < 31


def test_sis_reader_continues_past_command_echo(monkeypatch):
    elapsed = [0.0]
    monkeypatch.setattr("certmon.direct_extron.time.monotonic", lambda: elapsed[0])
    monkeypatch.setattr("certmon.direct_extron.time.sleep", lambda duration: elapsed.__setitem__(0, elapsed[0] + duration))
    class EchoChannel:
        chunks = [b"^[I1*certmon.pemCERT\r\n", b"Cert", b"I1\r\n"]
        def recv_ready(self):
            return bool(self.chunks)
        def recv(self, size):
            return self.chunks.pop(0)
    result = ParamikoDirectTransport()._read_response(EchoChannel())
    assert result == b"^[I1*certmon.pemCERT\r\nCertI1\r\n"


@pytest.mark.parametrize("echo", [b"\x1b", b"^["])
def test_exact_command_echo_then_ack_and_https_complete_upload(tmp_path, echo):
    class EchoTransport(FakeTransport):
        def ingest(self, identity, credentials, command, **kwargs):
            super().ingest(identity, credentials, command, **kwargs)
            return command[:-1].replace(b"\x1b", echo) + b"\r\nCertI1\r\n"
    service, _, _, transport = make_service(tmp_path, transport=EchoTransport())
    approve(service)
    result = service.activate_one(selector="10.0.0.10", certificate_id="cert-1")
    assert result["status"] == "verified"
    assert len(transport.sis_commands) == 1
    assert len(transport.deleted) == 1
    assert result["sftp_diagnostics"]["transfer_verified"] is True


@pytest.mark.parametrize("response", [
    b"^[I1*certmon.pemCERT\r\n",
    b"^[I1*other.pemCERT\r\nCertI1\r\n",
    b"^[I1*certmon.pemCERT\r\nCertI2\r\n",
    b"noise\r\nCertI1\r\n",
    b"^[I1*certmon.pemCERT\r\nCertI1\r\nCertI1\r\n",
])
def test_echo_without_exact_unambiguous_ack_never_counts_as_success(response):
    assert not DirectExtronService._exact_ack(response, 1, b"\x1bI1*certmon.pemCERT\r")


def test_sw4_recorded_terminal_reply_is_valid():
    command = b"\x1bI1*certmon-a04907d3bd3f498387185e9a0bd405bd.pemCERT\r"
    reply = b"^[I1*certmon-a04907d3bd3f498387185e9a0bd405bd.pemCERT\r\nCertI1\r\r\n"
    assert DirectExtronService._exact_ack(reply, 1, command)


@pytest.mark.parametrize("error_code", [errno.ENOENT, errno.EACCES, errno.EIO])
def test_cleanup_accepts_only_already_absent_file(tmp_path, monkeypatch, error_code):
    from types import SimpleNamespace

    closed = []
    class SFTP:
        def get_channel(self):
            return SimpleNamespace(settimeout=lambda timeout: None)
        def remove(self, name):
            raise OSError(error_code, "test SFTP error")
        def close(self):
            closed.append("sftp")
    transport = ParamikoDirectTransport()
    monkeypatch.setattr(transport, "_authenticated_transport", lambda *args: SimpleNamespace(close=lambda: closed.append("transport")))
    monkeypatch.setattr(paramiko.SFTPClient, "from_transport", lambda connection: SFTP())
    identity = EndpointIdentity("10.0.0.10", 1, "sftp", "10.0.0.10", 22022)
    if error_code == errno.ENOENT:
        transport.delete(identity, {}, "certmon.pem", expected_fingerprint="SHA256:known")
    else:
        with pytest.raises(OSError) as failure:
            transport.delete(identity, {}, "certmon.pem", expected_fingerprint="SHA256:known")
        assert failure.value.errno == error_code
    assert closed == ["sftp", "transport"]


@pytest.mark.parametrize("ending", [b"\r\r\n", b"\r\r"])
def test_terminal_ack_preserves_exact_nic_and_single_response(ending):
    command = b"\x1bI1*certmon.pemCERT\r"
    echo = b"^[I1*certmon.pemCERT\r\n"
    assert DirectExtronService._exact_ack(echo + b"CertI1" + ending, 1, command)
    assert not DirectExtronService._exact_ack(echo + b"CertI2" + ending, 1, command)
    assert not DirectExtronService._exact_ack(echo + b"CertI1\r\nCertI1" + ending, 1, command)


def test_confirmed_import_waits_for_https_switch_without_reupload(tmp_path, monkeypatch):
    elapsed = [0.0]
    monkeypatch.setattr("certmon.direct_extron.time.monotonic", lambda: elapsed[0])
    monkeypatch.setattr("certmon.direct_extron.time.sleep", lambda duration: elapsed.__setitem__(0, elapsed[0] + duration))
    observations = []
    def verifier(endpoint, material):
        observations.append(endpoint)
        status = ["different_certificate", "unreachable", "verified"][len(observations) - 1]
        return VerificationResult(status, "expected", "expected" if status == "verified" else "old")
    service, _, _, transport = make_service(tmp_path, verifier=verifier)
    approve(service)
    result = service.activate_one(selector="10.0.0.10", certificate_id="cert-1")
    assert result["status"] == "verified"
    assert elapsed[0] == 2
    assert len(observations) == 3
    assert len(transport.sftp_writes) == len(transport.sis_commands) == len(transport.deleted) == 1


def test_https_switch_timeout_is_not_success_and_never_replays_import(tmp_path, monkeypatch):
    elapsed = [0.0]
    monkeypatch.setattr("certmon.direct_extron.time.monotonic", lambda: elapsed[0])
    monkeypatch.setattr("certmon.direct_extron.time.sleep", lambda duration: elapsed.__setitem__(0, elapsed[0] + duration))
    service, _, _, transport = make_service(tmp_path, verifier=lambda *args: VerificationResult("different_certificate", "expected", "old"))
    service.verification_timeout = 3
    approve(service)
    result = service.activate_one(selector="10.0.0.10", certificate_id="cert-1")
    assert result["status"] == "cleanup_pending"
    assert result["verification"] == "different_certificate"
    assert service.recover_staged()[0]["known_completion"] is True
    assert elapsed[0] == 3
    assert len(transport.sftp_writes) == len(transport.sis_commands) == 1
    assert not transport.deleted


@pytest.mark.parametrize("remote_size", [8, 9])
def test_sftp_stage_confirms_remote_file_size_before_import(tmp_path, monkeypatch, remote_size):
    from types import SimpleNamespace

    pem = tmp_path / "combined.pem"
    pem.write_bytes(b"test PEM")
    calls = []
    class SFTP:
        def get_channel(self):
            return SimpleNamespace(settimeout=lambda timeout: None)
        def put(self, local, remote, confirm):
            calls.append((local, remote, confirm))
            return SimpleNamespace(st_size=remote_size)
        def close(self):
            pass
    transport = ParamikoDirectTransport()
    monkeypatch.setattr(transport, "_authenticated_transport", lambda *args: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(paramiko.SFTPClient, "from_transport", lambda connection: SFTP())
    if remote_size == 8:
        result = transport.stage(EndpointIdentity("10.0.0.10", 1, "sftp", "10.0.0.10", 22022), {}, pem, "certmon.pem", expected_fingerprint="SHA256:known")
        assert result == {"transfer_verified": True, "remote_size": 8}
    else:
        with pytest.raises(OSError, match="size did not match"):
            transport.stage(EndpointIdentity("10.0.0.10", 1, "sftp", "10.0.0.10", 22022), {}, pem, "certmon.pem", expected_fingerprint="SHA256:known")
    assert calls == [(str(pem), "certmon.pem", True)]


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
    assert transport.sis_commands[0][1] == b"\x1bI2*" + transport.sftp_writes[0][1].encode("ascii") + b"CERT\r"
    assert verified[0]["host"] == "10.0.1.10"
    assert verified[0]["port"] == 8443
    assert transport.deleted
    assert transport.expected_fingerprints == ["SHA256:known"] * 3


@pytest.mark.parametrize("nic", [1, 2])
def test_sis_import_matches_confirmed_putty_command_without_spaces(nic):
    assert DirectExtronService._sis_command(nic, "certmon.pem") == f"\x1bI{nic}*certmon.pemCERT\r".encode("ascii")


@pytest.mark.parametrize("ack", [b"CertI2\r", b"CertI1", b"noise CertI2\r more"])
def test_wrong_or_ambiguous_ack_never_replays_sis(tmp_path, ack):
    transport = FakeTransport(ack=ack)
    service, _, _, transport = make_service(tmp_path, transport=transport)
    approve(service)

    result = service.activate_one(selector="10.0.0.10", certificate_id="cert-1", nic=1)

    assert result["status"] in {"ack_rejected", "cleanup_pending"}
    assert len(transport.sis_commands) == 1
    assert result["response"] == "ack_rejected"
    assert service.recover_staged()[0]["response"] == "ack_rejected"
    assert service.recover_staged()[0]["verification"] == result["verification"]
    assert result["sis_diagnostics"]["received"] == repr(ack)
    assert result["sis_diagnostics"]["write_confirmed"] is True
    assert service.recover_staged()[0]["sis_diagnostics"] == result["sis_diagnostics"]


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


def test_permission_error_does_not_retry_other_credentials(tmp_path):
    class RejectingTransport(FakeTransport):
        def probe_credentials(self, identity, credentials, **kwargs):
            super().probe_credentials(identity, credentials, **kwargs)
            raise PermissionError("bad password")

    transport = RejectingTransport()
    service, _, _, transport = make_service(tmp_path, transport=transport)
    service.save_credentials("10.0.0.10", username="operator", password="device-secret")
    approve(service)

    result = service.probe_one(selector="10.0.0.10", nic=1)

    assert result["status"] == "authentication_failed"
    assert result["identity"]["port"] == 22022
    assert len(transport.auth_attempts) == 1
    assert transport.auth_attempts[0][1]["username"] == "operator"
    assert "secret" not in repr(result)


@pytest.mark.parametrize('accepted', ['device-secret', 'shared-secret', 'extron', None])
def test_direct_probe_tries_individual_shared_then_default(tmp_path, accepted):
    class RejectingTransport(FakeTransport):
        def probe_credentials(self, identity, credentials, **kwargs):
            super().probe_credentials(identity, credentials, **kwargs)
            if credentials['password'] != accepted:
                raise paramiko.AuthenticationException('rejected')

    service, _, _, transport = make_service(tmp_path, transport=RejectingTransport())
    service.save_credentials('10.0.0.10', username='operator', password='device-secret')
    result = service.probe_one(selector='10.0.0.10', auto_first_use=True)
    expected = [('operator', 'device-secret'), ('admin', 'shared-secret'), ('admin', 'extron')]
    if accepted:
        expected = expected[:next(i for i, (_, p) in enumerate(expected) if p == accepted) + 1]
    attempts = [(c['username'], c['password']) for _, c in transport.auth_attempts]
    assert attempts == expected * (2 if accepted else 1)
    assert result['status'] == ('ready' if accepted else 'authentication_failed')
    assert 'secret' not in repr(result)


def test_direct_upload_fallback_does_not_repeat_import_after_authentication(tmp_path):
    class DefaultOnlyTransport(FakeTransport):
        def probe_credentials(self, identity, credentials, **kwargs):
            super().probe_credentials(identity, credentials, **kwargs)
            if credentials['password'] != 'extron':
                raise paramiko.AuthenticationException('rejected')

        def stage(self, identity, credentials, *args, **kwargs):
            if credentials['password'] != 'extron':
                self.auth_attempts.append((identity, credentials))
                raise paramiko.AuthenticationException('rejected')
            return super().stage(identity, credentials, *args, **kwargs)

        def ingest(self, identity, credentials, *args, **kwargs):
            if credentials['password'] != 'extron':
                self.auth_attempts.append((identity, credentials))
                raise paramiko.AuthenticationException('rejected')
            return super().ingest(identity, credentials, *args, **kwargs)

    service, _, _, transport = make_service(tmp_path, transport=DefaultOnlyTransport())
    service.save_credentials('10.0.0.10', username='admin', password='device-secret')
    assert service.probe_one(selector='10.0.0.10', auto_first_use=True)['status'] == 'ready'
    transport.auth_attempts.clear()
    assert service.activate_one(selector='10.0.0.10', certificate_id='cert-1')['status'] == 'verified'
    assert len(transport.sis_commands) == 1
    assert len(transport.sftp_writes) == 1
    for connection in ('sftp', 'sis'):
        passwords = [c['password'] for identity, c in transport.auth_attempts if identity.connection == connection]
        assert passwords[:3] == ['device-secret', 'shared-secret', 'extron']


@pytest.mark.parametrize('failure', [OSError('offline'), PermissionError('denied')])
def test_direct_connection_or_permission_failure_does_not_try_next_password(tmp_path, failure):
    class BrokenTransport(FakeTransport):
        def probe_credentials(self, identity, credentials, **kwargs):
            super().probe_credentials(identity, credentials, **kwargs)
            raise failure

    service, _, _, transport = make_service(tmp_path, transport=BrokenTransport())
    service.save_credentials('10.0.0.10', username='admin', password='individual')
    result = service.probe_one(selector='10.0.0.10', auto_first_use=True)
    assert result['status'] in ('connection_failed', 'authentication_failed')
    assert len(transport.auth_attempts) == 1


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
    assert 'id="direct-extron-interface"' in direct_panel
    assert "Save LAN B endpoint" not in direct_panel
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


@pytest.mark.parametrize("endpoint,body,call", [
    ("activate", {"selector": "10.0.0.10", "nic": 1, "certificate_id": "cert-1"}, "activate"),
    ("certificate/delete", {"selector": "10.0.0.10", "nic": 1, "confirm_delete": True}, "remove"),
])
def test_direct_activation_uses_existing_server_auth_and_csrf_guards(
    tmp_data_dir, monkeypatch, endpoint, body, call
):
    module = load_server_app(tmp_data_dir, monkeypatch)
    service = FakeRouteService()
    module.direct_extron_service = service
    module.artifact_store = object()
    module.vault = object()
    client = module.app.test_client()

    assert client.post(f"/api/direct-extron/{endpoint}", json={}).status_code == 401
    client.post(
        "/api/auth/setup-first-admin",
        json={"username": "admin", "password": "correct horse", "password_confirmation": "correct horse"},
    )
    assert client.post(f"/api/direct-extron/{endpoint}", json={}).status_code == 403
    status = client.get("/api/auth/status").get_json()
    response = client.post(
        f"/api/direct-extron/{endpoint}",
        json=body,
        headers={status["csrf_header"]: status["csrf_token"]},
    )
    assert response.status_code == 200
    assert [name for name, _ in service.calls] == [call]


def test_direct_upload_browser_starts_without_network_or_activation(page, live_certmon):
    from playwright.sync_api import expect

    certmon = live_certmon(server_mode=False)
    requests = []
    page.on("request", lambda request: requests.append(request.url))
    page.goto(certmon.base_url)
    page.wait_for_function("typeof switchTab === 'function'")
    page.evaluate("switchTab('upload')")
    expect(page.locator('#direct-extron-upload')).not_to_be_visible()
    expect(page.locator('#toolbelt-batch')).to_be_visible()
    page.evaluate("document.getElementById('direct-extron-upload').showModal()")
    expect(page.locator('#direct-extron-activate')).to_be_disabled()
    expect(page.locator('#direct-extron-activate')).to_have_text('Upload certificate')
    buttons = page.locator('#direct-extron-upload button')
    expect(buttons.last).to_have_text('Delete certificate...')
    expect(page.get_by_role('button', name='Save LAN B endpoint', exact=True)).to_have_count(0)
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


def test_direct_upload_success_has_collapsed_safe_diagnostics(page, live_certmon):
    from playwright.sync_api import expect

    certmon = live_certmon(server_mode=False)
    page.route('**/api/direct-extron/activate', lambda route: route.fulfill(json={
        "status": "verified", "verification": "verified",
        "sftp_diagnostics": {"remote_size": 3375},
        "sis_diagnostics": {"write_confirmed": True, "received": "<script>unexpected</script>", "preloaded": "b''"},
    }))
    page.on('dialog', lambda dialog: dialog.accept())
    page.goto(certmon.base_url)
    page.wait_for_function("typeof switchTab === 'function'")
    page.evaluate("switchTab('upload'); document.getElementById('direct-extron-upload').showModal()")
    page.evaluate("async () => { directExtronReady = JSON.stringify(directExtronFields()); await activateDirectExtron(); }")
    status = page.locator('#direct-extron-status')
    expect(status).to_contain_text('Certificate uploaded and verified.')
    expect(status.locator('summary')).to_have_text('Technical details')
    expect(status.locator('details')).not_to_have_attribute('open', '')
    expect(status.locator('details div')).not_to_be_visible()
    expect(status.locator('script')).to_have_count(0)
    status.locator('summary').click()
    expect(status.locator('details div')).to_be_visible()
    expect(status.locator('details div')).to_contain_text('3375 bytes')
    page.evaluate("setDirectExtronStatus('Checking connection...')")
    expect(status.locator('details')).to_have_count(0)


def test_device_certificate_delete_dialog_requires_confirmation_and_selects_lan_b(page, live_certmon):
    from playwright.sync_api import expect

    certmon = live_certmon(server_mode=False)
    removals = []
    certificate = {"certificate_id": "prepared-cert", "issuer_type": "local_ca", "profile": "extron-rsa", "identifiers": ["10.0.0.10"]}
    device = {"selector": "10.0.0.10", "certificate_id": "prepared-cert", "label": "UCS 303", "extron_ready": True, "selected": True}
    page.route('**/api/certificates/public', lambda route: route.fulfill(json=[certificate]))
    page.route('**/api/toolbelt/devices', lambda route: route.fulfill(json={"devices": [device]}))
    page.route('**/api/toolbelt/reset-upload-tab', lambda route: route.fulfill(json={"devices": [device]}))
    page.route('**/api/direct-extron/target?*', lambda route: route.fulfill(json={"target": {"host": "10.0.1.10"}}))
    def remove(route):
        removals.append(route.request.post_data_json)
        route.fulfill(json={"status": "removal_acknowledged", "certificate_information": {"C": "test-default"}})
    page.route('**/api/direct-extron/certificate/delete', remove)
    page.goto(certmon.base_url)
    page.wait_for_function("typeof switchTab === 'function'")
    page.evaluate("""async () => {
      switchTab('upload');
      await loadAvailableCertificates();
      await loadToolbeltDevices(false);
      selectPreparedDirectDevice('10.0.0.10');
    }""")
    page.locator('#direct-extron-delete').click()
    expect(page.locator('#direct-extron-delete-dialog')).to_be_visible()
    expect(page.locator('#direct-extron-delete-device')).to_have_text('UCS 303 (10.0.0.10)')
    assert removals == []
    page.locator('#direct-extron-delete-dialog button').filter(has_text='Cancel').click()
    assert removals == []
    page.locator('#direct-extron-delete').click()
    page.locator('#direct-extron-delete-nic').select_option('2')
    confirmations = []
    def accept(dialog):
        confirmations.append(dialog.message)
        dialog.accept()
    page.on('dialog', accept)
    page.locator('#direct-extron-delete-confirm').click()
    expect(page.locator('#direct-extron-status')).to_contain_text('Device confirmed certificate removal on LAN B')
    assert removals == [{"selector": "10.0.0.10", "nic": 2, "confirm_delete": True}]
    assert 'LAN B (10.0.1.10)' in confirmations[0]
    assert 'CertMon will be kept' in confirmations[0]
    expect(page.locator('#direct-extron-activate')).to_be_disabled()


@pytest.mark.parametrize("body", [[], {"selector": []}, {"selector": "10.0.0.10", "nic": 1, "confirm_delete": True, "pem": "secret"}])
def test_certificate_delete_route_rejects_invalid_json_and_private_material(tmp_data_dir, monkeypatch, body):
    import app

    module = importlib.reload(app)
    service = FakeRouteService()
    module.direct_extron_service = service
    module.artifact_store = object()
    module.vault = object()
    monkeypatch.setattr(module, 'authorize', lambda permission: None)
    response = module.app.test_client().post('/api/direct-extron/certificate/delete', json=body)
    assert response.status_code == 400
    assert service.calls == []


def test_viewer_cannot_delete_device_certificate(tmp_data_dir, monkeypatch):
    from tests.test_rbac import create_viewer, auth_headers

    module = load_server_app(tmp_data_dir, monkeypatch)
    service = FakeRouteService()
    module.direct_extron_service = service
    module.artifact_store = object()
    module.vault = object()
    client = create_viewer(module)
    response = client.post('/api/direct-extron/certificate/delete',
                           json={"selector": "10.0.0.10", "nic": 1, "confirm_delete": True},
                           headers=auth_headers(client))
    assert response.status_code == 403
    assert service.calls == []


def test_direct_probe_html_error_has_actionable_message_and_no_upload(page, live_certmon):
    from playwright.sync_api import expect

    certmon = live_certmon(server_mode=False)
    page.route('**/api/direct-extron/probe', lambda route: route.fulfill(status=500, content_type='text/html', body='<!doctype html><title>Server error</title>'))
    page.goto(certmon.base_url)
    page.wait_for_function("typeof switchTab === 'function'")
    page.evaluate("switchTab('upload'); document.getElementById('direct-extron-upload').showModal()")
    page.locator('button[onclick="probeDirectExtron()"]').click()
    expect(page.locator('#direct-extron-status')).to_contain_text('HTTP 500')
    expect(page.locator('#direct-extron-status')).to_contain_text('Check the CertMon log')
    expect(page.locator('#direct-extron-activate')).to_be_disabled()
    expect(page.locator('#direct-extron-approve')).to_be_disabled()


def test_host_key_approval_continues_test_without_extra_test_clicks(page, live_certmon):
    from playwright.sync_api import expect

    certmon = live_certmon(server_mode=False)
    probes = []
    approvals = []
    def probe(route):
        probes.append(route.request.post_data_json)
        if len(probes) <= 2:
            connection, port = ('sftp', 22022) if len(probes) == 1 else ('sis', 22023)
            route.fulfill(json={"status": "approval_required", "fingerprint": f"SHA256:{connection}", "identity": {"connection": connection, "host": "10.0.0.10", "port": port}})
        else:
            route.fulfill(json={"status": "ready"})
    def approve_key(route):
        approvals.append(route.request.post_data_json)
        route.fulfill(json={"status": "approved", "fingerprint": approvals[-1]["fingerprint"]})
    page.route('**/api/direct-extron/probe', probe)
    page.route('**/api/direct-extron/host-keys/approve', approve_key)
    page.goto(certmon.base_url)
    page.wait_for_function("typeof switchTab === 'function'")
    page.evaluate("switchTab('upload'); document.getElementById('direct-extron-upload').showModal()")
    page.locator('button[onclick="probeDirectExtron()"]').click()
    expect(page.locator('#direct-extron-status')).to_contain_text('SFTP 10.0.0.10:22022')
    expect(page.locator('#direct-extron-status')).to_contain_text('testing continues automatically')
    page.locator('#direct-extron-approve').click()
    expect(page.locator('#direct-extron-status')).to_contain_text('SIS 10.0.0.10:22023')
    assert len(approvals) == 1
    page.locator('#direct-extron-approve').click()
    expect(page.locator('#direct-extron-status')).to_contain_text('sign-in successful')
    assert len(probes) == 3
    assert [item['connection'] for item in approvals] == ['sftp', 'sis']


def test_sis_authentication_failure_reports_the_correct_port(tmp_path):
    class RejectingSISTransport(FakeTransport):
        def probe_credentials(self, identity, credentials, **kwargs):
            super().probe_credentials(identity, credentials, **kwargs)
            if identity.connection == "sis":
                raise PermissionError("bad password")
    service, _, _, transport = make_service(tmp_path, transport=RejectingSISTransport())
    approve(service)
    result = service.probe_one(selector="10.0.0.10")
    assert result["status"] == "authentication_failed"
    assert result["identity"]["connection"] == "sis"
    assert result["identity"]["port"] == 22023
    assert len(transport.auth_attempts) == 2
