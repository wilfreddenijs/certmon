from certmon.auth import hash_password
from certmon.permissions import Permission, permissions_for_roles

from tests.test_auth_api import load_app


def auth_headers(client):
    status = client.get("/api/auth/status").get_json()
    return {status["csrf_header"]: status["csrf_token"]}


def renewal_payload():
    return {
        "endpoint_host": "192.168.1.20",
        "endpoint_port": 443,
        "issuer_type": "acme",
        "identifiers": ["device.example.com"],
        "profile": "generic-rsa",
        "environment": "staging",
        "dns_provider": "manual",
    }


def create_viewer(module):
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
    return client


def test_admin_role_can_start_certificate_workflows(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch)
    client = module.app.test_client()
    client.post(
        "/api/auth/setup-first-admin",
        json={
            "username": "admin",
            "password": "correct horse",
            "password_confirmation": "correct horse",
        },
    )

    response = client.post(
        "/api/renew",
        json=renewal_payload(),
        headers=auth_headers(client),
    )

    assert response.status_code == 201


def test_viewer_role_cannot_start_certificate_workflows(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch)
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

    response = client.post(
        "/api/renew",
        json=renewal_payload(),
        headers=auth_headers(client),
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "Permission denied: issue_certificate"


def test_auth_status_exposes_only_sorted_effective_permissions(
    tmp_data_dir, monkeypatch
):
    server_module = load_app(tmp_data_dir, monkeypatch)
    anonymous = server_module.app.test_client().get("/api/auth/status").get_json()
    assert anonymous["permissions"] == []

    server_module.database.create_user(
        user_id="multi-role-1",
        username="multi-role",
        password_hash=hash_password("correct horse"),
        roles=["viewer", "ca_admin"],
    )
    client = server_module.app.test_client()
    assert client.post(
        "/api/auth/login",
        json={"username": "multi-role", "password": "correct horse"},
    ).status_code == 200
    assert client.get("/api/auth/status").get_json()["permissions"] == sorted(
        permission.value
        for permission in permissions_for_roles(["viewer", "ca_admin"])
    )

    desktop_module = load_app(tmp_data_dir / "desktop", monkeypatch, server_mode=False)
    assert desktop_module.app.test_client().get("/api/auth/status").get_json()[
        "permissions"
    ] == sorted(permission.value for permission in Permission)


def test_viewer_can_discover_only_existing_public_certificate_artifacts(
    tmp_data_dir, monkeypatch
):
    module = load_app(tmp_data_dir, monkeypatch)
    module.artifact_store.create_certificate_set(
        "cert-1",
        {
            "certificate.pem": b"public certificate",
            "request.csr": b"public request",
        },
        {"private-key.pem": b"private key", "combined.pem": b"combined key"},
        {},
    )
    module.database.put_certificate(
        "cert-1",
        {
            "kind": "leaf",
            "identifiers": ["device.example.com"],
            "profile": "generic-rsa",
            "secret": "must never be returned",
        },
    )
    client = create_viewer(module)

    catalog = client.get("/api/certificates/public")
    assert catalog.status_code == 200
    assert catalog.get_json() == [
        {
            "certificate_id": "cert-1",
            "identifiers": ["device.example.com"],
            "profile": "generic-rsa",
            "public_artifacts": ["certificate.pem", "request.csr"],
            "download_names": {name: module._certificate_download_filename("cert-1", name) for name in ["certificate.pem", "request.csr"]},
            "download_prefix": module._certificate_download_filename("cert-1", "certificate.pem").removesuffix("-certificate.pem"),
        }
    ]
    assert b"private" not in catalog.data.lower()
    assert b"secret" not in catalog.data.lower()
    for name, filename in catalog.get_json()[0]["download_names"].items():
        download = client.get(f"/api/certificates/cert-1/public/{name}")
        assert f'filename="{filename}"' in download.headers["Content-Disposition"]
    assert client.get("/api/certificates").status_code == 403
    assert client.get("/api/certificates/cert-1/public/certificate.pem").status_code == 200
    assert client.get("/api/certificates/cert-1/private/private-key.pem").status_code == 403


def test_viewer_is_denied_ca_and_upload_mutations_before_processing(
    tmp_data_dir, monkeypatch
):
    module = load_app(tmp_data_dir, monkeypatch)
    client = create_viewer(module)
    headers = auth_headers(client)

    assert client.post("/api/ca/issue", json={}, headers=headers).status_code == 403
    assert client.post("/api/ca/issue-bulk", json={}, headers=headers).status_code == 403
    assert client.delete("/api/ca/issued/missing", headers=headers).status_code == 403
    assert client.get("/api/upload/devices").status_code == 200
    assert client.post(
        "/api/upload/devices",
        json={"name": "Viewer device", "host": "192.0.2.1", "device_type": "extron"},
        headers=headers,
    ).status_code == 403
    assert client.patch(
        "/api/upload/devices/missing", json={"name": "Changed"}, headers=headers
    ).status_code == 403
    assert client.delete("/api/upload/devices/missing", headers=headers).status_code == 403
