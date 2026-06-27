from datetime import datetime, timedelta, timezone

import pytest

from certmon.acme_service import (
    ACMEOrderError,
    ACMEOrderService,
    parse_retry_after,
    translate_acme_problem,
    _acme_client_deadline,
    _status_name,
)
from certmon.db import Database
from certmon.renewals import RenewalService


class FakeAccounts:
    def load(self, environment):
        return (
            {
                "directory_url": f"https://acme.test/{environment}",
                "account_url": f"https://acme.test/{environment}/account/1",
            },
            b"account-key",
        )


class FakeOrderClient:
    def __init__(self):
        self.created = []
        self.poll_results = {}
        self.finalized = []
        self.orders = {}

    def create_order(self, *, identifiers, csr_pem):
        self.created.append((tuple(identifiers), csr_pem))
        return {
            "order_url": "https://acme.test/order/1",
            "status": "pending",
            "authorizations": [
                {
                    "url": f"https://acme.test/authz/{identifier}",
                    "identifier": identifier,
                    "challenges": [
                        {
                            "type": "dns-01",
                            "url": f"https://acme.test/challenge/{identifier}",
                            "fqdn": f"_acme-challenge.{identifier.lstrip('*.')}",
                            "value": f"txt-{identifier}",
                        }
                    ],
                }
                for identifier in identifiers
            ],
        }

    def poll_authorization(self, authorization_url):
        return self.poll_results[authorization_url].pop(0)

    def finalize_order(self, order_url, csr_pem):
        self.finalized.append((order_url, csr_pem))
        return {
            "status": "valid",
            "certificate_pem": b"leaf",
            "chain_pem": b"chain",
        }

    def get_order(self, order_url):
        return self.orders[order_url]


def make_service(tmp_path):
    database = Database(tmp_path / "certmon.db")
    database.initialize()
    renewals = RenewalService(database)
    client = FakeOrderClient()
    service = ACMEOrderService(database, FakeAccounts(), lambda *args: client)
    return database, renewals, client, service


def create_job(renewals):
    return renewals.create_job(
        endpoint_host="device.example.com",
        endpoint_port=443,
        issuer_type="acme",
        identifiers=["Device.Example.COM", "*.Example.com"],
        profile="generic-rsa",
        environment="staging",
        dns_provider="manual",
    )


def test_order_creation_extracts_dns_challenges_and_persists_reference(tmp_path):
    database, renewals, client, service = make_service(tmp_path)
    job = create_job(renewals)

    result = service.create_order(job["id"], b"csr")

    assert client.created == [(('device.example.com', '*.example.com'), b"csr")]
    assert result["order_url"] == "https://acme.test/order/1"
    assert [record["fqdn"] for record in result["dns_challenges"]] == [
        "_acme-challenge.device.example.com",
        "_acme-challenge.example.com",
    ]
    persisted = database.get_setting(f"acme-order:{job['id']}")
    assert persisted["order_url"] == result["order_url"]
    assert persisted["csr_pem"] == "csr"


def test_authorization_polling_is_bounded_and_honors_retry_after(tmp_path):
    _, renewals, client, service = make_service(tmp_path)
    job = create_job(renewals)
    order = service.create_order(job["id"], b"csr")
    for challenge in order["dns_challenges"]:
        authz_url = challenge["authorization_url"]
        client.poll_results[authz_url] = [
            {"status": "pending", "retry_after": "2"},
            {"status": "valid"},
        ]

    result = service.poll_authorizations(
        job["id"], max_attempts=3, sleep=lambda seconds: None
    )

    assert result["status"] == "ready"
    assert result["attempts"] == 4


def test_finalize_returns_downloaded_certificate_chain(tmp_path):
    _, renewals, client, service = make_service(tmp_path)
    job = create_job(renewals)
    service.create_order(job["id"], b"csr")

    result = service.finalize(job["id"])

    assert result == {
        "status": "valid",
        "certificate_pem": b"leaf",
        "chain_pem": b"chain",
    }
    assert client.finalized == [("https://acme.test/order/1", b"csr")]


def test_native_acme_deadline_is_timezone_naive_for_client_compatibility():
    deadline = _acme_client_deadline()

    assert deadline.tzinfo is None
    assert deadline > datetime.now()


def test_reconcile_uses_persisted_order_url_after_restart(tmp_path):
    database, renewals, client, service = make_service(tmp_path)
    job = create_job(renewals)
    service.create_order(job["id"], b"csr")
    client.orders["https://acme.test/order/1"] = {
        "status": "invalid",
        "problem": {"type": "urn:ietf:params:acme:error:rateLimited", "detail": "slow down"},
        "retry_after": "120",
    }

    restarted = ACMEOrderService(database, FakeAccounts(), lambda *args: client)
    state, updates = restarted.reconcile(job)

    assert state == "failed"
    assert updates["error_code"] == "acme_rate_limited"
    assert "slow down" in updates["error_message"]


@pytest.mark.parametrize(
    ("problem_type", "expected"),
    [
        ("urn:ietf:params:acme:error:rateLimited", "acme_rate_limited"),
        ("urn:ietf:params:acme:error:rejectedIdentifier", "acme_rejected_identifier"),
        ("urn:ietf:params:acme:error:unauthorized", "acme_validation_failed"),
    ],
)
def test_problem_documents_translate_to_stable_codes(problem_type, expected):
    assert translate_acme_problem({"type": problem_type}) == expected


def test_retry_after_parses_seconds_and_http_date():
    now = datetime(2026, 6, 14, 10, 0, tzinfo=timezone.utc)

    assert parse_retry_after("30", now=now) == now + timedelta(seconds=30)
    assert parse_retry_after("Sun, 14 Jun 2026 10:02:00 GMT", now=now) == (
        now + timedelta(minutes=2)
    )


def test_native_acme_status_is_normalized_to_protocol_value():
    from acme import messages

    assert _status_name(messages.STATUS_PENDING) == "pending"


def test_polling_failure_raises_stable_error(tmp_path):
    _, renewals, client, service = make_service(tmp_path)
    job = create_job(renewals)
    order = service.create_order(job["id"], b"csr")
    first = order["dns_challenges"][0]["authorization_url"]
    client.poll_results[first] = [
        {
            "status": "invalid",
            "problem": {
                "type": "urn:ietf:params:acme:error:unauthorized",
                "detail": "TXT record missing",
            },
        }
    ]

    with pytest.raises(ACMEOrderError) as error:
        service.poll_authorizations(job["id"], max_attempts=1, sleep=lambda _: None)

    assert error.value.code == "acme_validation_failed"
