from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from certmon.dns.base import CleanupResult, DNSChallengeRecord, PresentedRecord


class ManualChallengeExpired(RuntimeError):
    pass


@dataclass(frozen=True)
class VisibilityResult:
    fqdn: str
    value: str
    visible: bool


class ManualDNSProvider:
    def __init__(
        self,
        resolver=None,
        *,
        ttl_seconds=900,
        clock=lambda: datetime.now(timezone.utc),
    ):
        self.resolver = resolver or authoritative_txt_values
        self.ttl_seconds = ttl_seconds
        self.clock = clock

    def present(self, records):
        expires_at = self.clock() + timedelta(seconds=self.ttl_seconds)
        return tuple(
            PresentedRecord(
                fqdn=record.fqdn.rstrip("."),
                value=record.value,
                provider="manual",
                expires_at=expires_at,
            )
            for record in _deduplicate(records)
        )

    def check_visibility(self, presented):
        if any(
            record.expires_at is not None and self.clock() >= record.expires_at
            for record in presented
        ):
            raise ManualChallengeExpired("Manual DNS challenge has expired")
        return tuple(
            VisibilityResult(
                fqdn=record.fqdn,
                value=record.value,
                visible=record.value in self.resolver(record.fqdn),
            )
            for record in presented
        )

    def cleanup(self, presented):
        return CleanupResult(cleaned=0)


def authoritative_txt_values(fqdn):
    import dns.resolver

    zone = dns.resolver.zone_for_name(fqdn)
    nameservers = dns.resolver.resolve(zone, "NS")
    addresses = []
    for nameserver in nameservers:
        host = str(nameserver.target).rstrip(".")
        for record_type in ("A", "AAAA"):
            try:
                addresses.extend(
                    answer.address
                    for answer in dns.resolver.resolve(host, record_type)
                )
            except dns.exception.DNSException:
                continue
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = addresses
    answers = resolver.resolve(fqdn, "TXT", search=False)
    return {
        b"".join(answer.strings).decode("utf-8")
        for answer in answers
    }


def _deduplicate(records):
    seen = set()
    result = []
    for record in records:
        key = (record.fqdn.rstrip("."), record.value)
        if key in seen:
            continue
        seen.add(key)
        result.append(DNSChallengeRecord(*key))
    return result
