import hashlib
import hmac
import json
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from certmon.artifacts import ARTIFACT_MUTATION_LOCK


class BackupError(ValueError):
    pass


@dataclass(frozen=True)
class BackupResult:
    backup_id: str
    path: Path


class BackupService:
    VERSION = 1

    def __init__(self, data_dir, database, *, mutation_lock=None):
        self.data_dir = Path(data_dir)
        self.database = database
        self.mutation_lock = mutation_lock or ARTIFACT_MUTATION_LOCK

    def create_backup(self, backup_root, recovery_package):
        backup_id = str(uuid.uuid4())
        backup_root = Path(backup_root)
        target = backup_root / backup_id
        backup_root.mkdir(parents=True, exist_ok=True)
        target.mkdir()
        try:
            with self.mutation_lock:
                self._backup_database(target / "certmon.db")
                for name in ("certificates", "secrets"):
                    source = self.data_dir / name
                    if source.exists():
                        shutil.copytree(source, target / name)
            manifest = self._build_manifest(target, backup_id, recovery_package)
            envelope = {
                "manifest": manifest,
                "hmac": self.sign_manifest(manifest, recovery_package),
            }
            (target / "manifest.json").write_text(
                json.dumps(envelope, indent=2, sort_keys=True), encoding="utf-8"
            )
            return BackupResult(backup_id, target)
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise

    def restore_backup(
        self,
        backup_path,
        restore_dir,
        recovery_package,
        *,
        expected_backup_id=None,
    ):
        backup_path = Path(backup_path)
        restore_dir = Path(restore_dir)
        if restore_dir.exists():
            raise BackupError("Restore directory already exists")
        manifest = self._load_and_verify_manifest(backup_path, recovery_package)
        if expected_backup_id and manifest["backup_id"] != expected_backup_id:
            raise BackupError("Backup ID does not match the requested backup ID")
        self._verify_files(backup_path, manifest)
        self._verify_representative_key(backup_path, manifest)

        try:
            shutil.copytree(
                backup_path,
                restore_dir,
                ignore=shutil.ignore_patterns("manifest.json"),
            )
        except Exception:
            shutil.rmtree(restore_dir, ignore_errors=True)
            raise
        return restore_dir

    def sign_manifest(self, manifest, recovery_package):
        key = self._manifest_key(recovery_package)
        payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        return hmac.new(key, payload, hashlib.sha256).hexdigest()

    def _backup_database(self, target):
        with self.database.connect() as source, sqlite3.connect(target) as destination:
            source.backup(destination)

    def _build_manifest(self, root, backup_id, recovery_package):
        files = self._file_hashes(root)
        key_file = root / "secrets" / "master-key.json"
        representative = None
        if key_file.exists():
            key_data = json.loads(key_file.read_text(encoding="utf-8"))
            representative = hashlib.sha256(key_data["key_id"].encode()).hexdigest()
        return {
            "version": self.VERSION,
            "backup_id": backup_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "recovery_package_fingerprint": hashlib.sha256(recovery_package).hexdigest(),
            "representative_key_fingerprint": representative,
            "files": files,
        }

    def _load_and_verify_manifest(self, backup_path, recovery_package):
        try:
            envelope = json.loads((backup_path / "manifest.json").read_text(encoding="utf-8"))
            manifest = envelope["manifest"]
            signature = envelope["hmac"]
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise BackupError("Invalid backup manifest") from exc
        if manifest.get("version") != self.VERSION:
            raise BackupError("Unsupported backup manifest version")
        package_fingerprint = hashlib.sha256(recovery_package).hexdigest()
        if not hmac.compare_digest(
            manifest.get("recovery_package_fingerprint", ""), package_fingerprint
        ):
            raise BackupError("Backup does not match this recovery package")
        expected = self.sign_manifest(manifest, recovery_package)
        if not hmac.compare_digest(signature, expected):
            raise BackupError("Backup manifest authentication failed")
        return manifest

    def _verify_files(self, backup_path, manifest):
        expected = manifest.get("files", {})
        actual = self._file_hashes(backup_path, exclude={"manifest.json"})
        if expected.keys() != actual.keys():
            raise BackupError("Backup file hash mismatch")
        for name, digest in expected.items():
            if not hmac.compare_digest(digest, actual[name]):
                raise BackupError(f"Backup file hash mismatch: {name}")

    def _verify_representative_key(self, backup_path, manifest):
        expected = manifest.get("representative_key_fingerprint")
        key_path = backup_path / "secrets" / "master-key.json"
        if expected is None and not key_path.exists():
            return
        try:
            key_id = json.loads(key_path.read_text(encoding="utf-8"))["key_id"]
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise BackupError("Representative key fingerprint cannot be verified") from exc
        actual = hashlib.sha256(key_id.encode()).hexdigest()
        if not hmac.compare_digest(expected or "", actual):
            raise BackupError("Representative key fingerprint mismatch")

    @staticmethod
    def _manifest_key(recovery_package):
        return hashlib.sha256(b"certmon-backup-manifest-v1\0" + recovery_package).digest()

    @staticmethod
    def _file_hashes(root, exclude=None):
        exclude = exclude or set()
        hashes = {}
        for path in sorted(p for p in Path(root).rglob("*") if p.is_file()):
            name = path.relative_to(root).as_posix()
            if name in exclude:
                continue
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        return hashes
