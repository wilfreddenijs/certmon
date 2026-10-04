---
phase: 05
slug: direct-extron-certificate-upload
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-10-04
---

# Phase 05 - Validation Strategy

## Test Infrastructure

Reuse pytest, pytest.ini, existing deployment/vault/API tests and the browser
permission harness. No hardware operation is authorized by automated tests.
Quick command: `py -m pytest tests/test_deployment.py tests/test_toolbelt_api.py tests/test_rbac.py tests/test_csrf.py`.
Full command: `py -m pytest` with the existing opt-in external ACME exclusion.
Runtime and exact new test filenames must be measured/finalized by the planner.

## Sampling Rate

- After each task: run its focused, non-watch-mode unit/API/browser tests.
- After each wave: run the full offline suite; no secrets or real device writes.
- Before human UAT: all automated regressions must pass.
- Target focused feedback within 120 seconds; split tests if this is exceeded.

## Verification Map (To Be Bound To Final Plans)

| Behavior | Secure behavior | Verification |
|----------|-----------------|--------------|
| Host-key trust | Unknown/changed keys rejected before sending secrets | Fake SSH endpoints; explicit enrollment/rotation API tests |
| Test action | No PEM materialization, transfer or ingest | Transport call assertions plus API/browser test |
| Activation | SFTP alone never counts as success | Exact SIS acknowledgement and expected HTTPS fingerprint tests |
| Ambiguous activation | No automatic replay of potentially completed ingest | Disconnect/timeout tests with verification-only recovery |
| Credentials | Stored encrypted; never returned in logs/API/audit | Vault and redaction regressions |
| Permissions | Existing deployment permission, CSRF and attribution retained | Pure-role and additive-role API/browser matrix |
| Interface selection | LAN B verified only at its chosen HTTPS endpoint | Separate LAN A/B address and fingerprint tests |
| Batch handling | Missing device fails that entry, no wrong-target retry loop | Selection, cancellation, progress and stale-state tests |

## Wave 0 Requirements

- Add fake SSH/SFTP and segmented SIS response fixtures before transport tasks.
- Add direct-upload service/API tests and browser expectations using existing harnesses.
- Each future task must name its automated command and existing or Wave 0 test file.
- The final planner/checker must bind this map to task IDs and threat references.

## Manual-Only Verification

On explicitly authorized test devices, record model/firmware, SSH host-key trust,
SIS command framing/response, selected LAN endpoint, and active certificate
fingerprint. Cover a one-LAN device and both interfaces of a two-LAN device.
Confirm no reboot, passphrase behavior, cleanup and partial failure behavior.
Toolbelt retirement is blocked until these replacement tests are accepted.

## Validation Sign-Off

- [ ] Every final plan task has focused automated verification or a Wave 0 dependency.
- [ ] No three consecutive implementation tasks lack automated feedback.
- [ ] Missing test fixtures are created before use.
- [ ] Full offline suite passes without watch-mode flags.
- [ ] Physical acceptance evidence is recorded separately from automated success.
- [ ] Final plan/checker binds requirements and security threats to test commands.

Approval: pending. No phase implementation or physical testing has occurred.
