import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone


SESSION_COOKIE = "certmon_session"
DEFAULT_SESSION_HOURS = 12
ADMIN_ROLES = ("admin", "operator", "ca_admin", "security_admin", "viewer")


class AuthError(PermissionError):
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
    }


class AuthService:
    def __init__(self, database, *, session_hours=DEFAULT_SESSION_HOURS):
        self.database = database
        self.session_hours = session_hours

    def first_admin_required(self):
        return not self.database.users_exist()

    def create_first_admin(self, username, password):
        username = (username or "").strip()
        if not username:
            raise AuthError("Username is required")
        if not password or len(password) < 8:
            raise AuthError("Password must be at least 8 characters")
        if self.database.users_exist():
            raise AuthError("First admin already exists")
        user_id = str(uuid.uuid4())
        self.database.create_user(
            user_id=user_id,
            username=username,
            password_hash=hash_password(password),
            roles=ADMIN_ROLES,
        )
        return self.database.get_user(user_id)

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
