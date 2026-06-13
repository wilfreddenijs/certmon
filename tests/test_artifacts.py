from pathlib import Path
import base64
import json

import pytest

from certmon.artifacts import ArtifactStore, PrivateArtifactError
from certmon.vault import MemoryKeyProtector, Vault


def make_store(tmp_path):
    vault = Vault(tmp_path / "vault", MemoryKeyProtector())
    vault.initialize()
    return ArtifactStore(tmp_path / "certificates", vault)


def test_private_artifacts_are_encrypted_and_not_publicly_readable(tmp_path):
    store = make_store(tmp_path)
    store.create_certificate_set(
        "cert-1",
        {"certificate.pem": b"leaf"},
        {"private-key.pem": b"private"},
        {"profile": "generic-rsa"},
    )

    assert store.read_public("cert-1", "certificate.pem") == b"leaf"
    envelope = json.loads(
        (tmp_path / "certificates" / "cert-1" / "private-key.pem.enc").read_text()
    )
    assert base64.b64decode(envelope["ciphertext"]) != b"private"
    assert "plaintext" not in envelope
    with pytest.raises(PrivateArtifactError):
        store.read_public("cert-1", "private-key.pem")


def test_materialized_private_file_is_removed_after_error(tmp_path):
    store = make_store(tmp_path)
    store.create_certificate_set(
        "cert-1",
        {},
        {"private-key.pem": b"private"},
        {},
    )

    materialized = None
    with pytest.raises(RuntimeError):
        with store.materialize_private("cert-1", "private-key.pem") as path:
            materialized = Path(path)
            assert materialized.read_bytes() == b"private"
            raise RuntimeError("deployment failed")

    assert materialized is not None
    assert not materialized.exists()
