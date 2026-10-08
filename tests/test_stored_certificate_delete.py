import pytest

from certmon.auth import hash_password
from tests.test_auth_api import load_app
from tests.test_audit_api import auth_headers


def seed_certificate(module, certificate_id="stored-leaf", issuer="acme", kind="leaf"):
    metadata = {"kind": kind, "issuer_type": issuer, "profile": "generic-rsa",
                "identifiers": ["device.example.com"]}
    module.artifact_store.create_certificate_set(certificate_id,
        {"certificate.pem": b"public"}, {"private-key.pem": b"private"}, metadata)
    module.database.put_certificate(certificate_id, metadata)
    return certificate_id


@pytest.mark.parametrize("issuer", ["acme", "external_ca", "local_ca"])
def test_delete_stored_leaf_removes_files_metadata_and_audits(tmp_data_dir, monkeypatch, issuer):
    module = load_app(tmp_data_dir, monkeypatch, server_mode=False)
    certificate_id = seed_certificate(module, issuer=issuer)
    seed_certificate(module, certificate_id="other-leaf", issuer=issuer)
    module.toolbelt_service.save_credentials("device.example.com", username="admin", password="individual-password")
    credentials_before = module.toolbelt_service._credentials_for("device.example.com")
    client = module.app.test_client()
    listed = client.get("/api/certificates/public").get_json()
    item = next(c for c in listed if c["certificate_id"] == certificate_id)
    assert item["created_at"] == module.database.get_certificate(certificate_id)["created_at"]
    response = client.delete(f"/api/certificates/{certificate_id}")
    assert response.status_code == 200
    assert module.database.get_certificate(certificate_id) is None
    assert not module.artifact_store.has_certificate(certificate_id)
    assert module.artifact_store.has_certificate("other-leaf")
    assert module.toolbelt_service._credentials_for("device.example.com") == credentials_before
    assert all(c["certificate_id"] != certificate_id for c in client.get("/api/certificates/public").get_json())
    event = module.database.list_audit_events()[0]
    assert event["event_type"] == "stored_certificate_deleted"
    assert event["target"] == certificate_id
    assert event["details"]["identifiers"] == ["device.example.com"]


def test_missing_or_root_certificate_cannot_be_deleted(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch, server_mode=False)
    seed_certificate(module, certificate_id="root", issuer="local_ca", kind="ca")
    client = module.app.test_client()
    assert client.delete("/api/certificates/missing").status_code == 404
    assert client.delete("/api/certificates/root").status_code == 404
    assert module.database.get_certificate("root") is not None
    assert module.artifact_store.has_certificate("root")


def test_failed_file_removal_keeps_certificate_entry(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch, server_mode=False)
    seed_certificate(module)
    def fail(_certificate_id):
        raise PermissionError("file locked")
    monkeypatch.setattr(module.artifact_store, "delete_certificate_set", fail)
    response = module.app.test_client().delete("/api/certificates/stored-leaf")
    assert response.status_code == 500
    assert module.database.get_certificate("stored-leaf") is not None
    assert module.artifact_store.has_certificate("stored-leaf")
    assert module.database.list_audit_events()[0]["success"] is False


@pytest.mark.parametrize("role,issuer,status", [
    ("viewer", "acme", 403), ("security_admin", "acme", 403),
    ("operator", "acme", 200), ("operator", "local_ca", 403),
    ("ca_admin", "local_ca", 200), ("admin", "external_ca", 200)])
def test_certificate_delete_permissions_and_csrf(tmp_data_dir, monkeypatch, role, issuer, status):
    module = load_app(tmp_data_dir, monkeypatch)
    seed_certificate(module, issuer=issuer)
    module.database.create_user(user_id="test", username="test",
        password_hash=hash_password("correct horse"), roles=[role])
    client = module.app.test_client()
    assert client.delete("/api/certificates/stored-leaf").status_code == 401
    client.post("/api/auth/login", json={"username": "test", "password": "correct horse"})
    assert client.delete("/api/certificates/stored-leaf").status_code == 403
    assert client.delete("/api/certificates/stored-leaf", headers=auth_headers(client)).status_code == status
