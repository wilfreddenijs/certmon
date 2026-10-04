import json
import os
import shutil
import stat
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from certmon.backup import BackupError, BackupService
from certmon.vault import Vault


class ServerBackupPackageError(ValueError):
    pass


class ServerBackupConflictError(ServerBackupPackageError):
    pass


@dataclass(frozen=True)
class ServerBackupPackageResult:
    backup_id: str
    path: Path
    created_at: str


@dataclass(frozen=True)
class StagedRestoreResult:
    backup_id: str
    staged_path: Path
    created_at: str
    activation_steps: tuple[str, ...]


class ServerBackupPackageService:
    VERSION = 1
    MAX_MEMBERS = 10_000
    MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
    README = (
        "CertMon full server backup\n\n"
        "This package contains encrypted CertMon data and a passphrase-encrypted "
        "recovery package. Restore it through CertMon, then follow the returned "
        "offline activation instructions.\n"
    )
    ACTIVATION_STEPS = (
        "Stop CertMon before changing the active data directory.",
        "Retain or rename the current data directory so it remains available for rollback.",
        "Rename the staged directory or configure CERTMON_DATA_DIR to use it.",
        "Start CertMon, sign in, and verify the Local CA, certificates, and audit history.",
        "Remove the old data directory only after the restored installation is accepted.",
    )

    def __init__(
        self,
        data_dir,
        database,
        vault,
        key_protector,
        *,
        mutation_lock=None,
    ):
        self.data_dir = Path(data_dir).resolve()
        self.database = database
        self.vault = vault
        self.key_protector = key_protector
        self.backup_service = BackupService(
            self.data_dir, database, mutation_lock=mutation_lock
        )

    def export_package(self, passphrase, output_file):
        if not isinstance(passphrase, str) or not passphrase.strip():
            raise ServerBackupPackageError("A nonblank backup passphrase is required")

        output_file = Path(output_file)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_zip = None
        try:
            with tempfile.TemporaryDirectory(prefix="certmon-server-backup-") as work:
                recovery_package = self.vault.create_recovery_package(passphrase)
                backup = self.backup_service.create_backup(
                    Path(work) / "backup", recovery_package
                )
                manifest = self._read_manifest(backup.path / "manifest.json")
                handle, temporary_name = tempfile.mkstemp(
                    prefix=f".{output_file.name}.",
                    suffix=".tmp",
                    dir=output_file.parent,
                )
                os.close(handle)
                temporary_zip = Path(temporary_name)
                with zipfile.ZipFile(
                    temporary_zip, "w", compression=zipfile.ZIP_DEFLATED
                ) as archive:
                    for source in sorted(
                        path for path in backup.path.rglob("*") if path.is_file()
                    ):
                        relative = source.relative_to(backup.path).as_posix()
                        archive.write(source, f"backup/{relative}")
                    archive.writestr("recovery-package.json", recovery_package)
                    archive.writestr("README.txt", self.README)
                temporary_zip.replace(output_file)
                temporary_zip = None
                return ServerBackupPackageResult(
                    backup.backup_id, output_file, manifest["created_at"]
                )
        except ServerBackupPackageError:
            raise
        except (BackupError, OSError, ValueError, zipfile.BadZipFile) as exc:
            raise ServerBackupPackageError("Unable to create server backup package") from exc
        finally:
            if temporary_zip is not None:
                temporary_zip.unlink(missing_ok=True)

    def stage_restore(self, package_file, passphrase, staging_parent):
        if not isinstance(passphrase, str) or not passphrase.strip():
            raise ServerBackupPackageError("A nonblank backup passphrase is required")

        staging_parent = Path(staging_parent).resolve()
        staging_parent.mkdir(parents=True, exist_ok=True)
        temporary_restore = None
        try:
            with tempfile.TemporaryDirectory(
                prefix=".certmon-restore-package-", dir=staging_parent
            ) as extracted:
                extracted = Path(extracted)
                with zipfile.ZipFile(package_file, "r") as archive:
                    members = self._validate_members(archive.infolist())
                    self._extract_members(archive, members, extracted)

                recovery_package = (extracted / "recovery-package.json").read_bytes()
                manifest = self._read_manifest(extracted / "backup" / "manifest.json")
                backup_id = self._validated_backup_id(manifest.get("backup_id"))
                final_path = staging_parent / f"{self.data_dir.name}-restore-{backup_id}"
                self._validate_destination(final_path)
                if final_path.exists():
                    raise ServerBackupConflictError("Restore destination already exists")

                temporary_restore = Path(
                    tempfile.mkdtemp(prefix=".certmon-restore-data-", dir=staging_parent)
                )
                temporary_restore.rmdir()
                self.backup_service.restore_backup(
                    extracted / "backup",
                    temporary_restore,
                    recovery_package,
                    expected_backup_id=backup_id,
                )
                restored_vault = Vault(
                    temporary_restore / "secrets", self.key_protector
                )
                restored_vault.restore_recovery_package(recovery_package, passphrase)
                temporary_restore.replace(final_path)
                temporary_restore = None
                return StagedRestoreResult(
                    backup_id,
                    final_path,
                    manifest["created_at"],
                    self.ACTIVATION_STEPS,
                )
        except ServerBackupConflictError:
            raise
        except ServerBackupPackageError:
            raise
        except (BackupError, OSError, ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
            raise ServerBackupPackageError("Invalid server backup package or passphrase") from exc
        finally:
            if temporary_restore is not None:
                shutil.rmtree(temporary_restore, ignore_errors=True)

    def _validate_members(self, members):
        if len(members) > self.MAX_MEMBERS:
            raise ServerBackupPackageError("Backup archive contains too many members")
        if sum(member.file_size for member in members) > self.MAX_UNCOMPRESSED_BYTES:
            raise ServerBackupPackageError("Backup archive is too large when extracted")

        seen = set()
        files = set()
        for member in members:
            name = member.filename
            if "\\" in name:
                raise ServerBackupPackageError("Backup archive contains an invalid path")
            path = PurePosixPath(name)
            normalized = name.rstrip("/")
            key = normalized.casefold()
            if not normalized or path.is_absolute() or ".." in path.parts:
                raise ServerBackupPackageError("Backup archive contains an unsafe path")
            if key in seen:
                raise ServerBackupPackageError("Backup archive contains duplicate members")
            seen.add(key)

            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ServerBackupPackageError("Backup archive contains a link")
            if not self._is_allowed_member(normalized, member.is_dir()):
                raise ServerBackupPackageError("Backup archive contains an unexpected member")
            if not member.is_dir():
                files.add(normalized)

        required = {"backup/manifest.json", "backup/certmon.db", "recovery-package.json", "README.txt"}
        if not required.issubset(files):
            raise ServerBackupPackageError("Backup archive is incomplete")
        return members

    @staticmethod
    def _is_allowed_member(name, is_directory):
        if name in {"recovery-package.json", "README.txt", "backup/manifest.json", "backup/certmon.db"}:
            return not is_directory
        if name in {"backup", "backup/certificates", "backup/secrets"}:
            return is_directory
        return name.startswith("backup/certificates/") or name.startswith("backup/secrets/")

    @staticmethod
    def _extract_members(archive, members, destination):
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.filename).parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)

    def _validate_destination(self, destination):
        destination = destination.resolve()
        if destination == self.data_dir or self.data_dir in destination.parents:
            raise ServerBackupPackageError(
                "Restore destination must be outside the active data directory"
            )

    @staticmethod
    def _read_manifest(path):
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            return envelope["manifest"]
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise ServerBackupPackageError("Invalid backup manifest") from exc

    @staticmethod
    def _validated_backup_id(value):
        try:
            parsed = uuid.UUID(value)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ServerBackupPackageError("Invalid backup ID") from exc
        if str(parsed) != value:
            raise ServerBackupPackageError("Invalid backup ID")
        return value
