from certmon.auth import hash_password

from tests.test_auth_api import load_app


def auth_headers(client):
    status = client.get("/api/auth/status").get_json()
    return {status["csrf_header"]: status["csrf_token"]}


def test_login_and_logout_are_audited(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch)
    client = module.app.test_client()
    client.post(
        "/api/auth/setup-first-admin",
        json={"username": "admin", "password": "correct horse"},
    )
    headers = auth_headers(client)
    client.post("/api/auth/logout", headers=headers)

    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong password"},
    ).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "correct horse"},
    ).status_code == 200

    events = client.get("/api/audit").get_json()
    event_types = [event["event_type"] for event in events]

    assert "first_admin_created" in event_types
    assert "logout" in event_types
    assert "login_failed" in event_types
    assert "login_succeeded" in event_types


def test_audit_endpoint_times_out_when_store_hangs(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch)
    client = module.app.test_client()
    client.post(
        "/api/auth/setup-first-admin",
        json={"username": "admin", "password": "correct horse"},
    )

    def hang(*_args, **_kwargs):
        import time

        time.sleep(1)

    monkeypatch.setattr(module, "AUDIT_QUERY_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(module.audit_service, "list", hang)

    response = client.get("/api/audit")

    assert response.status_code == 504
    assert response.get_json()["error"] == "Audit log query timed out"


def test_viewer_cannot_read_audit_log(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch)
    module.database.create_user(
        user_id="viewer-1",
        username="viewer",
        password_hash=hash_password("correct horse"),
        roles=["viewer"],
    )
    client = module.app.test_client()
    client.post(
        "/api/auth/login",
        json={"username": "viewer", "password": "correct horse"},
    )

    response = client.get("/api/audit")

    assert response.status_code == 403


def test_audit_redacts_secret_like_details(tmp_path):
    from certmon.audit import AuditService
    from certmon.db import Database

    db = Database(tmp_path / "certmon.db")
    db.initialize()
    service = AuditService(db)

    service.record("token_saved", details={"api_token": "secret", "zone": "example.com"})

    event = service.list()[0]
    assert event["details"] == {"api_token": "[redacted]", "zone": "example.com"}
