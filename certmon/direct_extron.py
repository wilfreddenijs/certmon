"""Pinned, one-device Extron certificate delivery primitives.

The browser supplies identifiers only. Credentials and combined PEM material stay
inside this module and every network operation starts after an exact host-key
approval for its endpoint identity.
"""

import hashlib
import errno
import json
import re
import socket
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import paramiko
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from certmon.deployment import DeploymentMaterial, verify_device_certificate
from certmon.toolbelt import DEFAULT_SECRET_ID, SECRET_PREFIX, SECRET_PURPOSE


LAN_B_TARGETS_KEY = "direct_extron_lan_b_targets"
HOST_KEYS_KEY = "direct_extron_host_keys"
STAGED_KEY = "direct_extron_staged_pems"


@dataclass(frozen=True)
class EndpointIdentity:
    selector: str
    nic: int
    connection: str
    host: str
    port: int

    def key(self):
        return "|".join((self.selector, str(self.nic), self.connection, self.host, str(self.port)))

    def device(self):
        return {"host": self.host, "port": self.port}


@dataclass(frozen=True)
class DirectTarget:
    sftp: EndpointIdentity
    sis: EndpointIdentity
    https: EndpointIdentity


@dataclass(frozen=True)
class SISExchange:
    preloaded: bytes
    received: bytes
    write_confirmed: bool


class HostKeyChangedError(RuntimeError):
    pass


class DirectConnectionError(ValueError):
    def __init__(self, identity, reason):
        self.identity = identity
        super().__init__(f"{identity.connection.upper()} connection to {identity.host}:{identity.port} failed: {reason}")


class ParamikoDirectTransport:
    """One fresh Paramiko transport per direct connection, with bounded I/O."""

    def __init__(self, *, connect_timeout=8, read_timeout=5, sis_response_timeout=30, max_response_bytes=512):
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.sis_response_timeout = sis_response_timeout
        self.max_response_bytes = max_response_bytes

    def host_key_fingerprint(self, identity):
        transport = self._connect(identity)
        try:
            transport.start_client(timeout=self.connect_timeout)
            key = transport.get_remote_server_key()
            return key.get_name(), self._fingerprint(key)
        finally:
            transport.close()

    def probe_credentials(self, identity, credentials, *, expected_fingerprint):
        transport = self._authenticated_transport(identity, credentials, expected_fingerprint)
        transport.close()

    def stage(self, identity, credentials, local_path, remote_name, *, expected_fingerprint):
        transport = self._authenticated_transport(identity, credentials, expected_fingerprint)
        try:
            sftp = paramiko.SFTPClient.from_transport(transport)
            try:
                sftp.get_channel().settimeout(self.read_timeout)
                attributes = sftp.put(str(local_path), remote_name, confirm=True)
                if attributes.st_size != Path(local_path).stat().st_size:
                    raise OSError("Staged PEM size did not match the local file")
                return {"transfer_verified": True, "remote_size": attributes.st_size}
            finally:
                sftp.close()
        finally:
            transport.close()

    def ingest(self, identity, credentials, command, *, expected_fingerprint):
        transport = self._authenticated_transport(identity, credentials, expected_fingerprint)
        try:
            channel = transport.open_session(timeout=self.connect_timeout)
            try:
                channel.settimeout(self.read_timeout)
                channel.get_pty(term="vt100")
                channel.invoke_shell()
                preloaded = self._drain(channel)
                if b"CertI" in preloaded:
                    return SISExchange(preloaded=preloaded, received=b"", write_confirmed=False)
                channel.sendall(command)
                received = self._read_response(channel)
                return SISExchange(preloaded=b"", received=received, write_confirmed=True)
            finally:
                channel.close()
        finally:
            transport.close()

    def delete(self, identity, credentials, remote_name, *, expected_fingerprint):
        transport = self._authenticated_transport(identity, credentials, expected_fingerprint)
        try:
            sftp = paramiko.SFTPClient.from_transport(transport)
            try:
                sftp.get_channel().settimeout(self.read_timeout)
                try:
                    sftp.remove(remote_name)
                except OSError as error:
                    if error.errno != errno.ENOENT:
                        raise
            finally:
                sftp.close()
        finally:
            transport.close()

    def _authenticated_transport(self, identity, credentials, expected_fingerprint):
        transport = self._connect(identity)
        try:
            transport.start_client(timeout=self.connect_timeout)
            if self._fingerprint(transport.get_remote_server_key()) != expected_fingerprint:
                raise HostKeyChangedError("SSH host key changed before authentication")
            transport.auth_password(credentials["username"], credentials["password"])
            if not transport.is_authenticated():
                raise paramiko.AuthenticationException("SSH authentication failed")
            return transport
        except Exception:
            transport.close()
            raise

    def _connect(self, identity):
        connection = socket.create_connection((identity.host, identity.port), timeout=self.connect_timeout)
        try:
            transport = paramiko.Transport(connection)
            transport.auth_timeout = self.connect_timeout
            transport.banner_timeout = self.connect_timeout
            return transport
        except Exception:
            connection.close()
            raise

    @staticmethod
    def _fingerprint(key):
        import base64

        digest = hashlib.sha256(key.asbytes()).digest()
        return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")

    def _drain(self, channel):
        data = bytearray()
        deadline = time.monotonic() + 0.2
        while time.monotonic() < deadline:
            if not channel.recv_ready():
                time.sleep(0.01)
                continue
            chunk = channel.recv(min(128, self.max_response_bytes - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) >= self.max_response_bytes:
                raise OSError("Pre-send response exceeded limit")
        return bytes(data)

    def _read_response(self, channel):
        data = bytearray()
        deadline = time.monotonic() + self.sis_response_timeout
        while time.monotonic() < deadline and len(data) < self.max_response_bytes:
            if not channel.recv_ready():
                time.sleep(0.02)
                continue
            data.extend(channel.recv(min(128, self.max_response_bytes - len(data))))
            if re.search(rb"(?:^|[\r\n])CertI[12]\r", data):
                break
        return bytes(data)


class DirectExtronService:
    """Explicit, non-retrying direct delivery for one selected Extron device."""

    LAN_B_TARGETS_KEY = LAN_B_TARGETS_KEY
    HOST_KEYS_KEY = HOST_KEYS_KEY
    STAGED_KEY = STAGED_KEY

    def __init__(self, database, artifacts, vault, *, transport=None, verifier=None, verification_timeout=30):
        self.database = database
        self.artifacts = artifacts
        self.vault = vault
        self.transport = transport or ParamikoDirectTransport()
        self.verifier = verifier or verify_device_certificate
        self.verification_timeout = verification_timeout

    def target_for(self, selector, nic=1):
        selector = self._selector(selector)
        nic = self._nic(nic)
        host, https_port = selector, 443
        if nic == 2:
            target = self.database.get_setting(self.LAN_B_TARGETS_KEY, {}).get(selector)
            if not target:
                raise ValueError("LAN B endpoint must be configured before selecting NIC 2")
            host, https_port = target["host"], int(target["port"])
        return DirectTarget(
            sftp=EndpointIdentity(selector, nic, "sftp", host, 22022),
            sis=EndpointIdentity(selector, nic, "sis", host, 22023),
            https=EndpointIdentity(selector, nic, "https", host, https_port),
        )

    def save_lan_b_target(self, selector, *, host, port=443):
        selector = self._selector(selector)
        host = self._host(host)
        port = self._port(port)
        targets = dict(self.database.get_setting(self.LAN_B_TARGETS_KEY, {}))
        targets[selector] = {"host": host, "port": port}
        self.database.put_setting(self.LAN_B_TARGETS_KEY, targets)
        return self.target_for(selector, 2)

    def save_credentials(self, selector, *, username, password):
        selector = self._selector(selector)
        self._save_secret(self._secret_id(selector), username=username, password=password, metadata={"selector": selector, "username": username})

    def save_shared_credentials(self, *, username, password):
        self._save_secret(DEFAULT_SECRET_ID, username=username, password=password, metadata={"scope": "shared", "username": username})

    def probe_one(self, *, selector, nic=1):
        target = self.target_for(selector, nic)
        trust = self._check_trust(target)
        if trust is not None:
            return trust
        credentials = self._credentials(target.sftp.selector)
        try:
            for identity in (target.sftp, target.sis):
                self.transport.probe_credentials(identity, credentials, expected_fingerprint=self._approved_fingerprint(identity))
        except HostKeyChangedError:
            return {"status": "host_key_changed", "identity": self._identity_dict(identity)}
        except (paramiko.AuthenticationException, PermissionError):
            return {"status": "authentication_failed", "identity": self._identity_dict(identity)}
        except (OSError, paramiko.SSHException):
            return {"status": "connection_failed", "identity": self._identity_dict(identity)}
        return {"status": "ready", "target": self._public_target(target)}

    def approve_host_key(self, *, selector, nic=1, fingerprint, connection=None):
        target = self.target_for(selector, nic)
        observed = self._observed_keys(target)
        supplied = str(fingerprint or "")
        approvals = dict(self.database.get_setting(self.HOST_KEYS_KEY, {}))
        for identity, (algorithm, current) in observed.items():
            if connection is not None and identity.connection != connection:
                continue
            if connection is None and approvals.get(identity.key(), {}).get("fingerprint") == current:
                continue
            if current != supplied:
                raise ValueError("Host-key fingerprint changed before approval")
            approvals[identity.key()] = {"algorithm": algorithm, "fingerprint": current, "identity": self._identity_dict(identity)}
            self.database.put_setting(self.HOST_KEYS_KEY, approvals)
            return {"status": "approved", "fingerprint": supplied, "identity": self._identity_dict(identity)}
        raise ValueError("No matching host-key endpoint to approve")

    def activate_one(self, *, selector, certificate_id, nic=1):
        target = self.target_for(selector, nic)
        trust = self._check_trust(target)
        if trust is not None:
            return trust
        if not certificate_id or not self.artifacts.has_certificate(certificate_id):
            raise KeyError(certificate_id)
        credentials = self._credentials(target.sftp.selector)
        staged_name = f"certmon-{uuid.uuid4().hex}.pem"
        record = self._record_staged(staged_name, target, certificate_id)
        try:
            with self.artifacts.materialize_private(certificate_id, "combined.pem") as pem_path:
                staged = self.transport.stage(target.sftp, credentials, pem_path, staged_name, expected_fingerprint=self._approved_fingerprint(target.sftp))
                if isinstance(staged, dict) and staged.get("transfer_verified") is True:
                    records = dict(self.database.get_setting(self.STAGED_KEY, {}))
                    records[staged_name] = dict(records[staged_name], sftp_diagnostics={"transfer_verified": True, "remote_size": staged["remote_size"]})
                    self.database.put_setting(self.STAGED_KEY, records)
                exchange = self._exchange(self.transport.ingest(target.sis, credentials, self._sis_command(target.sis.nic, staged_name), expected_fingerprint=self._approved_fingerprint(target.sis)))
        except HostKeyChangedError:
            return self._set_staged(staged_name, "cleanup_pending", response="host_key_changed")
        except (paramiko.AuthenticationException, PermissionError):
            return self._set_staged(staged_name, "cleanup_pending", response="authentication_failed", result_status="authentication_failed")
        except (OSError, paramiko.SSHException):
            verification = self._verify(target.https, certificate_id)
            return self._set_staged(staged_name, "cleanup_pending", response="transport_interrupted", verification=verification.status)
        records = dict(self.database.get_setting(self.STAGED_KEY, {}))
        records[staged_name] = dict(records[staged_name], sis_diagnostics={
            "write_confirmed": exchange.write_confirmed,
            "received": repr(exchange.received[:512]),
            "preloaded": repr(exchange.preloaded[:512]),
        })
        self.database.put_setting(self.STAGED_KEY, records)
        if exchange.preloaded or not exchange.write_confirmed or not self._exact_ack(exchange.received, target.sis.nic, self._sis_command(target.sis.nic, staged_name)):
            verification = self._verify(target.https, certificate_id)
            return self._set_staged(staged_name, "cleanup_pending", response="ack_rejected", verification=verification.status)
        self._set_staged(staged_name, "staged", known_completion=True)
        verification = self._verify(target.https, certificate_id, wait_for_activation=True)
        if verification.status != "verified":
            return self._set_staged(staged_name, "cleanup_pending", verification=verification.status, known_completion=True)
        try:
            self.transport.delete(target.sftp, credentials, staged_name, expected_fingerprint=self._approved_fingerprint(target.sftp))
        except (paramiko.AuthenticationException, PermissionError):
            return self._set_staged(staged_name, "delete_failed", verification="verified", known_completion=True)
        except (OSError, paramiko.SSHException):
            return self._set_staged(staged_name, "delete_failed", verification="verified", known_completion=True)
        return self._set_staged(staged_name, "deleted", verification="verified", result_status="verified", known_completion=True)

    def cleanup_one(self, *, staged_name, confirm_finished=False):
        if Path(staged_name).name != staged_name:
            raise ValueError("Invalid staged PEM name")
        records = self.database.get_setting(self.STAGED_KEY, {})
        record = records.get(staged_name)
        if record is None:
            raise KeyError(staged_name)
        if record["status"] == "deleted":
            return {"status": "deleted", "staged_name": staged_name}
        if not confirm_finished:
            return {"status": "cleanup_pending", "staged_name": staged_name}
        if not record.get("known_completion") and time.time() < record["grace_deadline"]:
            return {"status": "cleanup_pending", "staged_name": staged_name}
        original = record["target"]
        target = DirectTarget(
            EndpointIdentity(record["selector"], record["nic"], "sftp", original["host"], 22022),
            EndpointIdentity(record["selector"], record["nic"], "sis", original["host"], 22023),
            EndpointIdentity(record["selector"], record["nic"], "https", original["host"], original["https_port"]),
        )
        trust = self._check_trust(target)
        if trust is not None:
            return trust
        try:
            self.transport.delete(target.sftp, self._credentials(target.sftp.selector), staged_name, expected_fingerprint=self._approved_fingerprint(target.sftp))
        except HostKeyChangedError:
            return {"status": "host_key_changed", "identity": self._identity_dict(target.sftp)}
        except (paramiko.SSHException, PermissionError, OSError):
            return self._set_staged(staged_name, "delete_failed")
        return self._set_staged(staged_name, "deleted", result_status="deleted")

    def recover_staged(self):
        return [dict(value, staged_name=name) for name, value in self.database.get_setting(self.STAGED_KEY, {}).items() if value.get("status") != "deleted"]

    def _check_trust(self, target):
        approvals = self.database.get_setting(self.HOST_KEYS_KEY, {})
        for identity, (algorithm, fingerprint) in self._observed_keys(target).items():
            approved = approvals.get(identity.key())
            if approved is None:
                return {"status": "approval_required", "fingerprint": fingerprint, "identity": self._identity_dict(identity)}
            if approved.get("algorithm") != algorithm or approved.get("fingerprint") != fingerprint:
                return {"status": "host_key_changed", "fingerprint": fingerprint, "identity": self._identity_dict(identity)}
        return None

    def _observed_keys(self, target):
        result = {}
        for identity in (target.sftp, target.sis):
            try:
                observed = self.transport.host_key_fingerprint(identity)
            except (OSError, paramiko.SSHException) as error:
                if isinstance(error, TimeoutError):
                    reason = "connection timed out; check device reachability and firewall rules"
                elif isinstance(error, ConnectionRefusedError):
                    reason = "connection refused; check that the device service is enabled"
                elif isinstance(error, socket.gaierror):
                    reason = "host address could not be resolved"
                elif isinstance(error, paramiko.SSHException):
                    reason = "SSH negotiation failed; check the device SSH service and firmware"
                else:
                    reason = "network connection failed; check device reachability and firewall rules"
                raise DirectConnectionError(identity, reason) from error
            result[identity] = observed if isinstance(observed, tuple) else ("ssh", observed)
        return result

    def _approved_fingerprint(self, identity):
        return self.database.get_setting(self.HOST_KEYS_KEY, {})[identity.key()]["fingerprint"]

    def _credentials(self, selector):
        stored = self.database.get_secret(self._secret_id(selector)) or self.database.get_secret(DEFAULT_SECRET_ID)
        if stored is None:
            raise ValueError("No direct Extron credential is configured")
        blob = stored["blob"] if isinstance(stored, dict) and "blob" in stored else stored
        value = self.vault.decrypt(blob, purpose=SECRET_PURPOSE)
        data = json.loads(value.decode("utf-8") if isinstance(value, bytes) else value)
        return {"username": data["username"], "password": data["password"]}

    def _save_secret(self, secret_id, *, username, password, metadata):
        if not username or password is None:
            raise ValueError("username and password are required")
        blob = self.vault.encrypt(json.dumps({"username": username, "password": password}).encode("utf-8"), purpose=SECRET_PURPOSE)
        self.database.put_secret(secret_id, blob, metadata)

    def _record_staged(self, name, target, certificate_id):
        records = dict(self.database.get_setting(self.STAGED_KEY, {}))
        record = {
            "selector": target.sftp.selector,
            "nic": target.sftp.nic,
            "certificate_id": certificate_id,
            "status": "staged",
            "target": self._public_target(target),
            "known_completion": False,
            "grace_deadline": time.time() + 300,
        }
        records[name] = record
        self.database.put_setting(self.STAGED_KEY, records)
        return record

    def _set_staged(self, name, status, *, verification=None, response=None, result_status=None, known_completion=None):
        records = dict(self.database.get_setting(self.STAGED_KEY, {}))
        record = dict(records[name])
        record["status"] = status
        if verification:
            record["verification"] = verification
        if response:
            record["response"] = response
        if known_completion is not None:
            record["known_completion"] = known_completion
        records[name] = record
        self.database.put_setting(self.STAGED_KEY, records)
        payload = {"status": result_status or status, "staged_name": name}
        if record.get("sis_diagnostics"):
            payload["sis_diagnostics"] = record["sis_diagnostics"]
        if record.get("sftp_diagnostics"):
            payload["sftp_diagnostics"] = record["sftp_diagnostics"]
        if response:
            payload["response"] = response
        if verification:
            payload["verification"] = verification
        return payload

    def _verify(self, endpoint, certificate_id, *, wait_for_activation=False):
        try:
            certificate_pem = self.artifacts.read_public(certificate_id, "certificate.pem")
            certificate = x509.load_pem_x509_certificate(certificate_pem)
            fingerprint = hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()
            material = DeploymentMaterial(certificate_id, certificate_pem, fingerprint, self.artifacts)
        except AttributeError:
            material = SimpleNamespace(expected_fingerprint="")
        deadline = time.monotonic() + (self.verification_timeout if wait_for_activation else 0)
        while True:
            result = self.verifier(endpoint.device(), material)
            remaining = deadline - time.monotonic()
            if result.status == "verified" or remaining <= 0:
                return result
            time.sleep(min(1, remaining))

    @staticmethod
    def _exchange(value):
        return value if isinstance(value, SISExchange) else SISExchange(b"", bytes(value), True)

    @staticmethod
    def _exact_ack(value, nic, command=None):
        expected = f"CertI{nic}".encode("ascii")
        if not value.endswith((b"\r", b"\n")):
            return False
        # A PTY may translate the device's CRLF into CRCRLF.
        lines = value.rstrip(b"\r\n").replace(b"\r\r\n", b"\r\n").replace(b"\r\n", b"\r").split(b"\r")
        if lines == [expected]:
            return True
        if command is None:
            return False
        echoes = {command.rstrip(b"\r"), command.rstrip(b"\r").replace(b"\x1b", b"^[")}
        return len(lines) == 2 and lines[0] in echoes and lines[1] == expected

    @staticmethod
    def _sis_command(nic, staged_name):
        return b"\x1bI" + str(nic).encode("ascii") + b"*" + staged_name.encode("ascii") + b"CERT\r"

    @staticmethod
    def _public_target(target):
        return {"selector": target.sftp.selector, "nic": target.sftp.nic, "host": target.https.host, "https_port": target.https.port}

    @staticmethod
    def _identity_dict(identity):
        return {"selector": identity.selector, "nic": identity.nic, "connection": identity.connection, "host": identity.host, "port": identity.port}

    @staticmethod
    def _secret_id(selector):
        return f"{SECRET_PREFIX}{selector}"

    @staticmethod
    def _selector(value):
        selector = str(value or "").strip()
        if not selector or "|" in selector or "/" in selector:
            raise ValueError("Invalid device selector")
        return selector

    @staticmethod
    def _nic(value):
        nic = int(value)
        if nic not in (1, 2):
            raise ValueError("NIC must be 1 or 2")
        return nic

    @staticmethod
    def _host(value):
        host = str(value or "").strip()
        if not host or any(character.isspace() for character in host):
            raise ValueError("Invalid HTTPS host")
        return host

    @staticmethod
    def _port(value):
        port = int(value)
        if not 1 <= port <= 65535:
            raise ValueError("Invalid HTTPS port")
        return port
