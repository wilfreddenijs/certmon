---
phase: "05"
plan: "05-04"
status: completed
subsystem: upload-ui-packaging-documentation
reconciled: "2026-10-10"
requirements-completed: []
---

# Plan 05-04: Released UI, Windows Build And Documentation

Completed implementation scope; phase acceptance is still gated by 05-02 and
05-03. This is not a declaration that their original dependencies passed.

## Delivered

- Unified prepared-device list with Direct/Toolbelt methods, per-device NIC,
  credential dialogs, selected batches and explicit upload actions.
- Readable main results with technical diagnostics collapsed; sticky navigation
  and device-selection toolbar, issuer/name filters and device refresh after upload.
- Optional successful-row cleanup, replacement confirmation for duplicate device
  certificates and visible individual-password status.
- Audit Excel/date cleanup (`bb58ce3`), stored-certificate dates/deletion
  (`2f69cd4`, test-contract correction `cfbab08`).
- Updated README, then illustrated `docs/user-manual.md` and 16 real UI screenshots
  with fictional data (`15e5151`). The Markdown manual replaces the planned RTF
  artifact; no production secrets or real device actions were used for screenshots.

## Verified Existing Release Evidence

- Build 53: source `cfbab086d22d3ccc1cd0de7ebb46ff5d8e884c78`;
  Windows workflow run 37822940201 succeeded.
- Matching test run 37822940364: **523 passed, 1 deselected in 161.90s**.
  The excluded case is opt-in external ACME staging, not a silently skipped failure.
- Manual capture completed for all 16 screens; image links and staged diff checked.
- No new EXE or full regression run was needed for this planning-only reconciliation.

## Remaining Boundaries

Toolbelt remains supported. Packaging success and browser download acceptance
do not certify absence of malware/false positives. Hardware LAN B acceptance,
restart-progress disposition and independent phase review remain open.
