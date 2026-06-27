from datetime import datetime, timedelta, timezone

import pytest

from certmon.dns.base import DNSChallengeRecord
from certmon.dns.manual import ManualChallengeExpired, ManualDNSProvider


def test_manual_provider_deduplicates_records_and_checks_authoritative_visibility():
    visible = {"_acme-challenge.example.com": {"token-value"}}
    provider = ManualDNSProvider(
        resolver=lambda fqdn: visible.get(fqdn, set()), ttl_seconds=600
    )

    presented = provider.present(
        (
            DNSChallengeRecord("_acme-challenge.example.com", "token-value"),
            DNSChallengeRecord("_acme-challenge.example.com", "token-value"),
        )
    )
    status = provider.check_visibility(presented)

    assert len(presented) == 1
    assert status[0].visible is True
    assert status[0].fqdn == "_acme-challenge.example.com"


def test_manual_provider_reports_missing_txt_value():
    provider = ManualDNSProvider(resolver=lambda fqdn: {"different-value"})
    presented = provider.present(
        (DNSChallengeRecord("_acme-challenge.example.com", "expected"),)
    )

    assert provider.check_visibility(presented)[0].visible is False


def test_manual_challenge_cannot_continue_after_expiry():
    now = datetime(2026, 6, 14, 10, 0, tzinfo=timezone.utc)
    provider = ManualDNSProvider(
        resolver=lambda fqdn: {"value"},
        ttl_seconds=60,
        clock=lambda: now,
    )
    presented = provider.present(
        (DNSChallengeRecord("_acme-challenge.example.com", "value"),)
    )
    provider.clock = lambda: now + timedelta(seconds=61)

    with pytest.raises(ManualChallengeExpired):
        provider.check_visibility(presented)


def test_manual_cleanup_is_idempotent():
    provider = ManualDNSProvider(resolver=lambda fqdn: set())
    presented = provider.present(
        (DNSChallengeRecord("_acme-challenge.example.com", "value"),)
    )

    assert provider.cleanup(presented).cleaned == 0
    assert provider.cleanup(presented).cleaned == 0
