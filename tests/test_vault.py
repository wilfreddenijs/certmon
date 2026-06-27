import pytest
from cryptography.exceptions import InvalidTag

from certmon.vault import MemoryKeyProtector, Vault


def test_vault_round_trip_uses_unique_ciphertexts(tmp_path):
    vault = Vault(tmp_path, MemoryKeyProtector())
    vault.initialize()

    first = vault.encrypt(b"private-key", purpose="device-key")
    second = vault.encrypt(b"private-key", purpose="device-key")

    assert first.ciphertext != second.ciphertext
    assert vault.decrypt(first, purpose="device-key") == b"private-key"


def test_authenticated_metadata_cannot_be_changed(tmp_path):
    vault = Vault(tmp_path, MemoryKeyProtector())
    vault.initialize()
    blob = vault.encrypt(b"secret", purpose="cloudflare-token")

    with pytest.raises(InvalidTag):
        vault.decrypt(blob, purpose="device-password")
