import pytest

from certmon.credentials import ordered_credentials


@pytest.mark.parametrize('individual,shared,expected', [
    ({'password': 'device'}, {'password': 'shared'}, ['device', 'shared', 'extron']),
    ({'password': ''}, {'password': 'shared'}, ['shared', 'extron']),
    (None, None, ['extron']),
    ({'password': 'extron'}, {'password': 'extron'}, ['extron']),
    ({'password': 'same', 'username': 'operator'}, {'password': 'same'}, ['same', 'same', 'extron']),
])
def test_ordered_credentials_skip_empty_and_duplicate_pairs(individual, shared, expected):
    candidates = ordered_credentials(individual, shared)
    assert [c['password'] for c in candidates] == expected
    assert candidates[-1] == {'username': 'admin', 'password': 'extron'}
