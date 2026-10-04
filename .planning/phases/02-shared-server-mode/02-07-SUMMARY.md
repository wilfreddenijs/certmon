---
phase: 02
plan: 02-07
subsystem: shared-server-mode
tags: [rbac, browser, permissions, uat, sessions]
requires: [02-05, 02-06]
provides: [browser-role-matrix, regression-evidence, human-uat-acceptance]
affects: [app.py, templates/index.html, tests/test_rbac_browser.py]
status: complete
completed: 2026-10-04
---

# Phase 02 Plan 07: Browser Validation And Human Acceptance

All three tasks are complete. The user accepted build 23 and authorized Phase 02
closure, documentation, commit/push and merge to main on 2026-10-04.

## Completed Tasks

1. Real Chromium role matrix covers five roles, additive unions, public artifacts,
   forbidden loaders/private sentinels, role/disable/password/expiry revocation,
   native Audit cleanup and desktop mode. Renewal controls cover nine states.
2. Focused and full regressions passed. Latest CI run 37218519929 on source
   `5da496d1501feafbb6d881d89e82aab587c4d5e8`: 288 passed, one external ACME
   staging test deselected in 83.07s. No browser skips or xfails.
3. Human UAT 5 passed on build 23. UAT now records 10 passed, no unresolved issues;
   G-02-2 resolved. Passed UAT 4 and 9 remain unchanged.

## Human Evidence

Viewer retains public tabs/downloads without Upload permission errors while
restricted actions are hidden. Role changes and password resets invalidate the
session on the next protected request. Disable blocks sign-in, Enable restores it.
Audit refresh after revocation clears the session; desktop needs no sign-in.
Final retest confirmed Viewer Renewals restrictions, adjacent Enable/Disable,
role information, old/new passwords, additive roles and expired-session cleanup.
The screenshot's viewer account also has ca_admin, so Delete entry is authorized.

## Corrections And Commits

- `6695f6e`, `0169c63`: failing role matrix followed by implementation/desktop fix.
- `0edc25f`, `91f8a74`: populated views, real public downloads, union loaders and controlled session timers.
- `abb0791`, `f405625`: regression evidence and human checkpoint.
- `5695459`: completed-render synchronization and CSS enforcement of hidden controls.
- `59e2397`: effective-permission Renewals controls and adjacent account actions.
- `5da496d`: authoritative role information table with desktop/mobile browser checks.

## Delivery

- Build 23: https://github.com/wilfreddenijs/certmon/actions/runs/37218527033
- Artifact: CertMon-Windows, 11309680161.
- Tests: https://github.com/wilfreddenijs/certmon/actions/runs/37218519929

## Residual Risk And Scope

Build-22 full CI had a backup test fail on a physical SQLite file comparison;
build-23 passed with unchanged backup code. This is an intermittent test-stability
follow-up, not a claimed repair. External ACME staging remains opt-in/deferred.
No physical Extron upload is newly verified here. Phase 05 direct SFTP/SIS upload
is next and remains unplanned/unimplemented. No new role model or live polling.

## Self-Check

All task commits exist; seven Phase 02 summaries exist after this summary. Human
acceptance is explicit, not inferred from automated tests or build authorization.
