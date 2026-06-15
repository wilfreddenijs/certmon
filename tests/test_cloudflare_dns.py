import json

import pytest

from certmon.db import Database
from certmon.dns.base import DNSChallengeRecord
from certmon.dns.cloudflare import CloudflareDNSProvider, CloudflareError
from certmon.vault import MemoryKeyProtector, Vault


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"success": True, "result": {}}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = []
        self.responses = []
        self.headers = {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def make_provider(tmp_path, session, zones=("example.com",)):
    database = Database(tmp_path / "certmon.db")
    database.initialize()
    vault = Vault(tmp_path / "vault", MemoryKeyProtector())
    vault.initialize()
    CloudflareDNSProvider.configure(
        database, vault, token="super-secret-token", zones=zones
    )
    return database, vault, CloudflareDNSProvider.load(database, vault, session=session)


def test_configure_encrypts_token_and_verify_uses_bearer_header(tmp_path):
    session = FakeSession()
    session.responses = [FakeResponse(payload={"success": True, "result": {"status": "active"}})]
    database, vault, provider = make_provider(tmp_path, session)

    provider.verify_token()

    blob = database.get_secret("dns-cloudflare-token")
    assert vault.decrypt(blob, purpose=blob.purpose) == b"super-secret-token"
    assert database.get_setting("dns-cloudflare")["zones"] == ["example.com"]
    assert session.calls[0][2]["headers"]["Authorization"] == "Bearer super-secret-token"


def test_longest_suffix_zone_selection_pagination_and_duplicate_txt(tmp_path):
    session = FakeSession()
    session.responses = [
        FakeResponse(
            payload={
                "success": True,
                "result": [],
                "result_info": {"page": 1, "total_pages": 2},
            }
        ),
        FakeResponse(
            payload={
                "success": True,
                "result": [
                    {"id": "zone-parent", "name": "example.com"},
                    {"id": "zone-child", "name": "lab.example.com"},
                ],
                "result_info": {"page": 2, "total_pages": 2},
            }
        ),
        FakeResponse(payload={"success": True, "result": {"id": "record-1"}}),
    ]
    _, _, provider = make_provider(
        tmp_path, session, zones=("example.com", "lab.example.com")
    )
    records = (
        DNSChallengeRecord("_acme-challenge.device.lab.example.com", "value"),
        DNSChallengeRecord("_acme-challenge.device.lab.example.com", "value"),
    )

    presented = provider.present(records)

    assert len(presented) == 1
    assert presented[0].zone_id == "zone-child"
    assert presented[0].record_id == "record-1"
    assert session.calls[-1][2]["json"]["type"] == "TXT"


def test_restricted_zone_access_is_rejected(tmp_path):
    session = FakeSession()
    session.responses = [
        FakeResponse(
            payload={
                "success": True,
                "result": [{"id": "other", "name": "other.com"}],
                "result_info": {"page": 1, "total_pages": 1},
            }
        )
    ]
    _, _, provider = make_provider(tmp_path, session, zones=("example.com",))

    with pytest.raises(CloudflareError, match="configured zone"):
        provider.present((DNSChallengeRecord("_acme-challenge.other.com", "value"),))


def test_cleanup_treats_404_as_success_and_is_idempotent(tmp_path):
    session = FakeSession()
    session.responses = [
        FakeResponse(
            payload={
                "success": True,
                "result": [{"id": "zone", "name": "example.com"}],
                "result_info": {"page": 1, "total_pages": 1},
            }
        ),
        FakeResponse(payload={"success": True, "result": {"id": "record"}}),
        FakeResponse(status_code=404, payload={"success": False}),
        FakeResponse(status_code=404, payload={"success": False}),
    ]
    _, _, provider = make_provider(tmp_path, session)
    presented = provider.present(
        (DNSChallengeRecord("_acme-challenge.example.com", "value"),)
    )

    assert provider.cleanup(presented).cleaned == 1
    assert provider.cleanup(presented).cleaned == 1


def test_partial_present_failure_cleans_records_already_created(tmp_path):
    session = FakeSession()
    session.responses = [
        FakeResponse(
            payload={
                "success": True,
                "result": [{"id": "zone", "name": "example.com"}],
                "result_info": {"page": 1, "total_pages": 1},
            }
        ),
        FakeResponse(payload={"success": True, "result": {"id": "record-1"}}),
        FakeResponse(
            status_code=500,
            payload={"success": False, "errors": [{"message": "temporary failure"}]},
        ),
        FakeResponse(payload={"success": True, "result": {"id": "record-1"}}),
    ]
    _, _, provider = make_provider(tmp_path, session)

    with pytest.raises(CloudflareError):
        provider.present(
            (
                DNSChallengeRecord("_acme-challenge.one.example.com", "one"),
                DNSChallengeRecord("_acme-challenge.two.example.com", "two"),
            )
        )

    assert session.calls[-1][0] == "DELETE"
    assert session.calls[-1][1].endswith("/zones/zone/dns_records/record-1")


def test_errors_redact_token_and_request_headers(tmp_path):
    session = FakeSession()
    session.responses = [
        FakeResponse(status_code=403, payload={"success": False, "errors": [{"message": "denied"}]})
    ]
    _, _, provider = make_provider(tmp_path, session)

    with pytest.raises(CloudflareError) as error:
        provider.verify_token()

    assert "super-secret-token" not in str(error.value)
    assert "Authorization" not in str(error.value)
