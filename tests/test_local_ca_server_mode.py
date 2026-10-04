import zipfile
import io

from certmon.auth import hash_password

from tests.test_auth_api import load_app
from tests.test_ca_api import FakeArtifacts


def auth_headers(client):
    status = client.get("/api/auth/status").get_json()
    return {status["csrf_header"]: status["csrf_token"]}


def test_trust_bundle_contains_only_public_ca_files(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch, server_mode=False)
    monkeypatch.setattr(module, "artifact_store", FakeArtifacts())

    response = module.app.test_client().get("/api/ca/trust-bundle")

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert set(archive.namelist()) == {"certmon-ca.crt", "README.txt"}
        assert b"BEGIN CERTIFICATE" in archive.read("certmon-ca.crt")
        assert b"private key" in archive.read("README.txt").lower()


def test_viewer_can_download_trust_bundle_but_cannot_manage_ca(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch)
    monkeypatch.setattr(module, "artifact_store", FakeArtifacts())
    module.database.create_user(
        user_id="viewer-1",
        username="viewer",
        password_hash=hash_password("correct horse"),
        roles=["viewer"],
    )
    client = module.app.test_client()
    assert client.post(
        "/api/auth/login",
        json={"username": "viewer", "password": "correct horse"},
    ).status_code == 200

    assert client.get("/api/ca/trust-bundle").status_code == 200
    assert client.post(
        "/api/ca/generate",
        headers=auth_headers(client),
    ).status_code == 403


def test_ca_backup_export_requires_private_key_permission(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch)
    module.database.create_user(
        user_id="operator-1",
        username="operator",
        password_hash=hash_password("correct horse"),
        roles=["operator"],
    )
    client = module.app.test_client()
    client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "correct horse"},
    )

    response = client.post(
        "/api/ca/backup/export",
        json={"passphrase": "correct horse"},
        headers=auth_headers(client),
    )

    assert response.status_code == 403
