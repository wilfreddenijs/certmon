from tests.test_auth_api import load_app


def authenticated_client(module):
    client = module.app.test_client()
    client.post(
        "/api/auth/setup-first-admin",
        json={"username": "admin", "password": "correct horse"},
    )
    status = client.get("/api/auth/status").get_json()
    return client, {status["csrf_header"]: status["csrf_token"]}


def test_server_mode_blocks_mutating_routes_without_csrf(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch)
    client, _headers = authenticated_client(module)

    response = client.post("/api/hosts", json={"host": "example.test", "port": 443})

    assert response.status_code == 403
    assert response.get_json()["error"] == "CSRF token required"


def test_server_mode_blocks_renew_without_csrf(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch)
    client, _headers = authenticated_client(module)

    response = client.post(
        "/api/renew",
        json={
            "endpoint_host": "127.0.0.1",
            "endpoint_port": 443,
            "issuer_type": "local-ca",
            "identifiers": ["uat-csrf-test.local"],
            "profile": "generic-rsa",
        },
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "CSRF token required"


def test_server_mode_accepts_mutating_routes_with_csrf(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch)
    client, headers = authenticated_client(module)

    response = client.post(
        "/api/hosts",
        json={"host": "example.test", "port": 443},
        headers=headers,
    )

    assert response.status_code == 200


def test_local_mode_does_not_require_csrf(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch, server_mode=False)
    client = module.app.test_client()

    response = client.post("/api/hosts", json={"host": "example.test", "port": 443})

    assert response.status_code == 200
