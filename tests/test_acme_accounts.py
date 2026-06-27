import pytest

from certmon.acme_service import ACMEAccountKeyLost, ACMEAccountService
from certmon.db import Database
from certmon.vault import MemoryKeyProtector, Vault


class FakeAccountClient:
    def __init__(self, directory_url, account_key):
        self.directory_url = directory_url
        self.account_key = account_key
        self.calls = []

    def register(self, *, email, terms_of_service_agreed):
        self.calls.append((email, terms_of_service_agreed))
        return {
            "account_url": f"{self.directory_url}/account/1",
            "terms_of_service_url": f"{self.directory_url}/tos",
        }


class FakeFactory:
    def __init__(self):
        self.clients = []

    def __call__(self, directory_url, account_key):
        client = FakeAccountClient(directory_url, account_key)
        self.clients.append(client)
        return client


def make_service(tmp_path):
    database = Database(tmp_path / "certmon.db")
    database.initialize()
    vault = Vault(tmp_path / "vault", MemoryKeyProtector())
    vault.initialize()
    factory = FakeFactory()
    return database, vault, factory, ACMEAccountService(database, vault, factory)


def test_registration_requires_email_and_explicit_tos_acceptance(tmp_path):
    _, _, _, service = make_service(tmp_path)

    with pytest.raises(ValueError, match="email"):
        service.register("staging", email="", terms_of_service_agreed=True)
    with pytest.raises(ValueError, match="Terms of Service"):
        service.register(
            "staging", email="admin@example.com", terms_of_service_agreed=False
        )


def test_staging_and_production_use_separate_accounts_and_keys(tmp_path):
    database, vault, factory, service = make_service(tmp_path)

    staging = service.register(
        "staging", email="admin@example.com", terms_of_service_agreed=True
    )
    production = service.register(
        "production", email="admin@example.com", terms_of_service_agreed=True
    )

    assert staging["environment"] == "staging"
    assert production["environment"] == "production"
    assert staging["account_url"] != production["account_url"]
    assert staging["terms_of_service_url"].endswith("/tos")
    assert production["terms_of_service_agreed"] is True
    assert factory.clients[0].account_key != factory.clients[1].account_key
    assert database.get_setting("acme-account:staging")["email"] == "admin@example.com"
    staging_blob = database.get_secret("acme-account-key:staging")
    production_blob = database.get_secret("acme-account-key:production")
    assert vault.decrypt(staging_blob, purpose=staging_blob.purpose) != vault.decrypt(
        production_blob, purpose=production_blob.purpose
    )


def test_lost_account_key_requires_explicit_replacement(tmp_path):
    database, _, factory, service = make_service(tmp_path)
    original = service.register(
        "production", email="admin@example.com", terms_of_service_agreed=True
    )
    database.delete_secret("acme-account-key:production")

    with pytest.raises(ACMEAccountKeyLost):
        service.register(
            "production", email="admin@example.com", terms_of_service_agreed=True
        )

    replacement = service.register(
        "production",
        email="admin@example.com",
        terms_of_service_agreed=True,
        replace_lost_key=True,
    )

    assert replacement["replaced_account_url"] == original["account_url"]
    assert len(factory.clients) == 2
