# Phase 05 Closure Review

Reviewed inline on 2026-10-10 at the user's request to work through phase closure.
This is a current source/test review, not an independent external security audit.
The original plans and superseding decisions in 05-CONTEXT.md are both considered.

## Automated And Source Checks

- Fresh full non-staging regression run: `py -m pytest -m "not acme_staging" -q`,
  **523 passed, 1 deselected in 514.14s** on 2026-10-10. Collection preceded the
  addition of the two new packaging tests, which were run separately below.
- `tests/test_direct_extron_packaging.py`: 2 passed in 4.67s. Confirms approved
  installed Paramiko 5.0.0 and the PyInstaller app -> Direct -> Paramiko import
  chain; does not execute a frozen EXE or guarantee every runtime dependency.
- Existing Windows build-53 workflow successfully packaged the same production
  application. New source packaging tests do not require a new EXE.
- No real device write, scan, hostkey approval or trust installation was performed.

## Original Contract Comparison

| Contract | Current implementation / evidence | Closure result |
| --- | --- | --- |
| SFTP 22022 + fresh authenticated SIS 22023 | Paramiko transport, stage-size confirmation, protocol tests | Implemented |
| Exact NIC acknowledgement after confirmed write; no stale/replayed import | `_exact_ack`, bounded shell reader, ambiguity tests | Implemented with observed echo/terminal line-ending normalization |
| Matching selected HTTPS certificate before success | `_verify`, activation checks, HTTPS switch timeout tests | Implemented; independent physical LAN B still pending |
| Unknown and changed keys manually approved | First-use pinning explicitly requested later; changed keys still block before authentication | Superseded user decision, not original behavior |
| Exactly one credential, no fallback | Individual/shared/default candidates explicitly requested later; fallback only on authentication rejection | Superseded user decision; SIS replay remains prohibited |
| Exact selected batches; missing selector handled as failed row | API rejects any missing/unready selection with 400; never broadens to all devices | Safe behavior differs from original per-row continuation contract |
| Stop after current operation | `_execute_batch`, stop and lock tests | Implemented |
| Run/progress survives service recreation | Durable whitelisted database snapshots; unfinished runs restored as interrupted | Implemented; SQLite, no-replay and browser tests passed |
| Durable staged-file cleanup and no import replay | STAGED_KEY, recorded endpoint, grace/explicit finished confirmation, restart tests | Implemented |
| Standalone reverify API / run-scoped cleanup route | HTTPS check on ambiguity/import; cleanup uses a persisted staged basename, not a run URL | Standalone reverify route not delivered; route shape differs |
| Encrypted PEM/passphrase SIS variant | Generated combined PEM is decrypted locally inside the service; `_sis_command` has no passphrase argument | External encrypted-PEM import variant not delivered; no claim of support |
| Per-device LAN B target | Separate upload host, certificate NIC and LAN B HTTPS verification host | User-requested separation implemented; physical NIC-2 acceptance remains open |
| Actor-attributed operations | Request-layer Audit records actor; background outcomes have run_id but no actor/source fields themselves | Trace through batch-start run_id; stronger self-contained attribution not delivered |
| Server authorization / CSRF / private material handling | Direct routes require deploy_certificate; strict mutation fields, existing CSRF and no-private-material tests | Existing automated mitigation evidence; not blanket security certification |
| Dependency / packaging evidence | approved package checkpoint, successful Windows workflow, new source packaging tests | Source/build verified; physical/runtime claims remain bounded |
| User UI / docs / retained Toolbelt | Browser suites, illustrated manual, prior user EXE feedback | Delivered; Toolbelt not retired |

## Security Boundaries Reviewed

- T-05-01/05/09/15: endpoint-specific key pinning, changed-key rejection,
  reobserved approval and separately configured NIC verification. First-use is
  TOFU with the user's explicit earlier decision, not independent authentication.
- T-05-02/12/14: private PEM decrypted only inside materialization; public DTOs
  use identifiers/diagnostics; credentials are vaulted and not returned for display.
- T-05-03/11: request authorization, CSRF and auditing remain required. Background
  upload outcome attribution is linked through run_id rather than copied actor fields.
- T-05-04/13/18: bounded I/O, finite selected batches, operation locks and
  stop-between-devices. No claim of bounded lifetime retention for saved batches.
- T-05-06/07/08: model/firmware, LAN B endpoint/fingerprint and hardware evidence
  remain human acceptance items; no secrets should enter acceptance reports.
- T-05-10: partial/ambiguous sends do not trigger another ingest; read-only HTTPS
  verification and guarded SFTP deletion are separate from activation.
- T-05-SC/16/17: approved dependency, actual build, source packaging contracts and
  updated operator instructions. Build success is not antivirus certification.

## Pending User Input

The user explicitly requested durable batch snapshots and independently selectable
upload connections. Both are implemented with passing local tests. The LAN B
question concerned a certificate for NIC 2, verified on LAN B HTTPS, not necessarily
an upload connection through LAN B. No new physical acceptance evidence was supplied.

The other contract differences above must also receive an explicit disposition
(accepted scope amendment or fix/test work) before claiming full original-plan
completion. They are not silently waived by green regression tests.

## Current Result

Closure review performed; final acceptance remains pending. Refer to 05-UAT.md
and 05-VERIFICATION.md. Do not archive the milestone or retire Toolbelt.
