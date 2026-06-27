import base64
import ctypes
import hashlib
import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


class KeyProtector(Protocol):
    def protect(self, plaintext: bytes) -> bytes: ...

    def unprotect(self, protected: bytes) -> bytes: ...


@dataclass
class EncryptedBlob:
    key_id: str
    nonce: bytes
    ciphertext: bytes
    purpose: str


class MemoryKeyProtector:
    """Deterministic in-memory protector for tests only."""

    def __init__(self, seed=b"certmon-test-protector"):
        self._key = hashlib.sha256(seed).digest()

    def protect(self, plaintext):
        nonce = os.urandom(12)
        return nonce + AESGCM(self._key).encrypt(nonce, plaintext, b"master-key")

    def unprotect(self, protected):
        return AESGCM(self._key).decrypt(
            protected[:12], protected[12:], b"master-key"
        )


class WindowsDpapiProtector:
    CRYPTPROTECT_UI_FORBIDDEN = 0x1

    class DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.c_uint32),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("Windows DPAPI is only available on Windows")

    @classmethod
    def _blob(cls, data):
        buffer = ctypes.create_string_buffer(data)
        blob = cls.DataBlob(
            len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        )
        return blob, buffer

    def protect(self, plaintext):
        source, source_buffer = self._blob(plaintext)
        output = self.DataBlob()
        crypt32 = ctypes.windll.crypt32
        if not crypt32.CryptProtectData(
            ctypes.byref(source),
            "CertMon master key",
            None,
            None,
            None,
            self.CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output.pbData)
            del source_buffer

    def unprotect(self, protected):
        source, source_buffer = self._blob(protected)
        output = self.DataBlob()
        crypt32 = ctypes.windll.crypt32
        if not crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            self.CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output.pbData)
            del source_buffer


class Vault:
    MASTER_FILE = "master-key.json"
    PENDING_MASTER_FILE = "pending-master-key.json"

    def __init__(self, root: Path, protector: KeyProtector):
        self.root = Path(root)
        self.protector = protector
        self._master_key = None
        self._key_id = None
        self._pending_master_key = None
        self._pending_key_id = None

    @property
    def master_path(self):
        return self.root / self.MASTER_FILE

    @property
    def pending_master_path(self):
        return self.root / self.PENDING_MASTER_FILE

    def initialize(self):
        self.root.mkdir(parents=True, exist_ok=True)
        if self.master_path.exists():
            self._load_master_key()
            return
        self._master_key = AESGCM.generate_key(bit_length=256)
        self._key_id = str(uuid.uuid4())
        self._write_master_key(self.protector.protect(self._master_key))

    def encrypt(self, plaintext: bytes, *, purpose: str):
        self._ensure_loaded()
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._master_key).encrypt(
            nonce, plaintext, purpose.encode("utf-8")
        )
        return EncryptedBlob(self._key_id, nonce, ciphertext, purpose)

    def decrypt(self, blob: EncryptedBlob, *, purpose: str):
        self._ensure_loaded()
        if blob.key_id == self._key_id:
            key = self._master_key
        elif blob.key_id == self._pending_key_id:
            key = self._pending_master_key
        else:
            raise ValueError("Encrypted data uses an unknown master key")
        return AESGCM(key).decrypt(
            blob.nonce, blob.ciphertext, purpose.encode("utf-8")
        )

    def begin_rotation(self):
        self._ensure_loaded()
        if self._pending_master_key is not None:
            return self._pending_key_id
        self._pending_master_key = AESGCM.generate_key(bit_length=256)
        self._pending_key_id = str(uuid.uuid4())
        self._write_key_file(
            self.pending_master_path,
            self._pending_key_id,
            self.protector.protect(self._pending_master_key),
        )
        return self._pending_key_id

    def encrypt_for_rotation(self, plaintext: bytes, *, purpose: str):
        if self._pending_master_key is None:
            self.begin_rotation()
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._pending_master_key).encrypt(
            nonce, plaintext, purpose.encode("utf-8")
        )
        return EncryptedBlob(
            self._pending_key_id, nonce, ciphertext, purpose
        )

    def activate_pending_key(self):
        if self._pending_master_key is None:
            raise RuntimeError("No pending master key")
        self._master_key = self._pending_master_key
        self._key_id = self._pending_key_id
        self._write_master_key(self.protector.protect(self._master_key))
        self.pending_master_path.unlink(missing_ok=True)
        self._pending_master_key = None
        self._pending_key_id = None

    def create_recovery_package(self, passphrase: str):
        self._ensure_loaded()
        salt = os.urandom(16)
        wrapping_key = _derive_recovery_key(passphrase, salt)
        nonce = os.urandom(12)
        ciphertext = AESGCM(wrapping_key).encrypt(
            nonce, self._master_key, self._key_id.encode("ascii")
        )
        return json.dumps(
            {
                "version": 1,
                "kdf": {"name": "scrypt", "n": 16384, "r": 8, "p": 1},
                "salt": _b64(salt),
                "nonce": _b64(nonce),
                "ciphertext": _b64(ciphertext),
                "key_id": self._key_id,
            },
            sort_keys=True,
        ).encode("utf-8")

    def restore_recovery_package(self, package: bytes, passphrase: str):
        data = json.loads(package.decode("utf-8"))
        wrapping_key = _derive_recovery_key(passphrase, _unb64(data["salt"]))
        try:
            master_key = AESGCM(wrapping_key).decrypt(
                _unb64(data["nonce"]),
                _unb64(data["ciphertext"]),
                data["key_id"].encode("ascii"),
            )
        except InvalidTag as exc:
            raise ValueError("Invalid recovery passphrase") from exc
        self.root.mkdir(parents=True, exist_ok=True)
        self._master_key = master_key
        self._key_id = data["key_id"]
        self._write_master_key(self.protector.protect(master_key))

    def rewrap(self, new_protector: KeyProtector):
        self._ensure_loaded()
        self.protector = new_protector
        self._write_master_key(new_protector.protect(self._master_key))
        if self._pending_master_key is not None:
            self._write_key_file(
                self.pending_master_path,
                self._pending_key_id,
                new_protector.protect(self._pending_master_key),
            )

    def _ensure_loaded(self):
        if self._master_key is None:
            self._load_master_key()

    def _load_master_key(self):
        data = json.loads(self.master_path.read_text(encoding="utf-8"))
        self._key_id = data["key_id"]
        self._master_key = self.protector.unprotect(_unb64(data["protected"]))
        if self.pending_master_path.exists():
            pending = json.loads(
                self.pending_master_path.read_text(encoding="utf-8")
            )
            self._pending_key_id = pending["key_id"]
            self._pending_master_key = self.protector.unprotect(
                _unb64(pending["protected"])
            )

    def _write_master_key(self, protected):
        self._write_key_file(self.master_path, self._key_id, protected)

    def _write_key_file(self, path, key_id, protected):
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"version": 1, "key_id": key_id, "protected": _b64(protected)},
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)


def _derive_recovery_key(passphrase, salt):
    return Scrypt(salt=salt, length=32, n=16384, r=8, p=1).derive(
        passphrase.encode("utf-8")
    )


def _b64(value):
    return base64.b64encode(value).decode("ascii")


def _unb64(value):
    return base64.b64decode(value.encode("ascii"))
