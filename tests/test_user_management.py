import pytest

from certmon.auth import (
    AuthError,
    AuthService,
    SUPPORTED_ROLES,
    hash_session_token,
    public_user,
)
from certmon.db import Database


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
