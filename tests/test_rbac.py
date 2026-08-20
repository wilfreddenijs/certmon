from certmon.auth import hash_password

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
