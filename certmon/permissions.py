from enum import Enum


class AuthorizationError(PermissionError):
    pass


class Permission(str, Enum):
    ISSUE_CERTIFICATE = "issue_certificate"
    DEPLOY_CERTIFICATE = "deploy_certificate"
    DOWNLOAD_PUBLIC_CERTIFICATE = "download_public_certificate"
    DOWNLOAD_PRIVATE_KEY = "download_private_key"
    MANAGE_DNS_CREDENTIALS = "manage_dns_credentials"
    MANAGE_LOCAL_CA = "manage_local_ca"


LOCAL_PERMISSIONS = frozenset(Permission)


def authorize(permission, *, granted=None):
    permission = Permission(permission)
    effective = LOCAL_PERMISSIONS if granted is None else frozenset(granted)
    if permission not in effective:
        raise AuthorizationError(f"Permission denied: {permission.value}")
    return True
