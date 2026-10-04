---
phase: 02
plan: 02-06
subsystem: shared-server-mode
tags: [rbac, browser, permissions, session]
requires: [02-05]
provides: [effective-permission-ui, public-catalog, protected-401-reset]
affects: [app.py, templates/index.html, tests]
tech_stack:
  added: []
  patterns: [server-derived permission union, public artifact allowlist, one-shot protected 401 recovery]
key_files:
  created: []
  modified: [app.py, templates/index.html, tests/test_rbac.py, tests/test_ui_contract.py, tests/test_rbac_browser.py]
decisions:
  - Browser visibility consumes only the server-provided effective permission union.
  - Upload discovery uses the public catalog and renders only listed public artifacts.
  - Protected 401 responses reset the UI once without retrying the request.
metrics:
  duration: resumed after quota interruption
  completed: 2026-10-02
status: complete
actuals:
  tokens: 7867
  tasks: 3
  commits: 6
---

# Phase 02 Plan 06: Shared Server Mode Visibility Summary

Effective RBAC visibility, public-only certificate discovery, and one-shot session recovery now run through the real Chromium client.

## Completed Tasks

1. **Task 06-01: Viewer public-download tracer**
   - Exposed sorted effective permissions and a safe public certificate catalog.
   - Retained deployment/private denials and added authorization to inventoried mutations.
   - Commits: `3134f68` (RED), `87315da` (GREEN).

2. **Task 06-02: Permission-derived rendered visibility**
   - Replaced role-name visibility checks with `hasPermission`, centralized metadata visibility, and mixed-tab synchronization.
   - Viewer uses `/api/certificates/public` and does not load Audit, users, backup, Toolbelt, or the deploy catalog.
   - Commits: `93a10ec` (RED), `3dc4719` (GREEN).

3. **Task 06-03: Protected next-401 recovery**
   - Added a shared protected-response handler for wrapped fetch and the native Audit loader.
   - Revocation clears protected client state and returns to sign-in without replaying the rejected Audit request.
   - Commits: `eb1b13c` (RED), `1533281` (GREEN).

## Verification

- `py -3 -m pytest tests/test_rbac.py tests/test_auth_api.py tests/test_ca_api.py tests/test_local_ca_server_mode.py -q` - 27 passed in 16.47s.
- `py -3 -m pytest tests/test_ui_contract.py tests/test_rbac_browser.py -q` - 35 passed in 20.76s.
- `py -3 -m pytest tests/test_rbac_browser.py -k "next_401 or revoked_session or revoked_security_admin_audit_next_401 or expired_session or wrong_login" -q` - 1 passed, 3 deselected in 10.54s.
- `py -3 -m pytest tests/test_user_management.py tests/test_auth_api.py -q` - 23 passed in 21.26s.

## Deviations from Plan

### Auto-fixed Issues

1. **[Rule 1 - Test isolation] Removed an eager application import from browser tests**
   - **Found during:** Task 06-02 browser coverage.
   - **Issue:** Importing the application during test collection could initialize the default runtime data directory outside the live test fixture.
   - **Fix:** The test imports the already-started app only after the isolated live fixture is running.
   - **Files modified:** `tests/test_rbac_browser.py`.
   - **Commit:** `eb1b13c`.

## Known Stubs

None.

## Self-Check: PASSED

- Confirmed all five plan files exist.
- Confirmed task commits `3134f68`, `87315da`, `93a10ec`, `3dc4719`, `eb1b13c`, and `1533281` exist.
