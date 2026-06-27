from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class DNSChallengeRecord:
    fqdn: str
    value: str


@dataclass(frozen=True)
class PresentedRecord:
    fqdn: str
    value: str
    provider: str
    expires_at: datetime | None = None
    zone_id: str | None = None
    record_id: str | None = None


@dataclass(frozen=True)
class CleanupResult:
    cleaned: int
    errors: tuple[str, ...] = ()


class DNSProvider(Protocol):
    def present(
        self, records: tuple[DNSChallengeRecord, ...]
    ) -> tuple[PresentedRecord, ...]: ...

    def cleanup(self, presented: tuple[PresentedRecord, ...]) -> CleanupResult: ...
