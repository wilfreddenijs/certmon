import base64
import json
import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from certmon.vault import EncryptedBlob


class PrivateArtifactError(PermissionError):
    pass


class ArtifactStore:
    PRIVATE_NAMES = {"private-key.pem", "combined.pem"}

    def __init__(self, root: Path, vault):
        self.root = Path(root)
        self.vault = vault
        self.root.mkdir(parents=True, exist_ok=True)

    def create_certificate_set(
        self,
        certificate_id,
        public_files,
        private_files,
        metadata,
    ):
        target = self._certificate_dir(certificate_id)
        if target.exists():
            raise FileExistsError(f"Certificate {certificate_id} already exists")
        temporary = self.root / f".{certificate_id}.{uuid.uuid4().hex}.tmp"
        temporary.mkdir()
        try:
            for name, content in public_files.items():
                self._validate_name(name)
                if name in self.PRIVATE_NAMES:
                    raise PrivateArtifactError(f"{name} must be encrypted")
                (temporary / name).write_bytes(content)
            for name, content in private_files.items():
                self._validate_name(name)
                blob = self.vault.encrypt(
                    content, purpose=self._purpose(certificate_id, name)
                )
                (temporary / f"{name}.enc").write_text(
                    _serialize_blob(blob), encoding="utf-8"
                )
            (temporary / "metadata.json").write_text(
                json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
            )
            temporary.replace(target)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def has_certificate(self, certificate_id):
        return self._certificate_dir(certificate_id).is_dir()

    def read_public(self, certificate_id, name):
        self._validate_name(name)
        if name in self.PRIVATE_NAMES or name.endswith(".enc"):
            raise PrivateArtifactError(f"{name} is private")
        path = self._certificate_dir(certificate_id) / name
        return path.read_bytes()

    @contextmanager
    def materialize_private(self, certificate_id, name):
        self._validate_name(name)
        if name not in self.PRIVATE_NAMES:
            raise PrivateArtifactError(f"{name} is not a private artifact")
        encrypted_path = self._certificate_dir(certificate_id) / f"{name}.enc"
        blob = _deserialize_blob(encrypted_path.read_text(encoding="utf-8"))
        plaintext = self.vault.decrypt(
            blob, purpose=self._purpose(certificate_id, name)
        )
        temporary_dir = self.root / ".materialized"
        temporary_dir.mkdir(exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            dir=temporary_dir, prefix="certmon-", suffix=".pem", delete=False
        )
        path = Path(handle.name)
        try:
            handle.write(plaintext)
            handle.close()
            os.chmod(path, 0o600)
            yield path
        finally:
            if not handle.closed:
                handle.close()
            path.unlink(missing_ok=True)

    def _certificate_dir(self, certificate_id):
        if not certificate_id or Path(certificate_id).name != certificate_id:
            raise ValueError("Invalid certificate ID")
        return self.root / certificate_id

    @staticmethod
    def _validate_name(name):
        if not name or Path(name).name != name:
            raise ValueError("Invalid artifact name")

    @staticmethod
    def _purpose(certificate_id, name):
        return f"certificate-artifact:{certificate_id}:{name}"


def _serialize_blob(blob):
    return json.dumps(
        {
            "key_id": blob.key_id,
            "nonce": base64.b64encode(blob.nonce).decode("ascii"),
            "ciphertext": base64.b64encode(blob.ciphertext).decode("ascii"),
            "purpose": blob.purpose,
        },
        sort_keys=True,
    )


def _deserialize_blob(value):
    data = json.loads(value)
    return EncryptedBlob(
        key_id=data["key_id"],
        nonce=base64.b64decode(data["nonce"]),
        ciphertext=base64.b64decode(data["ciphertext"]),
        purpose=data["purpose"],
    )
