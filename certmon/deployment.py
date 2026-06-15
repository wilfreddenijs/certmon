import hashlib
import http.cookiejar
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from certmon.models import RenewalState
from certmon.permissions import Permission, authorize


class DeploymentAdapter(Protocol):
    def deploy(self, device, certificate):
        ...


@dataclass
class VerificationResult:
    status: str
    expected_fingerprint: str
    observed_fingerprint: str | None = None


@dataclass
class DeploymentAttempt:
    success: bool
    log: tuple[str, ...] = ()


@dataclass
class DeploymentResult:
    ok: bool
    log: tuple[str, ...] = ()
    instructions: str | None = None
    verification: VerificationResult | None = None
    public_artifacts: dict[str, str] = field(default_factory=dict)
    job: dict | None = None


@dataclass
class DeploymentMaterial:
    certificate_id: str
    certificate_pem: bytes
    expected_fingerprint: str
    artifact_store: object

    @contextmanager
    def materialize_private_key(self):
        with self.artifact_store.materialize_private(
            self.certificate_id, "private-key.pem"
        ) as path:
            yield Path(path)


class DeploymentService:
    def __init__(
        self,
        database,
        artifacts,
        renewal_service,
        *,
        adapters,
        verifier=None,
        public_artifact_url_builder=None,
    ):
        self.database = database
        self.artifacts = artifacts
        self.renewal_service = renewal_service
        self.adapters = dict(adapters)
        self.verifier = verifier or verify_device_certificate
        self.public_artifact_url_builder = (
            public_artifact_url_builder or _default_public_artifact_url
        )

    def deploy_certificate(self, device, certificate_id, *, job_id=None):
        authorize(Permission.DEPLOY_CERTIFICATE)
        certificate = self.database.get_certificate(certificate_id)
        if certificate is None or not self.artifacts.has_certificate(certificate_id):
            raise KeyError(certificate_id)
        job_id = job_id or self._find_deployable_job(certificate_id)

        public_artifacts = self._public_artifacts(certificate_id)
        material = DeploymentMaterial(
            certificate_id=certificate_id,
            certificate_pem=self.artifacts.read_public(certificate_id, "certificate.pem"),
            expected_fingerprint=_certificate_fingerprint(
                self.artifacts.read_public(certificate_id, "certificate.pem")
            ),
            artifact_store=self.artifacts,
        )

        adapter_name = (device.get("device_type") or "generic").strip().lower()
        adapter = self.adapters.get(adapter_name)
        if adapter is None:
            result = DeploymentResult(
                ok=False,
                log=(
                    f"Device type '{adapter_name}' does not support automatic push.",
                    "See manual instructions below.",
                ),
                instructions=_generic_instructions(device),
                public_artifacts=public_artifacts,
            )
            result.job = self._update_job(
                job_id,
                certificate_id,
                error_code="manual_deployment_required",
                error_message="Automatic deployment is unavailable for this device type",
            )
            self._record_event(
                job_id,
                device,
                certificate_id,
                adapter_name,
                result,
            )
            return result

        attempt = self._attempt_deployment(adapter, device, material)
        verification = None
        error_code = None
        error_message = None

        if attempt.success:
            verification = self.verifier(device, material)
            if verification.status == "verified":
                job = self._mark_verified(job_id, certificate_id)
                result = DeploymentResult(
                    ok=True,
                    log=attempt.log,
                    verification=verification,
                    public_artifacts=public_artifacts,
                    job=job,
                )
                self._record_event(
                    job_id,
                    device,
                    certificate_id,
                    adapter_name,
                    result,
                )
                return result
            error_code = "deployment_verification_failed"
            error_message = (
                "Deployment completed but verification returned "
                f"{verification.status}"
            )
        else:
            error_code = "deployment_failed"
            error_message = attempt.log[-1] if attempt.log else "Deployment failed"

        result = DeploymentResult(
            ok=False,
            log=attempt.log,
            verification=verification,
            instructions=_generic_instructions(device),
            public_artifacts=public_artifacts,
        )
        result.job = self._update_job(
            job_id,
            certificate_id,
            error_code=error_code,
            error_message=error_message,
        )
        self._record_event(job_id, device, certificate_id, adapter_name, result)
        return result

    def _attempt_deployment(self, adapter, device, material):
        try:
            return adapter.deploy(device, material)
        except Exception as exc:
            return DeploymentAttempt(success=False, log=(str(exc),))

    def _mark_verified(self, job_id, certificate_id):
        if not job_id:
            return None
        job = self._job_for_certificate(job_id, certificate_id)
        if job["state"] == RenewalState.ISSUED.value:
            job = self.renewal_service.transition(
                job_id,
                RenewalState.ISSUED,
                job["version"],
                RenewalState.DEPLOYMENT_PENDING,
                {"error_code": None, "error_message": None},
            )
        return self.renewal_service.transition(
            job_id,
            RenewalState.DEPLOYMENT_PENDING,
            job["version"],
            RenewalState.DEPLOYED,
            {"error_code": None, "error_message": None},
        )

    def _update_job(self, job_id, certificate_id, *, error_code, error_message):
        if not job_id:
            return None
        job = self._job_for_certificate(job_id, certificate_id)
        if job["state"] == RenewalState.ISSUED.value:
            return self.renewal_service.transition(
                job_id,
                RenewalState.ISSUED,
                job["version"],
                RenewalState.DEPLOYMENT_PENDING,
                {"error_code": error_code, "error_message": error_message},
            )
        self.database.compare_and_set_job(
            job_id,
            RenewalState.DEPLOYMENT_PENDING.value,
            job["version"],
            RenewalState.DEPLOYMENT_PENDING.value,
            {"error_code": error_code, "error_message": error_message},
        )
        return self.database.get_job(job_id)

    def _job_for_certificate(self, job_id, certificate_id):
        job = self.database.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.get("certificate_id") != certificate_id:
            raise ValueError("Certificate does not belong to this renewal job")
        if job["state"] not in {
            RenewalState.ISSUED.value,
            RenewalState.DEPLOYMENT_PENDING.value,
        }:
            raise ValueError("Renewal job is not ready for deployment")
        return job

    def _find_deployable_job(self, certificate_id):
        candidates = [
            job
            for job in self.database.list_jobs()
            if job.get("certificate_id") == certificate_id
            and job["state"]
            in {
                RenewalState.ISSUED.value,
                RenewalState.DEPLOYMENT_PENDING.value,
            }
        ]
        return candidates[-1]["id"] if candidates else None

    def _record_event(self, job_id, device, certificate_id, adapter_name, result):
        details = {
            "device_id": device.get("id"),
            "device_host": device.get("host"),
            "device_port": device.get("port"),
            "device_type": device.get("device_type"),
            "certificate_id": certificate_id,
            "adapter": adapter_name,
            "ok": result.ok,
            "log": list(result.log),
            "public_artifacts": result.public_artifacts,
        }
        if result.instructions:
            details["instructions"] = result.instructions
        if result.verification is not None:
            details["verification"] = {
                "status": result.verification.status,
                "expected_fingerprint": result.verification.expected_fingerprint,
                "observed_fingerprint": result.verification.observed_fingerprint,
            }
        self.database.record_event("certificate_deployment", details, job_id=job_id)

    def _public_artifacts(self, certificate_id):
        artifacts = {}
        for name in ("certificate.pem", "chain.pem", "full-chain.pem"):
            try:
                self.artifacts.read_public(certificate_id, name)
            except FileNotFoundError:
                continue
            artifacts[name] = self.public_artifact_url_builder(certificate_id, name)
        return artifacts


class ExtronDeploymentAdapter:
    def deploy(self, device, certificate):
        log = []
        scheme = "https" if device.get("https") else "http"
        host = device["host"]
        port = int(device.get("port", 80))
        base = f"{scheme}://{host}:{port}"

        cj = http.cookiejar.CookieJar()
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cj),
            urllib.request.HTTPSHandler(context=ctx),
        )
        opener.addheaders = [("User-Agent", "Mozilla/5.0")]

        login_url = None
        for path in ("/", "/login", "/auth", "/index.html"):
            try:
                response = opener.open(f"{base}{path}", timeout=5)
                body = response.read(4096).decode("utf-8", errors="ignore")
                if "password" in body.lower() or "login" in body.lower():
                    login_url = f"{base}{path}"
                    log.append(f"Found login page at {path}")
                    break
            except Exception:
                continue
        if login_url is None:
            login_url = f"{base}/"
            log.append("Login page not identified, trying root")

        authenticated = False
        login_payloads = (
            {"username": device.get("username") or "admin", "password": device.get("password")},
            {"user": device.get("username") or "admin", "passwd": device.get("password")},
            {"login": device.get("username") or "admin", "password": device.get("password")},
        )
        for post_url in (login_url, f"{base}/login", f"{base}/auth", f"{base}/api/login"):
            for payload in login_payloads:
                try:
                    request = urllib.request.Request(
                        post_url,
                        data=urllib.parse.urlencode(payload).encode(),
                        headers={
                            "Content-Type": "application/x-www-form-urlencoded"
                        },
                    )
                    response = opener.open(request, timeout=5)
                    status = response.getcode()
                    body = response.read(1024).decode("utf-8", errors="ignore")
                    if status in (200, 302) and "invalid" not in body.lower():
                        log.append(f"Login succeeded at {post_url} (HTTP {status})")
                        authenticated = True
                        break
                except urllib.error.HTTPError as exc:
                    if exc.code == 401:
                        continue
                    log.append(f"Login HTTP error {exc.code} at {post_url}")
                except Exception as exc:
                    log.append(f"Login error at {post_url}: {exc}")
            if authenticated:
                break
        if not authenticated:
            log.append("WARNING: Could not confirm login - will attempt upload anyway")

        boundary = "----CertMonBoundary7a3f9b"

        def make_multipart(cert_bytes, key_bytes, cert_field, key_field):
            return (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{cert_field}"; filename="cert.pem"\r\n'
                f"Content-Type: application/x-pem-file\r\n\r\n"
            ).encode() + cert_bytes + (
                f"\r\n--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{key_field}"; filename="key.pem"\r\n'
                f"Content-Type: application/x-pem-file\r\n\r\n"
            ).encode() + key_bytes + f"\r\n--{boundary}--\r\n".encode()

        with certificate.materialize_private_key() as key_path:
            key_bytes = key_path.read_bytes()
            cert_bytes = certificate.certificate_pem
            for path, cert_field, key_field in (
                ("/api/certificate", "certificate", "private_key"),
                ("/api/config/certificate", "cert", "key"),
                ("/Certificate", "certificate", "key"),
                ("/certificate", "cert_file", "key_file"),
                ("/api/security/cert", "cert", "key"),
            ):
                try:
                    request = urllib.request.Request(
                        f"{base}{path}",
                        data=make_multipart(cert_bytes, key_bytes, cert_field, key_field),
                        headers={
                            "Content-Type": (
                                f"multipart/form-data; boundary={boundary}"
                            )
                        },
                    )
                    request.get_method = lambda: "POST"
                    response = opener.open(request, timeout=10)
                    status = response.getcode()
                    body = response.read(512).decode("utf-8", errors="ignore")
                    log.append(f"Upload attempt {path}: HTTP {status} - {body[:120]}")
                    if status in (200, 201, 204):
                        log.append("Certificate upload succeeded!")
                        return DeploymentAttempt(success=True, log=tuple(log))
                except urllib.error.HTTPError as exc:
                    log.append(f"Upload {path}: HTTP {exc.code}")
                    if exc.code not in (404, 405):
                        log.append(
                            "  -> endpoint exists (HTTP "
                            f"{exc.code}), may need manual parameter adjustment"
                        )
                except Exception as exc:
                    log.append(f"Upload {path}: {exc}")

        log.append("Automatic upload did not succeed - see manual upload instructions")
        return DeploymentAttempt(success=False, log=tuple(log))


def verify_device_certificate(device, material):
    host = device["host"]
    port = int(device.get("port", 443))
    try:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=5) as connection:
            with context.wrap_socket(connection, server_hostname=host) as wrapped:
                observed_der = wrapped.getpeercert(binary_form=True)
    except OSError:
        return VerificationResult(
            status="unreachable",
            expected_fingerprint=material.expected_fingerprint,
            observed_fingerprint=None,
        )
    observed = hashlib.sha256(observed_der).hexdigest()
    status = (
        "verified"
        if observed == material.expected_fingerprint
        else "different_certificate"
    )
    return VerificationResult(
        status=status,
        expected_fingerprint=material.expected_fingerprint,
        observed_fingerprint=observed,
    )


def _certificate_fingerprint(certificate_pem):
    cert = x509.load_pem_x509_certificate(certificate_pem)
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def _default_public_artifact_url(certificate_id, name):
    return f"/api/certificates/{certificate_id}/public/{name}"


def _generic_instructions(device):
    device_type = device.get("device_type", "generic")
    host = device.get("host", "")
    port = device.get("port", 443)
    use_https = bool(device.get("https", False))
    scheme = "https" if use_https else "http"
    instructions = {
        "extron": (
            "Open Extron Toolbelt on this PC, connect to "
            f"{host}, then upload the public certificate and private key manually."
        ),
        "homeassistant": (
            "Copy the public certificate files to your Home Assistant config and "
            "perform private-key export separately before updating ssl_certificate "
            "and ssl_key."
        ),
        "synology": (
            "Open DSM, go to Control Panel > Security > Certificate, import the "
            "public certificate, and export the private key separately if needed."
        ),
        "generic": (
            f"Open the device web interface at {scheme}://{host}:{port} and follow "
            "its certificate import instructions. Public certificate downloads are "
            "linked below; private-key export remains a separate audited action."
        ),
    }
    return instructions.get(device_type, instructions["generic"])
