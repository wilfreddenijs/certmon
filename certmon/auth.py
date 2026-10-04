import hashlib
import hmac
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from certmon.permissions import ROLE_PERMISSIONS


SESSION_COOKIE = "certmon_session"
DEFAULT_SESSION_HOURS = 12
SUPPORTED_ROLES = ("admin", "operator", "ca_admin", "security_admin", "viewer")
if set(SUPPORTED_ROLES) != set(ROLE_PERMISSIONS):
    raise RuntimeError("SUPPORTED_ROLES must match ROLE_PERMISSIONS")


class AuthError(PermissionError):
    pass


class AuthNotFoundError(AuthError):
    pass


def _utc_now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _parse_iso(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def hash_password(password, *, iterations=260000):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    expected = bytes.fromhex(digest_hex)
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        int(iterations),
    )
    return hmac.compare_digest(actual, expected)


def hash_session_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def public_user(user):
    if not user:
        return None
    return {
        "id": user["id"],
        "username": user["username"],
        "roles": list(user.get("roles") or []),
        "created_at": user["created_at"],
        "disabled": bool(user.get("disabled_at")),
    }


class AuthService:
    def __init__(self, database, *, session_hours=DEFAULT_SESSION_HOURS):
        self.database = database
        self.session_hours = session_hours

    def first_admin_required(self):
        return not self.database.users_exist()

    def create_first_admin(self, username, password, password_confirmation):
        username = self._validated_username(username)
        self._validate_password(password)
        if password_confirmation is None or password != password_confirmation:
            raise AuthError("Password confirmation does not match")
        if self.database.users_exist():
            raise AuthError("First admin already exists")
        user_id = str(uuid.uuid4())
        try:
            self.database.create_user(
                user_id=user_id,
                username=username,
                password_hash=hash_password(password),
                roles=SUPPORTED_ROLES,
            )
        except sqlite3.IntegrityError as exc:
            raise AuthError("Username already exists") from exc
        return self.database.get_user(user_id)

    def list_users(self):
        return self.database.list_users()

    def create_user(self, username, password, roles):
        username = self._validated_username(username)
        self._validate_password(password)
        roles = self._validated_roles(roles)
        user_id = str(uuid.uuid4())
        try:
            self.database.create_user(
                user_id=user_id,
                username=username,
                password_hash=hash_password(password),
                roles=roles,
            )
        except sqlite3.IntegrityError as exc:
            raise AuthError("Username already exists") from exc
        return self.database.get_user(user_id)

    def update_user(self, user_id, *, username=None, roles=None):
        user = self._required_user(user_id)
        new_username = (
            user["username"] if username is None else self._validated_username(username)
        )
        new_roles = user["roles"] if roles is None else self._validated_roles(roles)
        roles_changed = list(new_roles) != list(user["roles"])
        try:
            updated = self.database.update_user_identity_and_roles(
                user_id,
                username=new_username,
                roles=new_roles,
                revoke_sessions=roles_changed,
                protect_final_admin=True,
            )
        except sqlite3.IntegrityError as exc:
            raise AuthError("Username already exists") from exc
        except ValueError as exc:
            raise AuthError(str(exc)) from exc
        if not updated:
            raise AuthNotFoundError("User not found")
        return self.database.get_user(user_id)

    def set_user_enabled(self, user_id, enabled):
        self._required_user(user_id)
        try:
            updated = self.database.set_user_disabled(
                user_id,
                not bool(enabled),
                revoke_sessions=not bool(enabled),
                protect_final_admin=True,
            )
        except ValueError as exc:
            raise AuthError(str(exc)) from exc
        if not updated:
            raise AuthNotFoundError("User not found")
        return self.database.get_user(user_id)

    def reset_user_password(self, user_id, password):
        self._required_user(user_id)
        self._validate_password(password)
        if not self.database.set_user_password_hash(
            user_id, hash_password(password), revoke_sessions=True
        ):
            raise AuthNotFoundError("User not found")
        return self.database.get_user(user_id)

    def _required_user(self, user_id):
        user = self.database.get_user(user_id)
        if user is None:
            raise AuthNotFoundError("User not found")
        return user

    @staticmethod
    def _validated_username(username):
        username = (username or "").strip()
        if not username:
            raise AuthError("Username is required")
        return username

    @staticmethod
    def _validate_password(password):
        if not password or len(password) < 8:
            raise AuthError("Password must be at least 8 characters")

    @staticmethod
    def _validated_roles(roles):
        if not isinstance(roles, (list, tuple, set)) or not roles:
            raise AuthError("At least one role is required")
        normalized = []
        for role in roles:
            if role not in SUPPORTED_ROLES:
                raise AuthError(f"Unsupported role: {role}")
            if role not in normalized:
                normalized.append(role)
        return normalized

    def authenticate(self, username, password):
        user = self.database.get_user_by_username((username or "").strip())
        if not user or user.get("disabled_at"):
            return None
        if not verify_password(password or "", user["password_hash"]):
            return None
        return user

    def start_session(self, user):
        token = secrets.token_urlsafe(32)
        expires_at = _utc_now() + timedelta(hours=self.session_hours)
        self.database.create_session(
            token_hash=hash_session_token(token),
            user_id=user["id"],
            expires_at=_iso(expires_at),
        )
        return token, expires_at

    def user_for_token(self, token):
        if not token:
            return None
        token_hash = hash_session_token(token)
        session = self.database.get_session(token_hash)
        if not session:
            return None
        if _parse_iso(session["expires_at"]) <= _utc_now():
            self.database.delete_session(token_hash)
            return None
        user = self.database.get_user(session["user_id"])
        if not user or user.get("disabled_at"):
            self.database.delete_session(token_hash)
            return None
        self.database.touch_session(token_hash)
        return user

    def end_session(self, token):
        if token:
            self.database.delete_session(hash_session_token(token))
