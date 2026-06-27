import os

import pytest

from certmon.acme_service import (
    ACMEAccountService,
    ACMEOrderService,
    NativeACMEAccountClient,
    NativeACMEOrderClient,
)
from certmon.artifacts import ArtifactStore
from certmon.db import Database
from certmon.dns.cloudflare import CloudflareDNSProvider
from certmon.renewals import ACMERenewalOrchestrator, RenewalService
from certmon.vault import MemoryKeyProtector, Vault


@pytest.mark.acme_staging
def test_letsencrypt_staging_dns01_flow(tmp_path):
    required = (
        "CERTMON_ACME_STAGING_TEST",
        "CERTMON_ACME_TEST_DOMAIN",
        "CERTMON_ACME_TEST_EMAIL",
        "CERTMON_ACME_CLOUDFLARE_TOKEN",
        "CERTMON_ACME_CLOUDFLARE_ZONES",
    )
    if os.environ.get("CERTMON_ACME_STAGING_TEST") != "1" or any(
        not os.environ.get(name) for name in required[1:]
    ):
        pytest.skip("ACME staging integration environment is not configured")

    database = Database(tmp_path / "certmon.db")
    database.initialize()
    vault = Vault(tmp_path / "vault", MemoryKeyProtector())
    vault.initialize()
    artifacts = ArtifactStore(tmp_path / "certificates", vault)
    CloudflareDNSProvider.configure(
        database,
        vault,
        token=os.environ["CERTMON_ACME_CLOUDFLARE_TOKEN"],
        zones=os.environ["CERTMON_ACME_CLOUDFLARE_ZONES"].split(","),
    )
    provider = CloudflareDNSProvider.load(database, vault)
    renewals = RenewalService(database)
    accounts = ACMEAccountService(database, vault, NativeACMEAccountClient)
    orders = ACMEOrderService(database, accounts, NativeACMEOrderClient)
    orchestrator = ACMERenewalOrchestrator(
        database,
        renewals,
        accounts,
        orders,
        artifacts,
        {"cloudflare": provider},
    )
    job = renewals.create_job(
        endpoint_host=os.environ["CERTMON_ACME_TEST_DOMAIN"],
        endpoint_port=443,
        issuer_type="acme",
        identifiers=[os.environ["CERTMON_ACME_TEST_DOMAIN"]],
        profile="generic-rsa",
        environment="staging",
        dns_provider="cloudflare",
    )
    assert job["environment"] == "staging"
    try:
        result = orchestrator.start_acme(
            job["id"],
            email=os.environ["CERTMON_ACME_TEST_EMAIL"],
            terms_of_service_agreed=True,
        )
        assert result["state"] == "issued"
    finally:
        presented = orchestrator._load_presented(job["id"], required=False)
        if presented:
            provider.cleanup(presented)
