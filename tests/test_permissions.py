import pytest

from certmon.permissions import AuthorizationError, Permission, authorize


def test_local_principal_has_phase_one_permissions():
    assert authorize(Permission.ISSUE_CERTIFICATE) is True


def test_denied_permission_raises_before_action():
    with pytest.raises(AuthorizationError):
        authorize(Permission.MANAGE_DNS_CREDENTIALS, granted=frozenset())
