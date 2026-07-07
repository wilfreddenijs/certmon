import importlib


def load_app(tmp_data_dir, monkeypatch, *, server_mode=True):
    monkeypatch.setenv("CERTMON_DATA_DIR", str(tmp_data_dir))
    if server_mode:
        monkeypatch.setenv("CERTMON_SERVER_MODE", "1")
        monkeypatch.setenv("CERTMON_BIND_HOST", "127.0.0.1")
    else:
        monkeypatch.delenv("CERTMON_SERVER_MODE", raising=False)
        monkeypatch.delenv("CERTMON_BIND_HOST", raising=False)
    import app

    return importlib.reload(app)


def test_local_mode_does_not_require_authentication(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch, server_mode=False)

    response = module.app.test_client().get("/api/data")

    assert response.status_code == 200


def test_server_mode_requires_authentication_before_api_access(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch)
    client = module.app.test_client()

    assert client.get("/api/data").status_code == 401
    status = client.get("/api/auth/status").get_json()

    assert status["server_mode"] is True
    assert status["authenticated"] is False
    assert status["first_admin_required"] is True


def test_first_admin_setup_creates_session_and_allows_api(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch)
    client = module.app.test_client()

    created = client.post(
        "/api/auth/setup-first-admin",
        json={"username": "admin", "password": "correct horse"},
    )

    assert created.status_code == 200
    assert created.get_json()["user"]["roles"][0] == "admin"
    assert client.get("/api/data").status_code == 200
    me = client.get("/api/auth/me").get_json()
    assert me["user"]["username"] == "admin"


def test_login_rejects_wrong_password_and_accepts_correct_password(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch)
    setup_client = module.app.test_client()
    setup_client.post(
        "/api/auth/setup-first-admin",
        json={"username": "admin", "password": "correct horse"},
    )

    client = module.app.test_client()
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong password"},
    ).status_code == 401

    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "correct horse"},
    )

    assert login.status_code == 200
    assert client.get("/api/data").status_code == 200


def test_logout_removes_session(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch)
    client = module.app.test_client()
    client.post(
        "/api/auth/setup-first-admin",
        json={"username": "admin", "password": "correct horse"},
    )
    status = client.get("/api/auth/status").get_json()

    assert client.post(
        "/api/auth/logout",
        headers={status["csrf_header"]: status["csrf_token"]},
    ).status_code == 200

    assert client.get("/api/data").status_code == 401
