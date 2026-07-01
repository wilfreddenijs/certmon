import json
import time
from contextlib import contextmanager
from pathlib import Path

from certmon.toolbelt import STATUS_KEY, ToolbeltBatchService
from certmon.vault import EncryptedBlob


def wait_until(predicate, timeout=2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    assert predicate()


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
                "device_name": "UCS Boardroom",
                "identifiers": ["192.168.0.10"],
            }
        ]

    def list_certificates(self):
        return list(self.certificates)

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    def put_setting(self, key, value):
        self.settings[key] = value

    def get_secret(self, secret_id):
        return self.secrets.get(secret_id)

    def put_secret(self, secret_id, blob, metadata=None):
        self.secrets[secret_id] = blob


class FakeArtifacts:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.materialized_paths = []

    def has_certificate(self, certificate_id):
        return certificate_id == "cert-1"

    @contextmanager
    def materialize_private(self, certificate_id, name):
        path = self.tmp_path / f"{certificate_id}-{name}"
        path.write_text("PRIVATE COMBINED PEM", encoding="utf-8")
        self.materialized_paths.append(path)
        try:
            yield path
        finally:
            path.unlink(missing_ok=True)


class FakeVault:
    def encrypt(self, data, purpose):
        return EncryptedBlob("key", b"nonce", data, purpose)

    def decrypt(self, blob, purpose):
        assert blob.purpose == purpose
        return blob.ciphertext


def test_toolbelt_service_dry_run_upload_and_cleanup(tmp_path):
    database = FakeDatabase()
    artifacts = FakeArtifacts(tmp_path)
    commands = []
    temp_dirs = []

    def runner(command, on_event):
        commands.append(command)
        list_path = Path(command[command.index("--list") + 1])
        temp_dirs.append(list_path.parent)
        assert list_path.read_text(encoding="utf-8").startswith("192.168.0.10,")
        on_event(
            {
                "event": "dry_run_ok" if "--commit" not in command else "upload_ok",
                "selector": "192.168.0.10",
                "message": "ok",
            }
        )

    service = ToolbeltBatchService(
        database, artifacts, FakeVault(), script_path=tmp_path / "toolbelt_uploader.py", runner=runner
    )

    dry_run = service.start(mode="dry-run", selectors=["192.168.0.10"])
    assert dry_run["status"] == "running"
    wait_until(lambda: len(commands) == 1)
    assert "--commit" not in commands[0]

    wait_until(lambda: database.get_setting(STATUS_KEY, {}).get("192.168.0.10|cert-1|dry-run"))
    latest = database.get_setting(STATUS_KEY)
    assert latest["192.168.0.10|cert-1|dry-run"]["ok"] is True

    service.start(mode="upload", selectors=["192.168.0.10"])
    wait_until(lambda: len(commands) == 2)
    assert "--commit" in commands[1]
    wait_until(lambda: all(not path.exists() for path in temp_dirs))
    assert all(not path.exists() for path in artifacts.materialized_paths)
    assert all(not path.exists() for path in temp_dirs)


def test_toolbelt_service_credentials_are_encrypted_and_not_returned(tmp_path):
    database = FakeDatabase()
    service = ToolbeltBatchService(
        database,
        FakeArtifacts(tmp_path),
        FakeVault(),
        script_path=tmp_path / "toolbelt_uploader.py",
        runner=lambda command, on_event: None,
    )

    service.save_credentials("192.168.0.10", username="admin", password="extron")

    devices = service.list_devices()
    assert devices[0]["credentials_saved"] is True
    payload = json.dumps(devices)
    assert '"password"' not in payload
    assert "admin" not in payload


def test_toolbelt_service_saves_serial_fallback_after_dry_run(tmp_path):
    database = FakeDatabase()
    commands = []

    def runner(command, on_event):
        commands.append(command)
        credential_path = Path(command[command.index("--device-password-file") + 1])
        credentials = json.loads(credential_path.read_text(encoding="utf-8"))
        resolved_path = Path(command[command.index("--resolved-credentials-file") + 1])
        if "--commit" not in command:
            assert credentials["192.168.0.10"]["password_candidates"] == ["extron", "__SERIAL__"]
            resolved_path.write_text(
                json.dumps(
                    {
                        "192.168.0.10": {
                            "username": "admin",
                            "password": "SERIAL123",
                        }
                    }
                ),
                encoding="utf-8",
            )
            on_event(
                {
                    "event": "credentials_resolved",
                    "selector": "192.168.0.10",
                    "message": "resolved",
                }
            )
            on_event({"event": "dry_run_ok", "selector": "192.168.0.10", "message": "ok"})
        else:
            assert credentials["192.168.0.10"] == {
                "username": "admin",
                "password": "SERIAL123",
            }
            on_event({"event": "upload_ok", "selector": "192.168.0.10", "message": "ok"})

    service = ToolbeltBatchService(
        database,
        FakeArtifacts(tmp_path),
        FakeVault(),
        script_path=tmp_path / "toolbelt_uploader.py",
        runner=runner,
    )

    service.start(mode="dry-run", selectors=["192.168.0.10"])
    wait_until(lambda: database.get_secret("toolbelt-device-credentials:192.168.0.10") is not None)
    devices = service.list_devices()
    assert devices[0]["credentials_saved"] is True
    payload = json.dumps(devices)
    assert "SERIAL123" not in payload

    service.start(mode="upload", selectors=["192.168.0.10"])
    wait_until(lambda: len(commands) == 2)
    assert "--commit" in commands[1]


def test_toolbelt_service_uses_child_mode_when_frozen(tmp_path, monkeypatch):
    database = FakeDatabase()
    service = ToolbeltBatchService(
        database,
        FakeArtifacts(tmp_path),
        FakeVault(),
        script_path=tmp_path / "toolbelt_uploader.py",
        runner=lambda command, on_event: None,
    )

    monkeypatch.setattr("certmon.toolbelt.sys.frozen", True, raising=False)
    monkeypatch.setattr("certmon.toolbelt.sys.executable", r"C:\CertMon\CertMon.exe")

    assert service._uploader_entrypoint() == [
        r"C:\CertMon\CertMon.exe",
        "--toolbelt-uploader",
    ]


def test_toolbelt_service_marks_devices_failed_when_runner_fails(tmp_path):
    database = FakeDatabase()

    def runner(command, on_event):
        raise RuntimeError("Extron Toolbelt is not installed and not running")

    service = ToolbeltBatchService(
        database,
        FakeArtifacts(tmp_path),
        FakeVault(),
        script_path=tmp_path / "toolbelt_uploader.py",
        runner=runner,
    )

    run = service.start(mode="dry-run", selectors=["192.168.0.10"])
    run_id = run["id"]

    wait_until(lambda: service.get_run(run_id)["status"] == "failed")
    failed = service.get_run(run_id)

    assert "Toolbelt is not installed or not running" in failed["error"]
    assert failed["devices"]["192.168.0.10"]["event"] == "dry_run_failed"
    assert failed["devices"]["192.168.0.10"]["ok"] is False
    latest = database.get_setting(STATUS_KEY)
    assert latest["192.168.0.10|cert-1|dry-run"]["event"] == "dry_run_failed"

def test_toolbelt_service_empty_selection_runs_no_devices(tmp_path):
    database = FakeDatabase()
    service = ToolbeltBatchService(
        database,
        FakeArtifacts(tmp_path),
        FakeVault(),
        script_path=tmp_path / "toolbelt_uploader.py",
        runner=lambda command, on_event: None,
    )

    service.save_selection([])
    devices = service.list_devices()

    assert devices[0]["selected"] is False
    try:
        service.start(mode="dry-run", selectors=[])
    except ValueError as error:
        assert "No Toolbelt devices selected" in str(error)
    else:
        raise AssertionError("empty explicit selection should not run all devices")


def test_toolbelt_service_blocks_not_extron_ready_devices(tmp_path):
    database = FakeDatabase()
    database.certificates[0]["profile"] = "generic-rsa"
    service = ToolbeltBatchService(
        database,
        FakeArtifacts(tmp_path),
        FakeVault(),
        script_path=tmp_path / "toolbelt_uploader.py",
        runner=lambda command, on_event: None,
    )

    try:
        service.start(mode="dry-run", selectors=["192.168.0.10"])
    except ValueError as error:
        assert "Extron-ready Local CA certificates" in str(error)
    else:
        raise AssertionError("non-Extron certificates should not start Toolbelt")

def test_toolbelt_service_prefers_ip_identifier_for_selector(tmp_path):
    database = FakeDatabase()
    database.certificates[0]["device_name"] = "IPLP"
    database.certificates[0]["identifiers"] = ["IPLP", "192.168.0.20"]
    service = ToolbeltBatchService(
        database,
        FakeArtifacts(tmp_path),
        FakeVault(),
        script_path=tmp_path / "toolbelt_uploader.py",
        runner=lambda command, on_event: None,
    )

    devices = service.list_devices()

    assert devices[0]["label"] == "IPLP"
    assert devices[0]["selector"] == "192.168.0.20"

def test_toolbelt_service_clears_stale_statuses_when_run_starts(tmp_path):
    database = FakeDatabase()
    database.put_setting(
        STATUS_KEY,
        {
            "192.168.0.10|cert-1|dry-run": {"ok": False, "message": "old dry-run"},
            "192.168.0.10|cert-1|upload": {"ok": True, "message": "old upload"},
        },
    )
    started = []
    service = ToolbeltBatchService(
        database,
        FakeArtifacts(tmp_path),
        FakeVault(),
        script_path=tmp_path / "toolbelt_uploader.py",
        runner=lambda command, on_event: started.append(command),
    )

    service.start(mode="dry-run", selectors=["192.168.0.10"])
    wait_until(lambda: started)

    devices = service.list_devices()
    assert devices[0]["dry_run"] is None
    assert devices[0]["upload"] is None


def test_toolbelt_service_reset_upload_tab_state_clears_status_and_selection(tmp_path):
    database = FakeDatabase()
    database.put_setting(
        STATUS_KEY,
        {
            "192.168.0.10|cert-1|dry-run": {"ok": False, "message": "old dry-run"},
            "192.168.0.10|cert-1|upload": {"ok": True, "message": "old upload"},
        },
    )
    service = ToolbeltBatchService(
        database,
        FakeArtifacts(tmp_path),
        FakeVault(),
        script_path=tmp_path / "toolbelt_uploader.py",
        runner=lambda command, on_event: None,
    )
    service.save_selection([])

    devices = service.reset_upload_tab_state()

    assert database.get_setting(STATUS_KEY) == {}
    assert devices[0]["selected"] is True
    assert devices[0]["dry_run"] is None
    assert devices[0]["upload"] is None


def test_toolbelt_service_sanitizer_does_not_redact_password_substrings():
    message = {"message": "all known Toolbelt passwords failed"}

    sanitized = ToolbeltBatchService._sanitize(message)

    assert sanitized["message"] == "all known Toolbelt passwords failed"
