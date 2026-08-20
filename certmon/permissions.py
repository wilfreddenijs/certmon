from enum import Enum
from contextvars import ContextVar


class AuthorizationError(PermissionError):
    pass


class Permission(str, Enum):
    ISSUE_CERTIFICATE = "issue_certificate"
    DEPLOY_CERTIFICATE = "deploy_certificate"
    DOWNLOAD_PUBLIC_CERTIFICATE = "download_public_certificate"
    DOWNLOAD_PRIVATE_KEY = "download_private_key"
    MANAGE_DNS_CREDENTIALS = "manage_dns_credentials"
    MANAGE_LOCAL_CA = "manage_local_ca"
    MANAGE_SERVER_BACKUP = "manage_server_backup"
    MANAGE_USERS = "manage_users"
    VIEW_AUDIT = "view_audit"


LOCAL_PERMISSIONS = frozenset(Permission)
_current_permissions = ContextVar("certmon_current_permissions", default=None)


ROLE_PERMISSIONS = {
    "viewer": frozenset(
        {
            Permission.DOWNLOAD_PUBLIC_CERTIFICATE,
        }
    ),
    "operator": frozenset(
        {
            Permission.ISSUE_CERTIFICATE,
            Permission.DEPLOY_CERTIFICATE,
            Permission.DOWNLOAD_PUBLIC_CERTIFICATE,
        }
    ),
    "ca_admin": frozenset(
        {
            Permission.ISSUE_CERTIFICATE,
            Permission.DOWNLOAD_PUBLIC_CERTIFICATE,
            Permission.MANAGE_LOCAL_CA,
        }
    ),
    "security_admin": frozenset(
        {
            Permission.DOWNLOAD_PUBLIC_CERTIFICATE,
            Permission.DOWNLOAD_PRIVATE_KEY,
            Permission.MANAGE_DNS_CREDENTIALS,
            Permission.MANAGE_SERVER_BACKUP,
            Permission.VIEW_AUDIT,
        }
    ),
    "admin": LOCAL_PERMISSIONS,
}


def permissions_for_roles(roles):
    permissions = set()
    for role in roles or []:
        permissions.update(ROLE_PERMISSIONS.get(role, frozenset()))
    return frozenset(permissions)


def set_current_permissions(granted):
    return _current_permissions.set(None if granted is None else frozenset(granted))


def reset_current_permissions(token):
    _current_permissions.reset(token)


def authorize(permission, *, granted=None):
    permission = Permission(permission)
    if granted is None:
        current = _current_permissions.get()
        effective = LOCAL_PERMISSIONS if current is None else frozenset(current)
    else:
        effective = frozenset(granted)
    if permission not in effective:
        raise AuthorizationError(f"Permission denied: {permission.value}")
    return True
