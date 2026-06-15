import pytest

from certmon.vault import MemoryKeyProtector, Vault
from certmon.db import Database


def test_recovery_package_restores_master_key(tmp_path):
    original = Vault(tmp_path / "original", MemoryKeyProtector())
    original.initialize()
    blob = original.encrypt(b"secret", purpose="device-key")
    package = original.create_recovery_package("correct horse battery staple")

    restored = Vault(tmp_path / "restored", MemoryKeyProtector())
    restored.restore_recovery_package(package, "correct horse battery staple")

    assert restored.decrypt(blob, purpose="device-key") == b"secret"


def test_recovery_package_rejects_wrong_passphrase(tmp_path):
    vault = Vault(tmp_path, MemoryKeyProtector())
    vault.initialize()
    package = vault.create_recovery_package("correct")

    with pytest.raises(ValueError, match="Invalid recovery passphrase"):
        Vault(tmp_path / "other", MemoryKeyProtector()).restore_recovery_package(
            package, "wrong"
        )


def test_master_key_can_be_rewrapped_for_new_service_account(tmp_path):
    first = Vault(tmp_path, MemoryKeyProtector(b"first"))
    first.initialize()
    blob = first.encrypt(b"secret", purpose="device-key")

    second_protector = MemoryKeyProtector(b"second")
    first.rewrap(second_protector)

    reopened = Vault(tmp_path, second_protector)
    assert reopened.decrypt(blob, purpose="device-key") == b"secret"


def test_interrupted_master_key_rotation_resumes(tmp_path):
    protector = MemoryKeyProtector()
    vault = Vault(tmp_path / "vault", protector)
    vault.initialize()
    db = Database(tmp_path / "certmon.db")
    db.initialize()
    for index in range(2):
        db.put_secret(
            f"secret-{index}",
            vault.encrypt(f"value-{index}".encode(), purpose="device-key"),
        )

    with pytest.raises(RuntimeError, match="Simulated rotation interruption"):
        db.rotate_secrets(vault, interrupt_after=1)

    reopened = Vault(tmp_path / "vault", protector)
    db.rotate_secrets(reopened)

    for index in range(2):
        blob = db.get_secret(f"secret-{index}")
        assert reopened.decrypt(blob, purpose="device-key") == f"value-{index}".encode()
