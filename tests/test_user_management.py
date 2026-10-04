import pytest

from certmon.auth import (
    AuthError,
    AuthService,
    SUPPORTED_ROLES,
    hash_session_token,
    public_user,
)
from certmon.db import Database
from tests.test_auth_api import load_app


@pytest.fixture
def auth(tmp_path):
    database = Database(tmp_path / "certmon.db")
    database.initialize()
    return AuthService(database)


def create_first_admin(auth):
    return auth.create_first_admin("admin", "correct horse", "correct horse")


def assert_session_exists(auth, token):
    assert auth.database.get_session(hash_session_token(token)) is not None


def test_supported_roles_match_permission_roles_exactly():
    assert SUPPORTED_ROLES == (
        "admin",
        "operator",
        "ca_admin",
        "security_admin",
        "viewer",
    )


@pytest.mark.parametrize(
    ("username", "password", "roles", "message"),
    [
        ("", "correct horse", ["viewer"], "Username is required"),
        ("viewer", "short", ["viewer"], "Password must be at least 8 characters"),
        ("viewer", "correct horse", [], "At least one role is required"),
        ("viewer", "correct horse", ["root"], "Unsupported role: root"),
    ],
)
def test_create_user_rejects_invalid_input_without_database_changes(
    auth, username, password, roles, message
):
    create_first_admin(auth)
    before = auth.database.list_users()

    with pytest.raises(AuthError, match=message):
        auth.create_user(username, password, roles)

    assert auth.database.list_users() == before


def test_create_user_rejects_case_insensitive_duplicate(auth):
    create_first_admin(auth)

    with pytest.raises(AuthError, match="Username already exists"):
        auth.create_user(" ADMIN ", "correct horse", ["viewer"])

    assert len(auth.database.list_users()) == 1


def test_users_are_listed_case_insensitively_and_public_values_hide_hashes(auth):
    create_first_admin(auth)
    auth.create_user("zulu", "correct horse", ["viewer"])
    auth.create_user("Alpha", "correct horse", ["operator"])

    users = auth.list_users()
    assert [user["username"] for user in users] == ["admin", "Alpha", "zulu"]
    result = public_user(users[0])
    assert result["created_at"]
    assert result["disabled"] is False
    assert "password_hash" not in result
    assert "disabled_at" not in result


def test_role_change_revokes_existing_sessions(auth):
    create_first_admin(auth)
    user = auth.create_user("operator", "correct horse", ["operator"])
    token, _expires = auth.start_session(user)
    assert_session_exists(auth, token)

    updated = auth.update_user(user["id"], roles=["viewer"])

    assert updated["roles"] == ["viewer"]
    assert auth.database.get_session(hash_session_token(token)) is None


def test_disable_and_password_reset_revoke_existing_sessions(auth):
    create_first_admin(auth)
    user = auth.create_user("viewer", "correct horse", ["viewer"])
    disable_token, _expires = auth.start_session(user)

    disabled = auth.set_user_enabled(user["id"], False)
    assert disabled["disabled_at"] is not None
    assert auth.database.get_session(hash_session_token(disable_token)) is None

    auth.set_user_enabled(user["id"], True)
    reset_token, _expires = auth.start_session(auth.database.get_user(user["id"]))
    auth.reset_user_password(user["id"], "new password")
    assert auth.database.get_session(hash_session_token(reset_token)) is None


def test_final_enabled_admin_cannot_be_disabled_or_lose_admin_role(auth):
    admin = create_first_admin(auth)

    with pytest.raises(AuthError, match="final enabled administrator"):
        auth.set_user_enabled(admin["id"], False)
    with pytest.raises(AuthError, match="final enabled administrator"):
        auth.update_user(admin["id"], roles=["viewer"])

    stored = auth.database.get_user(admin["id"])
    assert stored["disabled_at"] is None
    assert "admin" in stored["roles"]


def test_one_admin_can_be_changed_when_another_enabled_admin_exists(auth):
    first = create_first_admin(auth)
    second = auth.create_user("second-admin", "correct horse", ["admin"])

    assert auth.update_user(first["id"], roles=["viewer"])["roles"] == ["viewer"]
    auth.create_user("third-admin", "correct horse", ["admin"])
    assert auth.set_user_enabled(second["id"], False)["disabled_at"] is not None


def setup_admin_client(module):
    client = module.app.test_client()
    response = client.post(
        "/api/auth/setup-first-admin",
        json={
            "username": "admin",
            "password": "correct horse",
            "password_confirmation": "correct horse",
        },
    )
    assert response.status_code == 200
    status = client.get("/api/auth/status").get_json()
    return client, {status["csrf_header"]: status["csrf_token"]}


def login_client(module, username, password):
    client = module.app.test_client()
    assert client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).status_code == 200
    status = client.get("/api/auth/status").get_json()
    return client, {status["csrf_header"]: status["csrf_token"]}


def create_user_via_api(client, headers, username, roles):
    response = client.post(
        "/api/users",
        headers=headers,
        json={"username": username, "password": "correct horse", "roles": roles},
    )
    assert response.status_code == 201
    return response.get_json()["user"]


def test_user_management_api_lists_public_users_and_supported_roles(
    tmp_data_dir, monkeypatch
):
    module = load_app(tmp_data_dir, monkeypatch)
    client, _headers = setup_admin_client(module)

    response = client.get("/api/users")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["supported_roles"] == list(SUPPORTED_ROLES)
    assert payload["users"][0]["username"] == "admin"
    assert "password_hash" not in payload["users"][0]


def test_user_without_manage_users_is_forbidden_from_all_user_endpoints(
    tmp_data_dir, monkeypatch
):
    module = load_app(tmp_data_dir, monkeypatch)
    admin, headers = setup_admin_client(module)
    viewer = create_user_via_api(admin, headers, "viewer", ["viewer"])
    client, viewer_headers = login_client(module, "viewer", "correct horse")

    responses = [
        client.get("/api/users"),
        client.post(
            "/api/users",
            headers=viewer_headers,
            json={"username": "other", "password": "do not read", "roles": ["viewer"]},
        ),
        client.patch(
            f"/api/users/{viewer['id']}",
            headers=viewer_headers,
            json={"roles": ["admin"]},
        ),
        client.post(
            f"/api/users/{viewer['id']}/password",
            headers=viewer_headers,
            json={"password": "do not read"},
        ),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]


def test_user_api_returns_stable_validation_and_missing_user_errors(
    tmp_data_dir, monkeypatch
):
    module = load_app(tmp_data_dir, monkeypatch)
    client, headers = setup_admin_client(module)

    assert client.post(
        "/api/users",
        headers=headers,
        json={"username": "bad", "password": "short", "roles": ["viewer"]},
    ).status_code == 400
    assert client.patch(
        "/api/users/missing", headers=headers, json={"roles": ["viewer"]}
    ).status_code == 404
    assert client.patch(
        "/api/users/missing", headers=headers, json={"unexpected": True}
    ).status_code == 400
    assert client.post(
        "/api/users/missing/password",
        headers=headers,
        json={"password": "correct horse"},
    ).status_code == 404


def test_created_viewer_can_sign_in_but_cannot_start_renewal(
    tmp_data_dir, monkeypatch
):
    module = load_app(tmp_data_dir, monkeypatch)
    admin, headers = setup_admin_client(module)
    create_user_via_api(admin, headers, "viewer", ["viewer"])
    viewer, viewer_headers = login_client(module, "viewer", "correct horse")

    response = viewer.post(
        "/api/renew",
        headers=viewer_headers,
        json={
            "endpoint_host": "192.168.1.20",
            "endpoint_port": 443,
            "issuer_type": "acme",
            "identifiers": ["device.example.com"],
            "profile": "generic-rsa",
            "environment": "staging",
            "dns_provider": "manual",
        },
    )

    assert response.status_code == 403


def test_role_change_invalidates_target_session(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir, monkeypatch)
    admin, headers = setup_admin_client(module)
    operator = create_user_via_api(admin, headers, "operator", ["operator"])
    target, _target_headers = login_client(module, "operator", "correct horse")
    assert target.get("/api/data").status_code == 200

    updated = admin.patch(
        f"/api/users/{operator['id']}",
        headers=headers,
        json={"roles": ["viewer"]},
    )

    assert updated.status_code == 200
    assert target.get("/api/data").status_code == 401


def test_user_management_audit_events_contain_no_password_material(
    tmp_data_dir, monkeypatch
):
    module = load_app(tmp_data_dir, monkeypatch)
    client, headers = setup_admin_client(module)
    user = create_user_via_api(client, headers, "audited", ["viewer"])
    assert client.post(
        f"/api/users/{user['id']}/password",
        headers=headers,
        json={"password": "replacement secret"},
    ).status_code == 200

    events = client.get("/api/audit").get_json()
    relevant = [event for event in events if event["event_type"].startswith("user_")]
    serialized = str(relevant).lower()

    assert {event["event_type"] for event in relevant} >= {
        "user_created",
        "user_password_reset",
    }
    assert all(event["username"] == "admin" for event in relevant)
    assert all(event["source_ip"] for event in relevant)
    assert all(event["target"] for event in relevant)
    assert "replacement secret" not in serialized
    assert "password_hash" not in serialized
    assert "pbkdf2_sha256" not in serialized
