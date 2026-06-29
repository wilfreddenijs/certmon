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
