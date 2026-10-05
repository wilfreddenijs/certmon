# Phase 05: Direct Extron Certificate Upload - Research

Research handoff captured 2026-10-04. This is the independent researcher's returned report; no implementation or physical test was performed.

## RESEARCH COMPLETE

**Phase:** 05 - Direct Extron Certificate Upload  
**Confidence:** MEDIUM

The direct replacement should be a server-side transport layer that preserves the existing deployment, vault, RBAC, CSRF, audit, per-device progress, cancellation, and HTTPS fingerprint verification boundaries. SFTP transfer alone must never count as success: require the exact SIS ingest acknowledgement and a matching HTTPS peer-certificate SHA-256 fingerprint on the selected interface. [VERIFIED: `docs/specs/extron-direct-upload.md`] [VERIFIED: `certmon/deployment.py:83-173,404-435`]

**Locked user evidence:** combined PEM via SFTP TCP 22022; authenticated SIS over SSH TCP 22023; immediate activation in the tested workflow; LAN A/NIC 1 default with per-device LAN B/NIC 2; Toolbelt retirement only after physical verification. [VERIFIED: `05-CONTEXT.md`] The SIS screenshot was visually inspected and confirms an ingest command, `CertV` acknowledgement, passphrase variant, and NIC values, but exact channel framing/control bytes remain hardware verification work. [VERIFIED: `docs/SIS command for Cert Ingest.png` visual inspection]

### Standard Stack

- Preserve Flask, existing `cryptography`, `ssl`, and `hashlib` deployment verification. [VERIFIED: `certmon/deployment.py:13-15,404-435`]
- Use `paramiko==5.0.0` for SSH host-key policy and SFTP only after a `checkpoint:human-verify`. Official docs cover host-key policies, SFTP sessions, authentication, and explicit closure. [CITED: https://docs.paramiko.org/en/stable/api/client.html] [CITED: https://docs.paramiko.org/en/stable/api/sftp.html]
- `py -m pip index versions paramiko` reports 5.0.0; PyPI reports it released 2026-05-09. [VERIFIED: PyPI registry command, 2026-10-04] [CITED: https://pypi.org/project/paramiko/]
- Package legitimacy returned `SUS` solely because downloads were unavailable; source repo is `github.com/paramiko/paramiko`. [VERIFIED: package-legitimacy check, 2026-10-04]

## Package Legitimacy Audit

| Package | Registry | Official upstream | Candidate | Status | Required before install |
|---------|----------|-------------------|-----------|--------|-------------------------|
| `paramiko` | PyPI `paramiko` | `github.com/paramiko/paramiko`; `docs.paramiko.org` | `5.0.0` from 2026-10-04 research, provisional | `SUS` | Plan 05-01 Task 05-01-01 must re-read official metadata, release files/hashes and Python compatibility, then obtain blocking human approval of the exact version before requirements or installation changes. |

`SUS` records an incomplete download/packaging verification, not an allegation about the project. The plan must not convert the provisional candidate into a blind pin.

### Architecture

```text
Explicit Activate
  -> guarded Flask route (RBAC + CSRF + audit)
  -> direct batch service / encrypted credentials
  -> temporary server-side combined PEM
  -> authenticated SFTP staging
  -> authenticated SSH SIS exact request/reply
  -> selected LAN HTTPS peer DER fingerprint comparison
  -> verified or pending/failed result + cleanup/audit/progress
```

A separate authenticated Probe/Test operation must not materialize PEM, write SFTP files, or send an ingest command. [VERIFIED: `docs/specs/extron-direct-upload.md`]

### Key Risks and Required Plan Gates

- Reject unknown or changed SSH host keys; do not use automatic acceptance. Paramiko’s documented default is rejection. [CITED: https://docs.paramiko.org/en/stable/api/client.html]
- Do not automatically retry SIS after timeout/disconnect: activation may already have occurred. Verify HTTPS and report an indeterminate result instead. [ASSUMED]
- Do not retain Toolbelt’s `__SERIAL__` credential fallback until a model-specific, authenticated direct serial query is accepted. Current Toolbelt code uses it. [VERIFIED: `certmon/toolbelt.py:415-426`; quote: `for candidate in (default.get("password"), "extron", "__SERIAL__"):`]
- Official Extron manuals show serial-query variance (`19I` versus `99I or 19I`), so no universal direct serial retrieval may be assumed. [CITED: https://media.extron.com/public/download/files/userman/68-2939-01_P_DXP_HD_4K_PLUS.pdf] [CITED: https://media.extron.com/public/download/files/userman/smp_401_68-3349-01_A.pdf]
- LAN B needs its own reachable HTTPS verification endpoint; LAN A verification is not evidence for LAN B. [VERIFIED: `docs/specs/extron-direct-upload.md`]
- Existing controls must remain: `DEPLOY_CERTIFICATE`, server-mode CSRF, private-material browser rejection, encrypted credentials, and audit attribution. [VERIFIED: `certmon/permissions.py:9-55`; quote: `DEPLOY_CERTIFICATE = "deploy_certificate"`] [VERIFIED: `app.py:284-301,2045-2080,2336-2357`] [VERIFIED: `certmon/vault.py:109-155`]

## Validation Architecture

- **Framework:** pytest 9.1.1; full command: `py -m pytest`. [VERIFIED: `py -m pytest --version`, 2026-10-04]
- **Wave 0 tests needed:** fake direct SSH/SFTP transport tests; API/RBAC/CSRF/audit tests; no-browser-PEM regressions. [ASSUMED]
- **Automated coverage:** reject unknown host key before authentication/SFTP; Probe performs no ingest; SFTP-only success fails; exact SIS reply required; matching/mismatching/unreachable HTTPS fingerprints; no auto-replay after ambiguous ingest; secrets absent from response/log/audit. [ASSUMED] [VERIFIED: existing fingerprint pending/unreachable test patterns in `tests/test_deployment.py:253-379`]
- **Physical acceptance:** explicit Activate only, on one-LAN and two-LAN devices; record model/firmware, trusted host-key evidence, raw safe response evidence, selected interface HTTPS endpoint, and matching fingerprint. Toolbelt retirement follows only this acceptance. [VERIFIED: `docs/specs/extron-direct-upload.md`]

### Unresolved User Decisions

1. Host-key enrollment/rotation source, approver, persistent store, and audit wording.
2. Supported model/firmware allowlist and exact SIS interactive-channel framing.
3. Whether generated combined PEM needs the SIS passphrase form.
4. Whether remote staged PEM cleanup is allowed/required after activation.
5. LAN B address/HTTPS endpoint storage per upload target.
6. Whether direct serial retrieval is required at all, versus requiring saved/shared credentials.

No product changes, build, commit, push, branch change, or `.gsd/data` modification was performed.
