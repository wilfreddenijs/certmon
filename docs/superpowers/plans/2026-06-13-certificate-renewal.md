# Certificate Renewal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace CertMon's generated renewal commands with secure Local CA, External CA/import, and native Let's Encrypt DNS-01 issuance workflows, with optional server-side Extron deployment.

**Architecture:** Keep `app.py` as the Flask composition layer and move new behavior into focused `certmon/` modules. SQLite provides transactional metadata; an envelope-encrypted vault protects all private material; renewal jobs orchestrate Local CA, External CA, and ACME services; deployment receives certificate IDs and decrypts keys only on the server.

**Tech Stack:** Python 3.11+, Flask 3, SQLite, cryptography, acme/josepy, dnspython, requests, pytest, PyInstaller, Windows DPAPI through `ctypes`.

---

## Delivery Slices

1. **Secure foundation:** Tasks 1-4 produce tested SQLite persistence, migration, encrypted storage, recovery, and certificate profiles.
2. **Offline certificate workflows:** Tasks 5-7 produce renewal jobs, Local CA integration, External CA CSR/import, and artifact storage without internet access.
3. **ACME DNS-01:** Tasks 8-10 produce ACME accounts, manual DNS, Cloudflare automation, staging issuance, cleanup, and production gating.
4. **Application integration:** Tasks 11-14 produce APIs, UI, server-side deployment, backup/restore, packaging, and end-to-end verification.

## File Map

- `app.py`: existing routes and Flask wiring; delegates new work to services.
- `certmon/config.py`: resolve configurable server data paths.
- `certmon/db.py`: SQLite connection, schema, transactions, and JSON migration.
- `certmon/models.py`: renewal states, typed records, and state-transition rules.
- `certmon/permissions.py`: Phase 1 permission names and implicit local authorization.
- `certmon/vault.py`: envelope encryption, DPAPI wrapping, recovery package, rotation.
- `certmon/artifacts.py`: atomic encrypted artifact storage and controlled export.
- `certmon/profiles.py`: Generic modern, Generic RSA, and Extron certificate profiles.
- `certmon/certificates.py`: key/CSR creation, certificate parsing, matching, and chain validation.
- `certmon/renewals.py`: job orchestration, cancellation, recovery, and production gating.
- `certmon/external_ca.py`: CSR and existing-certificate import workflows.
- `certmon/acme_service.py`: ACME account and order lifecycle.
- `certmon/dns/base.py`: DNS provider protocol and challenge record model.
- `certmon/dns/manual.py`: authoritative DNS visibility checks.
- `certmon/dns/cloudflare.py`: Cloudflare zone selection and TXT lifecycle.
- `certmon/deployment.py`: server-side deployment by certificate/device ID.
- `certmon/backup.py`: consistent SQLite/artifact backup and restore verification.
- `templates/index.html`: renewal wizard and resumable job UI.
- `tests/`: focused unit, API, migration, security, and integration tests.

### Task 1: Add Test Harness and Data-Directory Configuration

**Files:**
- Create: `certmon/__init__.py`
- Create: `certmon/config.py`
- Create: `tests/conftest.py`
- Create: `tests/test_config.py`
- Modify: `requirements.txt`
- Modify: `app.py:17-37`

- [ ] **Step 1: Add the failing configuration tests**

```python
# tests/test_config.py
from pathlib import Path

from certmon.config import resolve_data_dir


def test_explicit_data_dir_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("CERTMON_DATA_DIR", str(tmp_path / "server-data"))
    assert resolve_data_dir(frozen=False, executable=Path("ignored"), source_dir=Path("ignored")) == tmp_path / "server-data"


def test_development_defaults_to_source_data_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("CERTMON_DATA_DIR", raising=False)
    assert resolve_data_dir(frozen=False, executable=Path("ignored"), source_dir=tmp_path) == tmp_path / "data"
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run: `pytest tests/test_config.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'certmon'`.

- [ ] **Step 3: Implement deterministic data-directory resolution**

```python
# certmon/config.py
import os
from pathlib import Path


def resolve_data_dir(*, frozen: bool, executable: Path, source_dir: Path) -> Path:
    configured = os.environ.get("CERTMON_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if frozen:
        program_data = Path(os.environ.get("PROGRAMDATA", executable.parent))
        return program_data / "CertMon"
    return source_dir / "data"
```

Update `app.py` so `data_dir()` delegates to `resolve_data_dir(...)` and creates the directory before first use. Do not move CA files yet; Task 4 performs the migration after encrypted storage exists.

- [ ] **Step 4: Add pytest dependencies and shared fixtures**

Add to `requirements.txt`:

```text
pytest>=8.2.0
pytest-mock>=3.14.0
```

Create `tests/conftest.py` with a `tmp_data_dir` fixture that sets `CERTMON_DATA_DIR` to a temporary directory.

- [ ] **Step 5: Verify and commit**

Run: `pytest tests/test_config.py -v`

Expected: `2 passed`.

```powershell
git add certmon requirements.txt app.py tests
git commit -m "test: add configurable data directory harness"
```

### Task 2: Introduce Transactional SQLite Persistence and JSON Migration

**Files:**
- Create: `certmon/db.py`
- Create: `tests/test_db.py`
- Create: `tests/test_json_migration.py`
- Modify: `app.py:42-56`

- [ ] **Step 1: Write failing schema and transaction tests**

```python
# tests/test_db.py
import sqlite3

from certmon.db import Database


def test_database_enables_wal_foreign_keys_and_schema(tmp_path):
    db = Database(tmp_path / "certmon.db")
    db.initialize()
    with db.connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"schema_version", "settings", "devices", "renewal_jobs", "certificates", "secrets", "events"} <= tables


def test_transaction_rolls_back_all_changes(tmp_path):
    db = Database(tmp_path / "certmon.db")
    db.initialize()
    try:
        with db.transaction() as conn:
            conn.execute("INSERT INTO settings(key, value) VALUES (?, ?)", ("x", "1"))
            raise RuntimeError("stop")
    except RuntimeError:
        pass
    with db.connect() as conn:
        assert conn.execute("SELECT value FROM settings WHERE key='x'").fetchone() is None
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/test_db.py -v`

Expected: import fails because `certmon.db` does not exist.

- [ ] **Step 3: Implement `Database`**

Implement connections with `timeout=5`, `row_factory=sqlite3.Row`, `PRAGMA foreign_keys=ON`, WAL initialization, and `BEGIN IMMEDIATE` transactions. Schema columns must include:

```sql
CREATE TABLE renewal_jobs (
  id TEXT PRIMARY KEY,
  endpoint_host TEXT NOT NULL,
  endpoint_port INTEGER NOT NULL,
  issuer_type TEXT NOT NULL,
  state TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 0,
  identifiers_json TEXT NOT NULL,
  profile TEXT NOT NULL,
  environment TEXT,
  dns_provider TEXT,
  certificate_id TEXT REFERENCES certificates(id),
  error_code TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

Add `Database.compare_and_set_job(job_id, expected_state, expected_version, new_state, updates)` using one conditional `UPDATE ... WHERE state=? AND version=?` and raise `ConcurrentUpdateError` when `rowcount != 1`.

- [ ] **Step 4: Write and implement idempotent legacy migration**

`tests/test_json_migration.py` must create a representative `certmon_data.json`, run `migrate_legacy_nonsecrets()`, assert devices and legacy renewals exist once, rerun migration, and assert counts remain unchanged. The migration must:

- import manual hosts, scan ranges, certificates, renewal records, and upload devices;
- never import plaintext device passwords into ordinary device columns;
- set `legacy_nonsecrets_imported_at` but not final migration completion;
- leave the source JSON unchanged for Task 3 to import its secrets securely.

- [ ] **Step 5: Replace ongoing JSON writes**

Change `load_data()` and `save_data()` only into a temporary compatibility adapter backed by SQLite. Existing routes must continue to receive the same dictionary shape until Tasks 11-13 move them to repositories. No route may write `certmon_data.json` after migration.

- [ ] **Step 6: Verify and commit**

Run: `pytest tests/test_db.py tests/test_json_migration.py -v`

Expected: all tests pass, including the compare-and-set concurrency test.

```powershell
git add certmon/db.py app.py tests
git commit -m "feat: add transactional sqlite persistence"
```

### Task 3: Encrypt All Private Material and Add Recovery

**Files:**
- Create: `certmon/vault.py`
- Create: `tests/test_vault.py`
- Create: `tests/test_recovery.py`
- Modify: `certmon/db.py`

- [ ] **Step 1: Write failing envelope-encryption tests**

```python
# tests/test_vault.py
from certmon.vault import MemoryKeyProtector, Vault


def test_vault_round_trip_uses_unique_ciphertexts(tmp_path):
    protector = MemoryKeyProtector()
    vault = Vault(tmp_path, protector)
    vault.initialize()
    first = vault.encrypt(b"private-key", purpose="device-key")
    second = vault.encrypt(b"private-key", purpose="device-key")
    assert first.ciphertext != second.ciphertext
    assert vault.decrypt(first, purpose="device-key") == b"private-key"


def test_authenticated_metadata_cannot_be_changed(tmp_path):
    protector = MemoryKeyProtector()
    vault = Vault(tmp_path, protector)
    vault.initialize()
    blob = vault.encrypt(b"secret", purpose="cloudflare-token")
    blob.purpose = "device-password"
    with pytest.raises(InvalidTag):
        vault.decrypt(blob, purpose="device-password")
```

- [ ] **Step 2: Implement the vault interfaces**

Define:

```python
class KeyProtector(Protocol):
    def protect(self, plaintext: bytes) -> bytes: ...
    def unprotect(self, protected: bytes) -> bytes: ...


@dataclass
class EncryptedBlob:
    key_id: str
    nonce: bytes
    ciphertext: bytes
    purpose: str
```

Use `AESGCM` with a random 32-byte installation key, a fresh 12-byte nonce, and `purpose.encode()` as associated data. Implement `WindowsDpapiProtector` using `CryptProtectData`/`CryptUnprotectData` through `ctypes`; use `MemoryKeyProtector` only in tests. Fail closed on non-Windows unless a protector is explicitly configured.

- [ ] **Step 3: Add secrets repository tests and implementation**

Store only `key_id`, nonce, ciphertext, purpose, timestamps, and metadata in SQLite. Add `put_secret`, `get_secret`, `delete_secret`, and `list_secret_metadata`; there must be no method that lists plaintext values.

Complete the legacy migration here: read passwords from the still-present legacy JSON, encrypt them directly into the vault, link their secret IDs to devices, set `legacy_json_migrated_at` in the same database transaction, and only then copy the source to `certmon_data.<UTC timestamp>.bak.json`. Rerunning after interruption must neither duplicate secrets nor overwrite newer credentials.

- [ ] **Step 4: Add recovery-package tests**

Test that `create_recovery_package(passphrase)` uses scrypt, contains versioned KDF parameters, restores the installation key into a fresh protector, rejects a wrong passphrase, and never writes the passphrase. Use `cryptography.hazmat.primitives.kdf.scrypt.Scrypt` and AES-GCM to wrap the master key.

- [ ] **Step 5: Add rewrap and rotation tests**

Test service-account migration by unprotecting with protector A and protecting with protector B without changing encrypted payloads. Test master-key rotation by simulating interruption after one item, rerunning, and asserting every secret decrypts under the new key ID.

- [ ] **Step 6: Verify and commit**

Run: `pytest tests/test_vault.py tests/test_recovery.py -v`

Expected: all encryption, tamper, recovery, rewrap, and resumable rotation tests pass.

```powershell
git add certmon/vault.py certmon/db.py tests
git commit -m "feat: protect private material with encrypted vault"
```

### Task 4: Add Encrypted Artifact Storage and Certificate Profiles

**Files:**
- Create: `certmon/artifacts.py`
- Create: `certmon/profiles.py`
- Create: `tests/test_artifacts.py`
- Create: `tests/test_profiles.py`
- Modify: `app.py:454-787`

- [ ] **Step 1: Write profile contract tests**

```python
# tests/test_profiles.py
from certmon.profiles import PROFILES


def test_extron_profile_is_rsa_2048_with_expected_usages():
    profile = PROFILES["extron-rsa"]
    assert profile.key_type == "rsa"
    assert profile.key_size == 2048
    assert profile.key_usage == {"digital_signature", "content_commitment", "key_encipherment", "data_encipherment"}
    assert profile.extended_key_usage == {"server_auth"}


def test_modern_profile_is_p256_server_auth():
    profile = PROFILES["generic-ecdsa"]
    assert profile.key_type == "ecdsa"
    assert profile.curve == "secp256r1"
    assert profile.extended_key_usage == {"server_auth"}
```

- [ ] **Step 2: Implement immutable profile definitions**

Create `CertificateProfile` as a frozen dataclass. Define exactly `generic-ecdsa`, `generic-rsa`, and `extron-rsa`. Add `recommend_profile(device_type)` returning `extron-rsa` for Extron and `generic-ecdsa` otherwise.

- [ ] **Step 3: Write encrypted artifact tests**

Test atomic creation of certificate directories, encrypted private-key storage, public certificate reads, prohibited general reads of private artifacts, and controlled temporary plaintext cleanup after exceptions.

- [ ] **Step 4: Implement artifact contracts**

```python
class ArtifactStore:
    def create_certificate_set(self, certificate_id: str, public_files: dict[str, bytes], private_files: dict[str, bytes], metadata: dict) -> None: ...
    def read_public(self, certificate_id: str, name: str) -> bytes: ...
    @contextmanager
    def materialize_private(self, certificate_id: str, name: str): ...
```

Public artifacts may be stored as PEM. `private-key.pem` and `combined.pem` must be vault-encrypted. For `extron-rsa`, combined plaintext is leaf certificate followed by an unencrypted RSA private key; do not append the chain.

- [ ] **Step 5: Migrate existing CA files**

On first startup, detect `C:\CertMon\CA` and the prior non-Windows CA directory. Import the CA private key into the vault, store its certificate publicly, import issued leaf/key/PEM sets, verify key matches, and move originals into a timestamped restricted migration backup only after verification. Keep existing CA endpoints functional through adapters until Task 11.

- [ ] **Step 6: Verify and commit**

Run: `pytest tests/test_profiles.py tests/test_artifacts.py -v`

Expected: all tests pass and no plaintext private artifact remains after materialization contexts close.

```powershell
git add certmon/artifacts.py certmon/profiles.py app.py tests
git commit -m "feat: add encrypted certificate artifacts and profiles"
```

### Task 5: Implement Renewal Job State Machine and Permissions

**Files:**
- Create: `certmon/models.py`
- Create: `certmon/permissions.py`
- Create: `certmon/renewals.py`
- Create: `tests/test_renewal_jobs.py`
- Create: `tests/test_permissions.py`

- [ ] **Step 1: Write transition tests**

Test allowed transitions including `draft -> awaiting_dns`, `draft -> awaiting_external_ca`, `issuing -> issued`, `deployment_pending -> deployed`, and cleanup transitions. Test rejection of `deployed -> issuing`, double advancement with stale version, and cancellation idempotence.

- [ ] **Step 2: Implement states and transition map**

```python
class RenewalState(str, Enum):
    DRAFT = "draft"
    AWAITING_DNS = "awaiting_dns"
    VALIDATING = "validating"
    ISSUING = "issuing"
    AWAITING_EXTERNAL_CA = "awaiting_external_ca"
    ISSUED = "issued"
    DEPLOYMENT_PENDING = "deployment_pending"
    DEPLOYED = "deployed"
    CLEANUP_REQUIRED = "cleanup_required"
    CANCELLED = "cancelled"
    FAILED = "failed"
```

`RenewalService.transition()` must call the database compare-and-set update and append a sanitized event in the same transaction.

- [ ] **Step 3: Add identifier normalization tests**

Test lowercase IDNA DNS normalization, SAN deduplication, separation of endpoint IP from identifiers, wildcard preservation, and public ACME rejection of IPs, `.local`, single-label names, and reserved names.

- [ ] **Step 4: Add permission boundaries**

Define the six permissions from the design. `authorize(permission)` uses an implicit local principal in Phase 1, but every sensitive service method and Flask route must call it. Tests monkeypatch denial and assert no database, filesystem, DNS, or deployment side effect occurs.

- [ ] **Step 5: Add startup recovery**

`recover_interrupted_jobs()` leaves `awaiting_dns` and `awaiting_external_ca` unchanged, reconciles ACME jobs through an injected ACME service, and examines recorded Cloudflare IDs for cleanup. Unknown active state becomes `failed` with `recovery_state_unknown` rather than creating a duplicate order.

- [ ] **Step 6: Verify and commit**

Run: `pytest tests/test_renewal_jobs.py tests/test_permissions.py -v`

Expected: all state, concurrency, normalization, recovery, and permission tests pass.

```powershell
git add certmon/models.py certmon/permissions.py certmon/renewals.py tests
git commit -m "feat: add resumable renewal job orchestration"
```

### Task 6: Build Key, CSR, and Certificate Validation Services

**Files:**
- Create: `certmon/certificates.py`
- Create: `tests/test_certificates.py`
- Create: `tests/fixtures/certificates/`

- [ ] **Step 1: Write key and CSR tests**

For each profile, assert key type/size, CSR CN, normalized SANs, signature validity, and no CA basic constraint. Include DNS and IP SANs for Local CA/External CA, but assert ACME callers reject IPs before CSR creation.

- [ ] **Step 2: Implement key and CSR generation**

Expose `generate_private_key(profile)`, `build_csr(key, identifiers, profile)`, and `serialize_private_key(key, passphrase=None)`. Keep passphrases in memory only long enough to encrypt the key into the vault.

- [ ] **Step 3: Write import-validation tests**

Fixtures must cover matching/mismatched keys, expired/not-yet-valid leaves, a leaf marked as CA, unordered chains, invalid signatures, path-length violations, public roots, configured enterprise roots, and explicitly accepted private roots.

- [ ] **Step 4: Implement validation with trust separated from cryptography**

Return:

```python
@dataclass(frozen=True)
class ChainValidation:
    cryptographically_valid: bool
    trust_status: Literal["system", "enterprise", "explicit_private", "untrusted"]
    ordered_chain: tuple[x509.Certificate, ...]
    errors: tuple[str, ...]
```

Verify public-key matching, signatures, issuer/subject linkage, validity, Basic Constraints, path length, and `keyCertSign`. Do not install imported roots.

- [ ] **Step 5: Verify and commit**

Run: `pytest tests/test_certificates.py -v`

Expected: all profile, CSR, key-match, chain, and trust-status cases pass.

```powershell
git add certmon/certificates.py tests
git commit -m "feat: add csr and certificate validation services"
```

### Task 7: Implement Local CA and External CA Workflows

**Files:**
- Create: `certmon/local_ca.py`
- Create: `certmon/external_ca.py`
- Create: `tests/test_local_ca.py`
- Create: `tests/test_external_ca.py`
- Modify: `app.py:454-787`

- [ ] **Step 1: Port Local CA tests before moving behavior**

Capture current CA generation and Extron leaf behavior in tests: ten-year CA, 825-day leaf, SANs, Authority Key Identifier, profile usages, and combined PEM ordering.

- [ ] **Step 2: Implement `LocalCAService` using vault/artifact services**

Generate or load the CA through certificate IDs rather than raw file paths. Issue leaves using named profiles. Return metadata and artifact IDs, never `key_pem` or passphrases in normal JSON responses.

- [ ] **Step 3: Write External CA lifecycle tests**

Test `draft -> awaiting_external_ca` after CSR creation, CSR public download, restart persistence, signed certificate completion, existing certificate/key import, identifier mismatch rejection, and explicit private-root trust recording.

- [ ] **Step 4: Implement `ExternalCAService`**

```python
def create_csr_job(job_id: str) -> str:  # returns public CSR artifact name
def complete_csr_job(job_id: str, leaf: bytes, chain: bytes | None, trust_anchor_id: str | None) -> str:  # certificate ID
def import_existing(job_id: str, leaf: bytes, chain: bytes | None, private_key: bytes, passphrase: str | None, trust_anchor_id: str | None) -> str:
```

All validation happens before artifact/database writes. Completion and certificate linkage commit transactionally.

- [ ] **Step 5: Redirect legacy CA endpoints**

Keep existing endpoint URLs temporarily, but make them call `LocalCAService`. Remove private key/passphrase fields from responses and add a compatibility error explaining that deployments now use certificate IDs.

- [ ] **Step 6: Verify and commit**

Run: `pytest tests/test_local_ca.py tests/test_external_ca.py -v`

Expected: offline issuance/import workflows pass without internet access.

```powershell
git add certmon/local_ca.py certmon/external_ca.py app.py tests
git commit -m "feat: add local and external ca renewal workflows"
```

### Task 8: Implement ACME Accounts and Order Lifecycle

**Files:**
- Create: `certmon/acme_service.py`
- Create: `tests/test_acme_accounts.py`
- Create: `tests/test_acme_orders.py`
- Modify: `requirements.txt`
- Modify: `certmon.spec`

- [ ] **Step 1: Add dependencies**

```text
acme>=3.0.0
josepy>=1.14.0
dnspython>=2.6.0
```

Add their modules/data to the PyInstaller specification only where PyInstaller analysis does not discover them automatically.

- [ ] **Step 2: Write mocked account registration tests**

Test required contact email, explicit ToS acceptance, separate staging/production accounts and keys, stored account URL/ToS metadata, and lost-account-key warning followed by explicit replacement.

- [ ] **Step 3: Implement `ACMEAccountService`**

Wrap the `acme.client.ClientV2` API behind an injectable client factory. Store account private keys through the vault and metadata through SQLite. Never expose `JWKRSA` or private key JSON through Flask.

- [ ] **Step 4: Write mocked order tests**

Test order creation for normalized DNS identifiers, DNS-01 challenge extraction, authorization polling, finalization with CertMon CSR, certificate-chain download, problem-document translation, retry-after parsing, and reconciliation of an existing order URL after restart.

- [ ] **Step 5: Implement `ACMEOrderService`**

Return structured challenge records and order references. Network polling must have bounded attempts/deadlines and run outside database write transactions. Convert ACME errors into stable codes such as `acme_rate_limited`, `acme_rejected_identifier`, and `acme_validation_failed`.

- [ ] **Step 6: Verify and commit**

Run: `pytest tests/test_acme_accounts.py tests/test_acme_orders.py -v`

Expected: all mocked account, order, retry, and recovery tests pass without network access.

```powershell
git add certmon/acme_service.py requirements.txt certmon.spec tests
git commit -m "feat: add native acme account and order services"
```

### Task 9: Implement Manual DNS and Cloudflare Providers

**Files:**
- Create: `certmon/dns/__init__.py`
- Create: `certmon/dns/base.py`
- Create: `certmon/dns/manual.py`
- Create: `certmon/dns/cloudflare.py`
- Create: `tests/test_manual_dns.py`
- Create: `tests/test_cloudflare_dns.py`

- [ ] **Step 1: Define provider contract and tests**

```python
@dataclass(frozen=True)
class DNSChallengeRecord:
    fqdn: str
    value: str


class DNSProvider(Protocol):
    def present(self, records: tuple[DNSChallengeRecord, ...]) -> tuple[PresentedRecord, ...]: ...
    def cleanup(self, presented: tuple[PresentedRecord, ...]) -> CleanupResult: ...
```

Test duplicate TXT values for wildcard/base-domain combinations and idempotent cleanup.

- [ ] **Step 2: Implement authoritative manual DNS checks**

Use dnspython to find authoritative nameservers and query TXT values directly. Return per-record visibility. Do not continue merely because the user clicked confirm. Add an expiry timestamp to manual challenges and reject continuation after expiry.

- [ ] **Step 3: Write Cloudflare API tests**

Mock `requests.Session`. Test token verification, longest-suffix zone selection, restricted zone access, TXT creation, returned record IDs, cleanup after success/failure, idempotent 404 cleanup, pagination, and redaction of token/request headers.

- [ ] **Step 4: Implement Cloudflare provider**

Use `Authorization: Bearer <token>`, explicit request timeouts, and stable error codes. Store token in the vault and only its secret ID/configured zones in SQLite. Presented record metadata contains zone ID, record ID, name, and job ID but no challenge value after validation completes.

- [ ] **Step 5: Verify and commit**

Run: `pytest tests/test_manual_dns.py tests/test_cloudflare_dns.py -v`

Expected: provider and cleanup tests pass with no network calls.

```powershell
git add certmon/dns tests
git commit -m "feat: add manual and cloudflare dns providers"
```

### Task 10: Orchestrate ACME Issuance and Production Gating

**Files:**
- Modify: `certmon/renewals.py`
- Create: `tests/test_acme_renewal_flow.py`
- Create: `tests/integration/test_letsencrypt_staging.py`

- [ ] **Step 1: Write full mocked workflow tests**

Cover manual DNS pause/resume, Cloudflare automatic present/validate/cleanup, certificate artifact creation, rate-limit failure with retry time, cleanup-required state, cancellation, stale manual challenge replacement, and restart reconciliation.

- [ ] **Step 2: Implement ACME orchestration**

`start_acme(job_id)` creates/reuses the account, creates the order, records order/auth URLs, and either pauses at `awaiting_dns` or invokes Cloudflare. `continue_manual_dns(job_id)` verifies authoritative visibility before answering challenges. Successful finalization stores leaf, chain, full chain, key, and metadata through `ArtifactStore` and transitions to `issued`.

- [ ] **Step 3: Enforce staging proof**

Normalize and hash the exact identifier set. Before production order creation, require a successful staging certificate event for the same hash. Return `staging_required` with an action link; do not include a bypass in Phase 1.

- [ ] **Step 4: Add opt-in staging integration test**

Mark the test `@pytest.mark.acme_staging` and skip unless `CERTMON_ACME_STAGING_TEST=1` plus test-domain/provider variables exist. The test must never select production and must clean TXT records in `finally`.

- [ ] **Step 5: Verify and commit**

Run: `pytest tests/test_acme_renewal_flow.py -v`

Expected: mocked end-to-end flows pass.

Run: `pytest -m "not acme_staging" -v`

Expected: normal suite passes without external access.

```powershell
git add certmon/renewals.py tests
git commit -m "feat: orchestrate dns-01 certificate issuance"
```

### Task 11: Replace Renewal and Credential APIs

**Files:**
- Modify: `app.py:282-329`
- Create: `tests/test_renewal_api.py`
- Create: `tests/test_credentials_api.py`

- [ ] **Step 1: Write API contract tests**

Test create draft with endpoint plus editable identifiers, select issuer/profile, manual DNS continuation, external CSR download/import, Cloudflare credential create/list/delete, cancel, retry cleanup, job detail, public artifact download, and forbidden private-key access. Assert no response contains `key_pem`, token, device password, passphrase, or challenge credential.

- [ ] **Step 2: Implement service wiring**

Create services once in an application bootstrap function and keep route handlers thin. Replace `/api/renew` command generation with job creation. Preserve `/api/renewals` as a sanitized job list. Remove command strings from the model and Excel export.

- [ ] **Step 3: Add explicit sensitive routes**

Private export, DNS credential management, CA management, issuance, and deployment routes call their permission before parsing or loading secrets. Private export returns an attachment only after `download_private_key` authorization and records an event.

- [ ] **Step 4: Verify and commit**

Run: `pytest tests/test_renewal_api.py tests/test_credentials_api.py -v`

Expected: API contracts and secret-absence assertions pass.

```powershell
git add app.py tests
git commit -m "feat: expose secure renewal workflow api"
```

### Task 12: Build the Renewal Wizard UI

**Files:**
- Modify: `templates/index.html:376-439`
- Modify: `templates/index.html:678-839`
- Modify: `templates/index.html:969-1100`
- Create: `tests/test_ui_contract.py`

- [ ] **Step 1: Add DOM contract tests**

Parse rendered HTML and assert the wizard contains separate endpoint and identifiers fields, three issuer choices, three profiles, manual/Cloudflare DNS choices, staging/production controls, External CA CSR/import controls, resumable status actions, and no Certbot/acme.sh selector.

- [ ] **Step 2: Replace the modal with a step-based wizard**

Steps:

1. Endpoint and editable identifiers.
2. Issuer: Let's Encrypt, Local CA, External CA/Import.
3. Profile and issuer-specific options.
4. Review and start.
5. Job-state action panel for DNS records, CSR download/import, results, or errors.

Use text labels in addition to color. Display production gating before submission. Never place private PEM or stored secrets in DOM state.

- [ ] **Step 3: Render resumable job actions**

Map states to exact actions: `awaiting_dns` -> Verify and continue/Cancel; `awaiting_external_ca` -> Download CSR/Import signed cert/Cancel; `cleanup_required` -> Retry cleanup; `issued` -> Deploy now/Keep for later; `failed` -> show sanitized error and allowed retry.

- [ ] **Step 4: Verify with tests and browser**

Run: `pytest tests/test_ui_contract.py -v`

Expected: all DOM contracts pass.

Run CertMon locally and use the in-app Browser to exercise Local CA, External CA pause/resume, manual DNS pause, validation errors, and responsive modal layout. Record screenshots only if visual defects need comparison.

- [ ] **Step 5: Commit**

```powershell
git add templates/index.html tests/test_ui_contract.py
git commit -m "feat: add certificate renewal wizard"
```

### Task 13: Refactor Deployment to Server-Side Certificate IDs

**Files:**
- Create: `certmon/deployment.py`
- Create: `tests/test_deployment.py`
- Modify: `app.py:788-1080`
- Modify: `templates/index.html:1302-1535`

- [ ] **Step 1: Write deployment security tests**

Assert the API accepts only `certificate_id` and `device_id`, rejects PEM fields, materializes keys only inside the server adapter, removes temporary plaintext after success/failure, and records an audit-ready event.

- [ ] **Step 2: Move existing Extron logic behind an adapter**

```python
class DeploymentAdapter(Protocol):
    def deploy(self, device: Device, certificate: DeploymentMaterial) -> DeploymentResult: ...


class ExtronDeploymentAdapter:
    def deploy(self, device, certificate): ...
```

Preserve current Extron endpoint attempts initially, but accept in-memory server material and never browser-provided PEM. Generic devices return instructions and public artifact links only.

- [ ] **Step 3: Add fingerprint verification**

After an adapter reports success, rescan the endpoint and compare SHA-256 DER fingerprints. Distinguish `verified`, `unreachable`, and `different_certificate`. Only `verified` transitions the job to `deployed`; other outcomes remain `deployment_pending` with details.

- [ ] **Step 4: Update UI calls**

Replace certificate/key text areas and upload payloads with certificate selection by ID. Preselect Extron only from saved/detected device type. Keep explicit manual private export separate.

- [ ] **Step 5: Verify and commit**

Run: `pytest tests/test_deployment.py -v`

Expected: no private key crosses the Flask test client boundary and fingerprint statuses pass.

```powershell
git add certmon/deployment.py app.py templates/index.html tests
git commit -m "feat: deploy certificates entirely server side"
```

### Task 14: Add Backup, Restore, Packaging, and Final Verification

**Files:**
- Create: `certmon/backup.py`
- Create: `tests/test_backup.py`
- Modify: `launcher.py`
- Modify: `certmon.spec`
- Modify: `README.md`
- Modify: `build.bat`

- [ ] **Step 1: Write backup/restore tests**

Test SQLite online backup, coordinated encrypted artifact snapshot, HMAC-authenticated manifest, hash mismatch rejection, wrong recovery package rejection, mismatched backup ID rejection, representative key fingerprint validation, and source-backup immutability.

- [ ] **Step 2: Implement backup and restore services**

Quiesce artifact mutations with a narrow application lock, use SQLite's `backup()` API, copy encrypted artifacts, write the versioned manifest, then release the lock. Restore goes to a new directory, verifies fully, and requires an explicit final directory swap outside the service.

- [ ] **Step 3: Update launcher and packaging**

Initialize data directory, database migrations, vault, and startup job recovery before opening the browser. Add required hidden imports. Update `build.bat` to install from `requirements.txt` instead of duplicating dependency names.

- [ ] **Step 4: Update operator documentation**

Document:

- three issuer workflows;
- staging-before-production behavior;
- Cloudflare token scope;
- recovery package creation and storage warning;
- backup/restore and service-account migration;
- `CERTMON_DATA_DIR`;
- current single-user limitation and requirement to remain loopback-only until Phase 2 authentication exists;
- private-key export risk;
- optional staging integration-test variables.

- [ ] **Step 5: Run complete verification**

Run:

```powershell
pytest -m "not acme_staging" -v
python -m compileall app.py launcher.py certmon tests
pyinstaller certmon.spec --clean --noconfirm
```

Expected: test suite passes, compilation succeeds, and `dist\CertMon.exe` is produced.

Launch the EXE with a temporary `CERTMON_DATA_DIR`; verify startup, legacy migration, Local CA issuance, External CA CSR pause/resume, sanitized renewal UI, restart recovery, and server-side deployment request shape.

- [ ] **Step 6: Commit**

```powershell
git add certmon/backup.py launcher.py certmon.spec README.md build.bat tests
git commit -m "feat: complete secure renewal delivery"
```

## Final Acceptance Check

- [ ] Scanned IP and requested DNS identifiers remain separate in API, database, and UI.
- [ ] Local CA works offline for IP and internal DNS SANs.
- [ ] External CA supports resumable CSR completion and validated existing imports.
- [ ] Manual and Cloudflare DNS-01 complete staging issuance.
- [ ] Production requires prior staging success for the same normalized identifiers.
- [ ] All private material and credentials are encrypted at rest.
- [ ] Recovery package, backup/restore, service-account rewrap, and key rotation are tested.
- [ ] SQLite prevents lost updates and duplicate job advancement.
- [ ] The browser never receives private PEM during deployment.
- [ ] Extron-compatible RSA profile and deployment verification work.
- [ ] Certbot and acme.sh are absent from the user-facing renewal workflow.
- [ ] The packaged Windows EXE remains self-contained.
