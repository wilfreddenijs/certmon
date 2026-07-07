import hashlib
import hmac

from certmon.auth import hash_session_token


CSRF_HEADER = "X-CertMon-CSRF"
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class CSRFError(PermissionError):
    pass


def csrf_token_for_session(session_token, secret):
    if not session_token:
        return None
    token_hash = hash_session_token(session_token)
    return hmac.new(
        secret.encode("utf-8"),
        token_hash.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def validate_csrf(request, *, session_token, secret):
    if request.method not in MUTATING_METHODS:
        return True
    expected = csrf_token_for_session(session_token, secret)
    provided = request.headers.get(CSRF_HEADER)
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        raise CSRFError("CSRF token required")
    return True
