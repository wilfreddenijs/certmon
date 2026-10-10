---
phase: 05
slug: direct-extron-certificate-upload
status: gaps_found
nyquist_compliant: false
wave_0_complete: true
created: 2026-10-04
---

# Phase 05 - Validation Strategy

## Current Evidence Reconciliation

Updated 2026-10-10. The map below is the original planned strategy, not an
assertion that every task ran with its original gates/commands. Existing tracer
fixtures and automated suites are delivered; full phase compliance remains open.

Actual tests live in `tests/test_direct_extron.py`, `tests/test_direct_batch.py`,
`tests/test_upload_workspace_ui.py`, `tests/test_credentials.py` and
`tests/test_upload_queue.py`, plus existing RBAC/CSRF/Audit suites. The planned
`tests/test_direct_extron_api.py` does not exist; API coverage was integrated into
other suites. The later closure pass adds `tests/test_direct_extron_packaging.py`
with 2 passing source packaging contracts. Successful Windows CI remains separate
packaging evidence; source contracts do not execute the frozen application.

Build-53 test run 37822940364 passed 523 tests with one opt-in ACME staging
case deselected. These existing results were checked, not rerun, during this
documentation update. See 05-VERIFICATION.md for gaps and 05-UAT.md for hardware.

Useful current focused command (not executed during reconciliation):
`py -m pytest tests/test_direct_extron.py tests/test_direct_batch.py tests/test_upload_workspace_ui.py tests/test_credentials.py tests/test_upload_queue.py tests/test_rbac.py tests/test_csrf.py -m "not acme_staging" -q`.

No live device operation is implied by this command or by a green automated run.
Do not use the old nonexistent-file commands below as current instructions.

Subsequent closure run on 2026-10-10: `py -m pytest -m "not acme_staging" -q`
passed 523 tests, with 1 deselected, in 514.14s. The two new packaging contracts
were added after full-suite collection and passed separately in 4.67s. The inline
contract review is in 05-CLOSURE-REVIEW.md; physical acceptance and explicit
disposition of the remaining differences still prevent phase sign-off.

## Test Infrastructure

Reuse pytest, pytest.ini, existing deployment/vault/API tests and the browser
permission harness. No hardware operation is authorized by automated tests.
Quick command: `py -m pytest tests/test_deployment.py tests/test_toolbelt_api.py tests/test_rbac.py tests/test_csrf.py`.
Full command: `py -m pytest` with the existing opt-in external ACME exclusion.
New focused files are `tests/test_direct_extron.py`, `tests/test_direct_extron_api.py`, and `tests/test_direct_extron_packaging.py`.

## Sampling Rate

- After each task: run its focused, non-watch-mode unit/API/browser tests.
- After each wave: run the full offline suite; no secrets or real device writes.
- Before human UAT: all automated regressions must pass.
- Target focused feedback within 120 seconds; split tests if this is exceeded.

## Verification Map

| Task ID | Behavior | Test file(s) | Automated command |
|---------|----------|--------------|-------------------|
| 05-01-01 | Official Paramiko identity/version gate before install | Official PyPI JSON metadata | `py -c` metadata/upstream/release-hash assertion from 05-01 |
| 05-01-02 | LAN A/LAN B target UI/API, deterministic credential, fresh-channel SIS/ACK ordering, durable cleanup, and HTTPS tracer | `tests/test_direct_extron.py` | `py -m pytest tests/test_direct_extron.py -q --basetemp .tmp\pytest-05-01 -p no:cacheprovider` |
| 05-02-01 | One-LAN physical activation acceptance | `tests/test_direct_extron.py`; hardware evidence | Focused test command in 05-02, then blocking human checkpoint |
| 05-02-02 | LAN A/LAN B separate physical verification | `tests/test_direct_extron.py`; hardware evidence | Focused test command in 05-02, then blocking human checkpoint |
| 05-03-01 | Fresh-channel/preloaded ACK rejection, deterministic credentials, ambiguous-send recovery, durable guarded cleanup, and no replay | `tests/test_direct_extron.py` | `py -m pytest tests/test_direct_extron.py -q -k "host_key or sis or preloaded or fragmented or wrong_nic or credential or ambiguous or cleanup or restart or wrong_path or verification or reverify" --basetemp .tmp\pytest-05-03-protocol -p no:cacheprovider` |
| 05-03-02 | Exact-selected batch, missing target, stop-after-current, persisted progress | `tests/test_direct_extron.py` | `py -m pytest tests/test_direct_extron.py -q -k "batch or selection or missing or stop or persist" --basetemp .tmp\pytest-05-03-batch -p no:cacheprovider` |
| 05-03-03 | Target/trust/run APIs, RBAC, CSRF, audit redaction | `tests/test_direct_extron_api.py`, `tests/test_rbac.py`, `tests/test_csrf.py`, `tests/test_audit_api.py` | Focused API/security command in 05-03 |
| 05-04-01 | LAN controls, credential source/change/retest, host-key approval, cleanup remediation, progress, and manual/legacy retention | `tests/test_ui_contract.py`, `tests/test_direct_extron_api.py` | `py -m pytest tests/test_ui_contract.py tests/test_direct_extron_api.py -q --basetemp .tmp\pytest-05-04-ui -p no:cacheprovider` |
| 05-04-02 | Approved dependency and PyInstaller packaging | `tests/test_direct_extron_packaging.py` | Packaging test, `py -m pip check`, and `py -m PyInstaller certmon.spec --clean --noconfirm` from 05-04 |
| 05-04-03 | Direct/manual/credential/Toolbelt/security regressions plus full offline suite | Focused Phase 05 and existing regression files | Focused aggregate command and `py -m pytest -m "not acme_staging" -q --basetemp .tmp\pytest-05-full -p no:cacheprovider` |

## Wave 0 Requirements

- Task 05-01-02 creates LAN A/LAN B fake SSH/SFTP endpoints, preloaded/segmented/wrong-NIC SIS replies, credential-attempt recording, durable cleanup/restart fixtures, HTTPS verifier, API, and UI tracer fixtures before physical acceptance.
- Task 05-03-03 creates the dedicated API/security suite before the final UI and regression plan consumes it.
- Each future task must name its automated command and existing or Wave 0 test file.
- The final planner/checker must bind this map to task IDs and threat references.

## Manual-Only Verification

On explicitly authorized test devices, record model/firmware, SSH host-key trust,
SIS command framing/response, selected LAN endpoint, and active certificate
fingerprint. Cover a one-LAN device and both interfaces of a two-LAN device.
Confirm no reboot, passphrase behavior, deterministic credential selection, fresh-channel ACK ordering, and actionable cleanup/partial-failure behavior.
Toolbelt retirement is blocked until these replacement tests are accepted.

## Validation Sign-Off

- [ ] Every final plan task has focused automated verification or a Wave 0 dependency.
- [ ] No three consecutive implementation tasks lack automated feedback.
- [x] Tracer fixtures are delivered; standalone planned API/packaging file paths differ from actual suites.
- [x] Full offline CI suite passes without watch-mode flags (build 53, 523 passed).
- [ ] Physical acceptance evidence is recorded separately from automated success.
- [ ] Final plan/checker binds requirements and security threats to test commands.

Original planning binding was completed; implementation fixtures now exist.
Physical approval and independent final contract/security coverage review remain
pending. Nyquist compliance is not asserted until remaining gaps are reviewed.
