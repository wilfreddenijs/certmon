# CertMon Certificate Renewal Design

## Purpose

Upgrade CertMon's renewal feature from command generation to real, generic
certificate issuance. Phase 1 supports Let's Encrypt through ACME DNS-01, the
existing CertMon Local CA, and certificates issued by an external CA. Issuance
is independent from deployment, with optional Extron deployment offered after
a certificate is issued.

Authentication is a separate Phase 2 project. Phase 1 defines permission
boundaries so local accounts, Active Directory/LDAPS, and OIDC can enforce
them later without restructuring the issuance engine.

## Scope

Phase 1 includes:

- Native Python ACME issuance using DNS-01.
- Let's Encrypt staging and production environments.
- Manual DNS challenges that work with any DNS provider.
- Automatic Cloudflare DNS challenges.
- Encrypted Cloudflare credentials stored on the CertMon server.
- Existing Local CA issuance presented through the same renewal workflow.
- CSR generation and completed-certificate import for external CAs.
- Import of an existing certificate, chain, and matching private key.
- Secure storage of keys, certificates, chains, and issuance metadata.
- Resumable renewal jobs with sanitized logs.
- Optional post-issuance deployment, with Extron preselected when detected.
- Endpoint rescanning and certificate fingerprint verification after deployment.
- Permission hooks for the later shared-server authentication phase.

Phase 1 does not include:

- User authentication or role management.
- Active Directory, OIDC, or local account login.
- Unattended scheduled renewals.
- Automatic DNS providers other than Cloudflare.
- Automatic deployment to generic devices.
- A requirement to install Certbot, acme.sh, or another external ACME client.

## Product Decisions

Users choose an issuance source, not an implementation tool:

- **Let's Encrypt** for publicly registered DNS names.
- **Local CA** for private IP addresses and internal hostnames.
- **External CA / Import** for company CAs, commercial CAs, and certificates
  obtained outside CertMon.

Certbot and acme.sh are removed from the user-facing renewal selector. CertMon
uses a native Python ACME engine so the source and Windows executable behave
consistently.

The scanned endpoint and requested certificate identifiers are separate data.
For example, CertMon may connect to `192.168.0.43:443` while requesting a
certificate for `wilfred.denijs.com`. A scanned IP address must never silently
become an ACME identifier.

## Architecture

### Certificate Service

The certificate service:

- validates requested DNS names and IP addresses;
- creates private keys and certificate signing requests;
- reads CN and SAN candidates from scanned certificates;
- writes certificate artifacts atomically;
- calculates certificate fingerprints;
- exposes metadata without exposing private-key material.

Certificate issuance uses named profiles rather than ad hoc key parameters:

- **Generic modern:** ECDSA P-256, SHA-256, digital signature key usage, and
  server-auth EKU.
- **Generic RSA:** RSA 2048, SHA-256, digital signature and key encipherment,
  and server-auth EKU for devices that do not support ECDSA.
- **Extron compatible:** RSA 2048, SHA-256, the Extron-compatible key usages
  already produced by CertMon, server-auth EKU, and an Extron-compatible PEM
  representation.

The wizard recommends a profile from the saved or detected device type but
allows the user to select another compatible profile. RSA keys smaller than
2048 bits, SHA-1 signatures, CA basic constraints on leaf certificates, and
client-auth EKU are not generated in Phase 1.

### ACME Service

The ACME service owns:

- ACME account registration and account-key storage;
- staging and production directory selection;
- order creation and authorization handling;
- DNS-01 challenge preparation and validation;
- finalization, certificate download, and chain handling;
- structured error translation, including rate-limit retry times.

ACME account creation requires a contact email and explicit acceptance of the
CA's current Terms of Service. Staging and production use separate accounts and
separate account keys. Account metadata records the directory URL, account URL,
contact email, ToS URL accepted, and creation time. Losing an account key does
not delete issued certificate artifacts; CertMon creates a new account only
after clearly warning that existing pending orders cannot be resumed.

The service uses the Python `acme` library and CertMon-generated key material.
It does not shell out to Certbot or acme.sh.

### External CA Service

The external CA service supports two workflows:

- **Generate CSR:** CertMon creates and retains a private key, generates a CSR
  for the selected CN/SANs, and allows the CSR to be downloaded for submission
  to a company or commercial CA. The returned certificate and optional chain
  are imported into the same pending job.
- **Import existing:** the user supplies a leaf certificate, optional issuer
  chain, and its private key when CertMon did not generate the key.

Before accepting an import, CertMon verifies that the leaf certificate matches
the stored or uploaded private key, is currently valid or has a clearly
displayed future validity date, has the expected CN/SAN identifiers, is not a
CA certificate, and forms a valid ordered chain when chain certificates are
provided. PEM and DER certificate input are accepted; private keys are accepted
only in supported PEM encodings. An encrypted private key requires its
passphrase for validation and protected storage.

Chain validation verifies each certificate signature, issuer/subject linkage,
validity period, Basic Constraints, path-length constraints, and CA key usage.
CertMon distinguishes cryptographic chain validity from trust. A chain may end
at an operating-system-trusted public root, a configured enterprise trust
anchor, or an explicitly accepted private root supplied with the import. A
private root is not installed into the server or colleague trust stores as a
side effect. Incomplete or self-consistent but untrusted chains may be inspected
but cannot proceed to deployment until the user explicitly records the intended
trust anchor.

### DNS Provider Interface

DNS providers implement a small interface for creating and deleting ACME TXT
records. Phase 1 includes:

- **Manual DNS:** returns the exact TXT record name and value, then pauses.
- **Cloudflare:** creates and removes TXT records through a scoped API token.

The interface must permit additional providers without changing renewal jobs
or the UI workflow.

### Deployment Service

Deployment remains separate from issuance. An issued certificate can be kept
for later or passed to a deployment adapter. Phase 1 reuses the existing
deployment module and offers Extron when the device is detected or saved as an
Extron device. Generic devices receive artifact downloads and instructions.

Successful deployment is followed by a TLS rescan. CertMon compares the
observed certificate fingerprint with the issued certificate fingerprint and
records whether deployment was verified.

Deployment APIs accept a certificate ID and device ID only. The server loads
and decrypts the required key material internally and passes it directly to the
deployment adapter. Private-key PEM must never be sent to the browser and then
posted back for deployment. Manual private-key export is a separate audited
operation behind the `download_private_key` permission boundary.

## Renewal Job Model

Each renewal has a stable UUID rather than a list-length integer. A job stores
the endpoint, requested identifiers, issuer, ACME environment, DNS provider,
timestamps, state, artifact references, deployment state, and sanitized log.

Supported states are:

```text
draft
awaiting_dns
validating
issuing
awaiting_external_ca
issued
deployment_pending
deployed
cleanup_required
cancelled
failed
```

`failed` records retain enough non-secret context to retry or resume. After a
restart, jobs paused at `awaiting_dns` remain actionable. Jobs interrupted in
`validating` or `issuing` are marked recoverable and reconciled with their ACME
order before a new order is created.

Users may cancel draft, manual-DNS, and external-CA jobs. Cancellation first
attempts to remove DNS records and temporary challenge material. A job enters
`cleanup_required` when automatic cleanup cannot complete; it records safe,
specific remediation and can be retried. Expired manual challenges cannot be
continued: CertMon cancels the stale authorization, cleans its artifacts, and
creates a fresh authorization only after explicit user action. Abandoned
Cloudflare records are discovered from job metadata during startup recovery and
removed or surfaced as `cleanup_required`.

## Persistence And Concurrency

Job, credential metadata, certificate metadata, device records, and audit-ready
events are stored in SQLite rather than the current shared JSON document. Each
state transition and its related metadata changes occur in one transaction.
SQLite runs in WAL mode with foreign keys enabled and a bounded busy timeout.
Long-running ACME, DNS, scanning, and deployment network calls occur outside
write transactions; their results are committed using compare-and-set state
transitions so two workers cannot advance the same job concurrently.

Schema migrations are versioned and run before the application accepts
requests. The existing `certmon_data.json` is imported once through an
idempotent migration, retained as a timestamped backup, and never used for
ongoing writes after successful migration.

## User Flow

1. The user clicks **Renew** on a monitored certificate.
2. CertMon displays the target endpoint separately from editable CN/SAN domain
   candidates taken from the observed certificate.
3. The user chooses **Let's Encrypt**, **Local CA**, or **External CA / Import**.
4. Local CA issuance accepts private IP and DNS SANs and proceeds without
   internet access.
5. Let's Encrypt rejects IP identifiers and invalid/internal-only DNS names
   before creating an order.
6. The user selects staging or production and manual DNS or Cloudflare.
7. Manual DNS displays every required `_acme-challenge` TXT record and pauses
   until the user selects **Verify and continue**.
8. Cloudflare creates the records, waits for authoritative DNS visibility,
   completes validation, and removes the records.
9. External CA users either download a CertMon-generated CSR and return later
   to import the signed certificate, or import an existing certificate, chain,
   and private key. A CSR job pauses in `awaiting_external_ca`.
10. CertMon validates and stores the issued or imported artifacts and displays
    their issuer, expiry, and domains.
11. The user chooses **Deploy now** or **Keep for later**.
12. If deployment runs, CertMon rescans the endpoint and records fingerprint
    verification.

Production issuance for a domain set requires a successful staging issuance
for the same normalized set of identifiers. Phase 1 has no bypass because the
future Admin authorization needed to control a bypass does not yet exist.

## Storage

CertMon uses a configurable server data directory, separate from application
binaries. The default for an installed Windows service should be a protected
machine-data location. Development mode may use a repository-local data
directory.

```text
data/
  accounts/
    staging/
    production/
  certificates/
    <certificate-id>/
      certificate.pem
      chain.pem
      fullchain.pem
      private-key.pem
      request.csr
      combined.pem
      metadata.json
  ca/
  jobs/
  secrets/
```

SQLite metadata contains references and fingerprints, never plaintext private
keys or provider tokens. Artifact writes use temporary files plus atomic
replacement. On Windows, private directories and files receive ACLs restricted
to the CertMon service account and administrators.

`combined.pem` is a compatibility artifact, not a general download format. For
the Extron profile its plaintext form is ordered as leaf certificate followed
by an unencrypted RSA private key, matching the existing Toolbelt requirement;
the chain is kept in `chain.pem` and is not appended unless a future device
profile explicitly requires it. At rest, `combined.pem` is encrypted like every
other private-key-bearing artifact and has the same restricted ACL. It is
decrypted only for server-side deployment or an explicit, audited private-key
export. Temporary plaintext files are created only when an adapter requires a
path and are deleted immediately after use.

## Secrets

All private material is encrypted at rest, including Local CA keys, ACME account
keys, issued and imported device keys, encrypted-key passphrases, device
credentials, Cloudflare tokens, and private-key-bearing combined files.

CertMon uses envelope encryption. A random 256-bit installation master key is
protected by Windows DPAPI for the CertMon service account. Each secret or
private artifact is encrypted with AES-256-GCM using a fresh nonce and
authenticated metadata; plaintext is never written to SQLite. This supports
unattended service restarts while keeping cryptographic storage independent
from the shape of individual secret types.

Initial setup requires creation of an administrator recovery package. The
package contains the installation master key wrapped by a key derived from an
administrator-supplied recovery passphrase using scrypt with versioned
parameters. It is never stored beside the live data directory. Backups are
recoverable only with the database, encrypted artifacts, and this recovery
package/passphrase.

Backups use SQLite's online backup API and a coordinated snapshot of encrypted
artifacts. An authenticated manifest, protected by an HMAC key derived from the
installation master key, records schema version, backup ID, file hashes, and
the master-key identifier so restore cannot silently combine a database and
artifact directory from different generations. Restore verifies the manifest,
decrypts representative keys, validates their public-key fingerprints against
metadata, and leaves the original backup untouched. CertMon never includes a
plaintext key or the recovery passphrase in a backup.

Service-account or server migration is an explicit maintenance operation:
unlock the master key with the recovery package, protect it with DPAPI under the
new service account, verify decryption of representative artifacts, and only
then retire the old wrapper. Rotation creates a new master key and re-encrypts
all private material transactionally with resumable progress. The
secret-storage interface permits non-Windows protection backends later.

Cloudflare tokens must be scoped to `Zone:DNS:Edit` and `Zone:Zone:Read` for
only the zones CertMon manages. The API never returns token values after they
are stored. Logs redact tokens, device passwords, private keys, passphrases,
and ACME challenge credentials.

## DNS Challenge Behavior

Cloudflare zone selection uses the longest matching configured zone for the
requested identifier. CertMon verifies that the token can access the zone
before creating an ACME order.

TXT records created by CertMon are tagged in job metadata and removed after
successful validation. Cleanup is also attempted after failure. If cleanup
fails, the job reports the exact record name and a safe remediation message
without revealing credentials.

Manual DNS validation queries authoritative DNS servers. The UI shows which
records are visible and does not continue merely because the user clicked a
confirmation button.

## Security Boundaries

Phase 1 defines these permissions at API boundaries:

- `issue_certificate`
- `deploy_certificate`
- `download_public_certificate`
- `download_private_key`
- `manage_dns_credentials`
- `manage_local_ca`

Until Phase 2 adds authentication, the local application has an implicit
single-user context. Private-key download remains an explicit operation and
must not be included in ordinary certificate-list responses.

The Local CA private key and ACME account keys are never downloadable through
general artifact endpoints. Existing endpoints that expose device keys must
be routed through the explicit private-key permission boundary before shared
server deployment is considered supported.

## Error Handling

- Validation errors are returned before external side effects.
- ACME problem documents become concise user-facing errors plus sanitized job
  details.
- Rate-limit responses record and display the server-provided retry time.
- Automatic retries are bounded and never loop rapidly.
- Interrupted jobs reconcile existing ACME orders before creating replacements.
- External CA imports reject mismatched private keys, malformed chains, CA
  certificates, and certificates whose identifiers do not match the job unless
  the user explicitly starts a new import job for those identifiers.
- DNS cleanup failures do not discard an otherwise issued certificate.
- Cancellation is idempotent, and incomplete cleanup enters `cleanup_required`
  rather than falsely reporting cancellation as complete.
- Failed deployment does not invalidate or delete issued artifacts.
- Verification failure distinguishes an unreachable endpoint from a reachable
  endpoint still serving a different certificate.

## Testing

Unit tests cover:

- CN/SAN extraction and normalization;
- rejection of IP addresses and internal names for public ACME issuance;
- CSR and artifact generation;
- CSR download, external-certificate import, key matching, and chain validation;
- renewal state transitions and restart recovery;
- concurrent compare-and-set transitions and SQLite migration rollback;
- manual DNS record presentation and visibility checks;
- Cloudflare zone matching, record creation, and cleanup;
- DPAPI master-key wrapping and redaction;
- envelope encryption, recovery-package restore, service-account rewrapping,
  and interrupted master-key rotation;
- certificate-profile key type, size, KU, EKU, and Extron compatibility;
- ACME account registration, ToS acceptance, environment separation, and lost
  account-key recovery;
- cancellation, stale manual challenges, and cleanup-required recovery;
- ACME errors and rate-limit retry metadata;
- fingerprint comparison after deployment;
- permission boundary placement around sensitive endpoints.

Integration tests use Let's Encrypt staging and opt-in credentials. They are
not part of the default test run. Production issuance is never exercised by
automated tests.

Existing scan, Local CA, Excel export, and deployment behavior receives focused
regression tests around the interfaces changed by this work.

## Acceptance Criteria

- Renewing a certificate for an IP-hosted device uses editable DNS names from
  its CN/SANs and never generates an ACME request for the scanned IP.
- A user can complete a Let's Encrypt staging issuance using manual DNS-01.
- A user can store an encrypted Cloudflare token and complete automatic DNS-01
  issuance without the token appearing in JSON storage, API responses, or logs.
- A user can generate and download a CSR, restart CertMon, and later complete
  the same job by importing the signed certificate and chain.
- A user can import an existing certificate, chain, and matching private key;
  CertMon rejects mismatched keys and malformed chains before storing them.
- The same normalized domain set must pass staging before production issuance.
- An issued certificate produces private key, leaf, chain, full-chain, combined
  PEM, and metadata artifacts in a protected certificate directory.
- Every private-key-bearing artifact and stored credential is encrypted at rest,
  and a tested recovery package can restore access after server migration.
- Browser-based deployment submits certificate and device IDs only and never
  receives private-key PEM.
- Concurrent requests cannot overwrite renewal jobs or advance one job twice.
- Generic modern, Generic RSA, and Extron-compatible certificate profiles emit
  the specified key algorithms, usages, and EKUs.
- Local CA issuance remains available for private IPs and internal hostnames.
- Issuance succeeds independently of deployment.
- Extron is offered as the deployment target when detected, and post-deployment
  fingerprint verification records whether the device serves the new cert.
- Paused and interrupted jobs can recover after a CertMon restart.
- The Windows executable remains self-contained and does not require Certbot or
  acme.sh to be installed.

## Follow-On Phase

Phase 2 converts CertMon into a supported shared service with local accounts,
AD/LDAPS, and OIDC/Entra ID authentication; Admin and Operator roles; audit
logging; secure server configuration; and recovery-admin access. It will
enforce the permission boundaries defined here and support deployment behind
an HTTPS reverse proxy while CertMon remains bound to loopback.
