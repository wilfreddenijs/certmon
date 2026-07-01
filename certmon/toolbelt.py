import ipaddress
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


STATUS_KEY = "toolbelt_latest_status"
SELECTION_KEY = "toolbelt_selected_devices"
SECRET_PREFIX = "toolbelt-device-credentials:"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ToolbeltRun:
    id: str
    mode: str
    status: str = "running"
    started_at: str = field(default_factory=utc_now)
    finished_at: str | None = None
    current_device: str | None = None
    events: list[dict] = field(default_factory=list)
    devices: dict[str, dict] = field(default_factory=dict)
    requested_stop: bool = False
    error: str | None = None
    stop_file: str | None = None
    temp_dir: str | None = None

    def to_dict(self):
        return {
            "id": self.id,
            "mode": self.mode,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "current_device": self.current_device,
            "events": list(self.events[-200:]),
            "devices": self.devices,
            "requested_stop": self.requested_stop,
            "error": self.error,
        }


class ToolbeltBatchService:
    """Server-side Toolbelt orchestration.

    The browser sees device/certificate IDs and progress only. Private Extron
    combined PEM files are materialized server-side into a temporary run
    directory and deleted when the run ends.
    """

    def __init__(self, database, artifacts, vault, *, script_path=None, runner=None):
        self.database = database
        self.artifacts = artifacts
        self.vault = vault
        self.script_path = Path(script_path or Path(__file__).parents[1] / "toolbelt_uploader.py")
        self.runner = runner or self._run_subprocess
        self._lock = threading.RLock()
        self._runs: dict[str, ToolbeltRun] = {}

    def list_devices(self):
        latest = self.database.get_setting(STATUS_KEY, {})
        selected_setting = self.database.get_setting(SELECTION_KEY, None)
        selected = set(selected_setting or [])
        rows = []
        for cert in self.database.list_certificates():
            if cert.get("kind") != "leaf" or cert.get("issuer_type") != "local_ca":
                continue
            selector = self._selector(cert)
            if not selector:
                continue
            profile = cert.get("profile")
            rows.append(
                {
                    "selector": selector,
                    "certificate_id": cert["id"],
                    "label": cert.get("device_name") or selector,
                    "identifiers": cert.get("identifiers") or [],
                    "profile": profile,
                    "extron_ready": profile == "extron-rsa"
                    and self.artifacts.has_certificate(cert["id"]),
                    "selected": selector in selected
                    if selected_setting is not None
                    else True,
                    "dry_run": latest.get(self._status_key(selector, cert["id"], "dry-run")),
                    "upload": latest.get(self._status_key(selector, cert["id"], "upload")),
                    "credentials_saved": self.database.get_secret(
                        self._secret_id(selector)
                    )
                    is not None,
                }
            )
        return sorted(rows, key=lambda row: (row["label"], row["selector"]))

    def save_selection(self, selectors):
        self.database.put_setting(SELECTION_KEY, sorted(set(selectors or [])))

    def save_credentials(self, selector, *, username, password):
        if not selector or not username or password is None:
            raise ValueError("selector, username and password are required")
        blob = self.vault.encrypt(
            json.dumps({"username": username, "password": password}).encode("utf-8"),
            purpose="toolbelt-device-credentials",
        )
        self.database.put_secret(
            self._secret_id(selector), blob, {"selector": selector, "username": username}
        )

    def start(self, *, mode, selectors=None):
        if mode not in {"dry-run", "upload"}:
            raise ValueError("mode must be dry-run or upload")
        selected = None if selectors is None else set(selectors)
        targets = [
            row
            for row in self.list_devices()
            if selected is None or row["selector"] in selected
        ]
        if not targets:
            raise ValueError("No Toolbelt devices selected")
        self._clear_previous_statuses(mode, targets)
        not_ready = [row["selector"] for row in targets if not row.get("extron_ready")]
        if not_ready:
            raise ValueError(
                "Toolbelt upload requires Extron-ready Local CA certificates for: "
                + ", ".join(not_ready)
            )
        if mode == "upload":
            blocked = [
                row["selector"]
                for row in targets
                if not (row.get("dry_run") or {}).get("ok")
            ]
            if blocked:
                raise ValueError(
                    "Upload is blocked until dry-run is OK for: "
                    + ", ".join(blocked)
                )

        run = ToolbeltRun(id=str(uuid.uuid4()), mode=mode)
        with self._lock:
            self._runs[run.id] = run
        thread = threading.Thread(
            target=self._execute_run, args=(run, targets), daemon=True
        )
        thread.start()
        return run.to_dict()

    def get_run(self, run_id):
        with self._lock:
            run = self._runs.get(run_id)
            return None if run is None else run.to_dict()

    def stop(self, run_id):
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            run.requested_stop = True
            if run.stop_file:
                Path(run.stop_file).write_text("stop", encoding="utf-8")
            return run.to_dict()

    def _clear_previous_statuses(self, mode, targets):
        latest = self.database.get_setting(STATUS_KEY, {})
        modes = ("dry-run", "upload") if mode == "dry-run" else ("upload",)
        changed = False
        for row in targets:
            for status_mode in modes:
                key = self._status_key(row["selector"], row["certificate_id"], status_mode)
                if key in latest:
                    latest.pop(key, None)
                    changed = True
        if changed:
            self.database.put_setting(STATUS_KEY, latest)

    def _execute_run(self, run, targets):
        temp_dir = Path(tempfile.mkdtemp(prefix=f"certmon-toolbelt-{run.id}-"))
        run.temp_dir = str(temp_dir)
        stop_file = temp_dir / "stop"
        run.stop_file = str(stop_file)
        list_file = temp_dir / "devices.txt"
        credential_file = temp_dir / "credentials.json"
        resolved_credentials_file = temp_dir / "resolved-credentials.json"
        try:
            lines = []
            credentials = {}
            for row in targets:
                selector = row["selector"]
                certificate_id = row["certificate_id"]
                pem_name = f"{self._safe_name(selector)}-{certificate_id[:8]}-extron-combined.pem"
                pem_path = temp_dir / pem_name
                with self.artifacts.materialize_private(
                    certificate_id, "combined.pem"
                ) as materialized:
                    shutil.copy2(materialized, pem_path)
                lines.append(f"{selector},{pem_path}")
                credentials[selector] = self._credentials_for(selector)
                self._record_device_event(
                    run,
                    {
                        "event": "device_pending",
                        "selector": selector,
                        "certificate_id": certificate_id,
                    },
                )
            list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            credential_file.write_text(json.dumps(credentials), encoding="utf-8")
            command = [
                *self._uploader_entrypoint(),
                "--list",
                str(list_file),
                "--jsonl",
                "--stop-file",
                str(stop_file),
                "--device-password-file",
                str(credential_file),
                "--resolved-credentials-file",
                str(resolved_credentials_file),
            ]
            if run.mode == "upload":
                command.append("--commit")
            self.runner(command, self._handle_event(run))
            self._save_resolved_credentials(resolved_credentials_file)
            self._finish(run, "stopped" if run.requested_stop else "complete")
        except Exception as exc:
            self._save_resolved_credentials(resolved_credentials_file)
            message = self._friendly_error(str(exc))
            run.error = message
            self._record_event(run, {"event": "run_failed", "message": message})
            failed_event = "upload_failed" if run.mode == "upload" else "dry_run_failed"
            for row in targets:
                self._record_device_event(
                    run,
                    {
                        "event": failed_event,
                        "selector": row["selector"],
                        "certificate_id": row["certificate_id"],
                        "message": message,
                    },
                )
            self._finish(run, "failed")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _run_subprocess(self, command, on_event):
        output_tail = []
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdout is not None
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = {"event": "log", "message": line}
                output_tail.append(line)
                output_tail = output_tail[-8:]
            on_event(event)
        code = process.wait()
        if code:
            detail = "\n".join(output_tail).strip()
            if detail:
                raise RuntimeError(detail)
            raise RuntimeError(f"Toolbelt uploader exited with code {code}")

    def _uploader_entrypoint(self):
        if getattr(sys, "frozen", False):
            return [sys.executable, "--toolbelt-uploader"]
        return [sys.executable, str(self.script_path)]

    @staticmethod
    def _friendly_error(message):
        text = message or "Toolbelt uploader failed"
        lower = text.lower()
        if "not installed" in lower or "not running" in lower:
            return (
                "Extron Toolbelt is not installed or not running. Install/open "
                "Toolbelt, wait until the device list is visible, then retry dry-run."
            )
        if "cannot be automated" in lower or "administrator" in lower or "elevated" in lower:
            return (
                "Toolbelt is running at a different privilege level. Run CertMon "
                "and Toolbelt both as Administrator, or both normally, then retry."
            )
        if "pywinauto is required" in lower:
            return (
                "Toolbelt automation support is missing from this build "
                "(pywinauto/comtypes). Install dependencies or use a newer build."
            )
        return text

    def _handle_event(self, run):
        def handle(event):
            self._record_event(run, event)
            selector = event.get("selector") or event.get("device")
            if selector:
                run.current_device = selector
            if selector and event.get("event") in {
                "dry_run_ok",
                "dry_run_failed",
                "upload_ok",
                "upload_failed",
                "credentials_needed",
                "credentials_resolved",
                "serial_column_missing",
                "device_cancelled",
                "device_skipped",
            }:
                self._record_device_event(run, event)

        return handle

    def _record_event(self, run, event):
        event = {"time": utc_now(), **event}
        with self._lock:
            run.events.append(self._sanitize(event))

    def _record_device_event(self, run, event):
        event = self._sanitize(event)
        selector = event.get("selector") or event.get("device")
        if not selector:
            return
        certificate_id = event.get("certificate_id") or self._certificate_id_for(selector)
        ok = event.get("event", "").endswith("_ok")
        state = {
            "event": event.get("event"),
            "ok": ok,
            "message": event.get("message") or event.get("status"),
            "time": utc_now(),
            "run_id": run.id,
            "mode": run.mode,
        }
        with self._lock:
            run.devices[selector] = state
        if certificate_id and event.get("event") in {
            "dry_run_ok",
            "dry_run_failed",
            "upload_ok",
            "upload_failed",
        }:
            latest = self.database.get_setting(STATUS_KEY, {})
            latest[self._status_key(selector, certificate_id, run.mode)] = state
            self.database.put_setting(STATUS_KEY, latest)

    def _finish(self, run, status):
        with self._lock:
            run.status = status
            run.finished_at = utc_now()
            run.current_device = None

    def _save_resolved_credentials(self, path):
        try:
            if not path.exists():
                return
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        for selector, credential in (data or {}).items():
            username = (credential or {}).get("username") or "admin"
            password = (credential or {}).get("password")
            if not selector or not password:
                continue
            try:
                self.save_credentials(selector, username=username, password=password)
            except Exception:
                pass

    def _credentials_for(self, selector):
        blob = self.database.get_secret(self._secret_id(selector))
        if blob is not None:
            try:
                return json.loads(
                    self.vault.decrypt(
                        blob, purpose="toolbelt-device-credentials"
                    ).decode("utf-8")
                )
            except Exception:
                pass
        return {"username": "admin", "password_candidates": ["extron", "__SERIAL__"]}

    def _certificate_id_for(self, selector):
        for row in self.list_devices():
            if row["selector"] == selector:
                return row["certificate_id"]
        return None

    @staticmethod
    def _selector(metadata):
        identifiers = metadata.get("identifiers") or []
        for value in identifiers:
            try:
                ipaddress.ip_address(value)
            except ValueError:
                continue
            return value
        return identifiers[0] if identifiers else metadata.get("id")

    @staticmethod
    def _status_key(selector, certificate_id, mode):
        return f"{selector}|{certificate_id}|{mode}"

    @staticmethod
    def _secret_id(selector):
        return SECRET_PREFIX + selector

    @staticmethod
    def _safe_name(value):
        return "".join(ch if ch.isalnum() or ch in ".-" else "-" for ch in value)[:80]

    @staticmethod
    def _sanitize(value):
        text = json.dumps(value, default=str)
        for forbidden in ("password", "private-key", "BEGIN PRIVATE KEY"):
            text = text.replace(forbidden, "[redacted]")
        return json.loads(text)
