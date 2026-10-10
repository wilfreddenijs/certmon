---
phase: "05"
plan: "05-03"
status: partial
subsystem: transport-batch-security
reconciled: "2026-10-10"
requirements-completed: []
---

# Plan 05-03: Implemented Protocol And Batch, With Contract Gaps

## Delivered

- `f86ab3a`, `de1370a`, `3a266f4`: confirmed SFTP size, terminal echo-aware
  NIC acknowledgement handling, absent-file cleanup and bounded HTTPS switch wait.
- `f278c57`: exact-selected sequential Direct batches, progress snapshots,
  stop-after-current-device, server-side certificate resolution and guarded APIs.
- `03ca875`: automatic first-use endpoint pinning, changed-key rejection, persisted
  per-device NIC and distinct LAN B HTTPS configuration.
- `13305e6`: individual -> shared -> admin/extron password candidates, no Direct
  automatic serial discovery and no import replay after ambiguous transmission.
- `586ed64`: durable per-device upload Audit outcomes and optional successful-row
  cleanup only after results are recorded.
- Staged PEM records, deadlines, endpoint identities and pending/failed cleanup
  survive restart via database settings; recovery does not retransmit SIS import.

## Existing Test Evidence

`tests/test_direct_extron.py`, `tests/test_direct_batch.py`, `tests/test_credentials.py`,
`tests/test_upload_queue.py`, `tests/test_rbac.py` and `tests/test_csrf.py` cover
protocol, trust, credentials, selected batches, recovery and access boundaries.
API cases are integrated into these suites rather than the planned standalone
`tests/test_direct_extron_api.py`. Aggregate CI evidence: 05-VERIFICATION.md.

## Why This Plan Remains Partial

- Original durable run/progress requirement is not implemented: `_batches` is an
  in-memory dictionary. A restart loses the live run snapshot and does not resume
  or replay it. Durable staged recovery and Audit outcomes are not equivalent.
- Original strict one-credential and manual first-use approval requirements were
  superseded by user decisions, not fulfilled verbatim.
- Expansion occurred before the complete hardware checkpoint was recorded;
  this document must not backdate acceptance of that dependency.
- A complete independent original-contract/security review is still required,
  including planned reverify/passphrase behavior and evidence coverage. Existing
  tests are not a declaration that every original threat assertion is satisfied.

No new code changes or scope-waiver decisions were made during reconciliation.

## Subsequent Closure Review

The user requested the closure steps on 2026-10-10. 05-CLOSURE-REVIEW.md records
the current inline contract/security comparison and the outstanding decisions.
No answer to the batch-persistence or LAN B acceptance questions is yet recorded.
The plan remains partial; new source packaging tests do not change its status.
