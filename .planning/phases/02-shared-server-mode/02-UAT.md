---
status: diagnosed
phase: 02-shared-server-mode
source:
  - .planning/phases/02-shared-server-mode/02-01-SUMMARY.md
  - .planning/phases/02-shared-server-mode/02-VERIFICATION.md
started: 2026-07-07T22:47:18+02:00
updated: 2026-08-24T00:00:00+02:00
---

## Current Test

### Gap-closure retest (Tests 4, 5, and 9)

status: completed with remaining issue
published_commit: e2e806d50f3f5f6a99eb32b3dea5535d5f9fab7c
workflow_run: https://github.com/wilfreddenijs/certmon/actions/runs/32497863521
workflow_run_id: 32497863521
build_number: 15
artifact: CertMon-Windows (artifact ID 9452352191)
note: The successful Windows artifact is built from the local gap-closure commit, not the stale previously tested remote commit e89fa8d0d9b4159b9c3e2058b787b59ccaeea649. Retest only the unresolved browser workflows before changing any gap status.

## Tests

### 1. Desktop Mode Safety
expected: Start CertMon without server-mode environment variables. It should run in desktop mode on loopback only, with no login screen required and normal Devices/Renewals/Local CA/Upload access.
result: [passed]

### 2. LAN Bind Safety Gate
expected: Start CertMon with a LAN or wildcard bind host but without `CERTMON_SERVER_MODE=1`. It should refuse startup with a clear configuration error instead of exposing the app unauthenticated on the LAN.
result: [passed]
note: Initial UAT reported the Windows EXE still started. Root cause was `launcher.py` bypassing server-mode runtime config and hardcoding loopback startup. After fix/rebuild, CertMon did not start and logged `CONFIG ERROR: LAN binding requires CERTMON_SERVER_MODE=1. Default desktop mode is loopback-only.`

### 3. First Admin Setup
expected: Start CertMon with `CERTMON_SERVER_MODE=1` and a LAN/loopback bind host using a fresh data directory. The first browser open should show a "Create first admin" flow; creating the admin signs you in and opens the normal app.
result: [passed]

### 4. Login, Logout, And Session
expected: In server mode after first-admin setup, logout should return to the sign-in screen. Wrong credentials should be rejected; correct credentials should sign in and restore app access.
result: [passed]
note: Build 15 UAT confirmed that pressing Enter submits the authentication form. Login/logout, wrong-credential rejection, correct-credential access restoration, and the Enter-key follow-up all passed.

### 5. Role Restrictions
expected: A lower-privilege user such as Viewer should be able to view allowed public information but should not be able to start certificate issuance, manage CA/private-key operations, or view restricted audit/security actions.
result: issue
reported: "Viewer still sees role-restricted controls and navigation. In Upload, `Download all Extron PEMs` is visible but returns a function-not-available error when clicked. The Audit tab/button is visible, but Refresh audit reports `Your role cannot view the audit log`."
severity: major
note: The Administration UI/API is present and backend authorization appears to deny the restricted actions correctly. The remaining UAT 5 failure is frontend role visibility: unauthorized controls and navigation must not be shown to a Viewer. Retest creation of a viewer, role restrictions and visibility, role changes, disable/enable, password reset, and session revocation through the normal workflow.

### 6. CSRF Protection
expected: Normal UI actions should work after login, while direct state-changing API calls without the CertMon CSRF header should be rejected in server mode.
result: [passed]
note: Browser console XHR without CSRF header returned 403 with `{"error":"CSRF token required"}`. Earlier fetch-based helper was invalid because the UI wraps `window.fetch` and injects CSRF automatically; helper updated to use XMLHttpRequest.

### 7. Audit Log
expected: Sensitive actions such as login/logout, failed login, private-artifact download, DNS credential change, Toolbelt run, deployment, or Local CA backup/import should appear in the Audit tab with user/source IP and without secret values.
result: [passed]
note: UAT confirmed Audit tab renders `login_succeeded`, `login_failed`, `logout`, and `first_admin_created` with username and source IP, and without secrets. Earlier loading issue was fixed by replacing missing `esc()` helper usage with `escapeHtml()`.

### 8. Local CA Trust Bundle
expected: The Local CA tab should offer a Trust bundle download. The downloaded ZIP should contain the public CA certificate and instructions only, not the Local CA private key.
result: [passed]
note: Confirmed that the ZIP contains the same public CA certificate as Download CA cert plus README.txt, without Local CA private-key material.

### 9. Backup And Recovery Metadata
expected: Backup/restore behavior should preserve server-mode users, roles, sessions where applicable, Local CA data, certificate metadata, and audit records; private-key backup/export actions should remain permission-gated.
result: [passed]
note: Build 15 UAT confirmed that the Administration module exposes full server backup and staged recovery controls, including the displayed offline activation and rollback steps.

### 10. LAN Browser UAT
expected: From a second machine or browser on the LAN, open the server-mode URL. Unauthenticated access should show login/setup, authenticated access should work according to role, and desktop/local mode should remain unaffected on the host machine.
result: [passed]
note: LAN access, authentication, and unaffected desktop mode were confirmed. The unavailable lower-privilege role test is recorded separately as the UAT 5 user-management gap.

## Summary

total: 10
passed: 9
issues: 1
pending: 0
skipped: 0
blocked: 0

## Gaps

- 2026-07-09: UAT 2 found that the Windows launcher bypassed the LAN bind safety gate. Fixed in `launcher.py`; retest required with a new build.
- 2026-07-09: UAT 4 polish follow-up: Sign in should submit on Enter, and first-admin password setup should require password confirmation with a match check.
- 2026-07-09: UAT 5 blocked: user/role management is not exposed in the admin UI/API, so role restrictions cannot be tested end-to-end with a Viewer user from normal workflows.
- 2026-07-09: UAT 7 found the Audit tab could remain stuck on "Loading audit..." with no visible error. Added timeout/error UI; retest required with a new build.
- 2026-07-10: UAT 7 retest on build 6 still hung on "Loading audit...". Reworked Audit tab to use an independent UI timeout guard and native fetch bypass for `/api/audit?limit=100`; retest required.
- 2026-07-10: UAT 7 retest still showed the independent timeout guard text but did not transition. Reworked Audit tab to use `XMLHttpRequest` with native `xhr.timeout = 10000`; retest required.
- 2026-07-10: UAT 7 retest on build 8 still showed the XHR guard text without transition. Added backend timeout for `/api/audit` so audit retrieval returns 504 JSON instead of waiting indefinitely; retest required.
- 2026-08-13: UAT 7 retest still showed no visible timeout. Reworked Audit tab away from async/Promise style to callback-based XHR plus visible elapsed-second watchdog, so retest can show whether browser timers are running.
- 2026-08-13: UAT 7 retest showed XHR watchdog stuck at 0s. Reworked Audit tab again to render/tick first and start the audit request in a deferred native fetch callback, avoiding XHR send in the initial click handler.
- 2026-08-13: UAT 7 retest showed deferred watchdog stuck at 0s. Isolated tab open from audit loading and added a timer-only diagnostic button to distinguish browser timer blockage from audit request blockage.
- 2026-08-14: UAT 7 retest showed Refresh audit stuck at 0s. Delayed the audit fetch until after 1.5s and added an "Open raw audit JSON" link to test `/api/audit` outside the in-page loader.
- 2026-08-20: UAT 7 raw JSON proved `/api/audit` returns valid events. Root cause found in UI renderer: audit template used missing `esc()` helper instead of `escapeHtml()`. Fixed audit rendering and added render-error fallback.
- gap_id: G-02-1
  truth: "Pressing Enter on the authentication screen submits the active login or setup action exactly once."
  status: resolved
  reason: "Build 15 UAT passed: pressing Enter submits the authentication form."
  test: 4
  root_cause: "The tested executable was built from remote commit e89fa8d and predates local commit 60f86cf, which adds native form submission for the Enter key."
  artifacts:
    - path: "templates/index.html"
      issue: "The remote build has a click-only authentication button; local HEAD has the corrected submit form."
  resolved_by:
    - "Build 15 UAT on commit e2e806d50f3f5f6a99eb32b3dea5535d5f9fab7c"
  debug_session: ".planning/debug/auth-enter-key-stale-build.md"
- gap_id: G-02-2
  truth: "An administrator can create and manage users, assign supported roles, and verify that lower-privilege users are restricted accordingly."
  status: failed
  reason: "UAT 5 retest: a Viewer still sees role-restricted Upload and Audit controls/navigation. `Download all Extron PEMs` is visible but returns a function-not-available error, and Refresh audit reports `Your role cannot view the audit log`."
  severity: major
  test: 5
  artifacts:
    - path: "certmon/auth.py"
      status: implemented
    - path: "app.py"
      status: implemented
    - path: "templates/index.html"
      status: implemented
  missing:
    - "Hide or avoid rendering role-restricted navigation and controls for a Viewer, including the Audit tab/button and Upload's `Download all Extron PEMs` control."
    - "Retest the Viewer workflow after frontend role visibility is corrected; backend authorization currently appears to deny the restricted actions correctly."
  root_cause: "The stale-build delivery gap was resolved by build 15, which includes the Administration user-management UI. UAT 5 now identifies a separate frontend role-visibility gap: server-side authorization denies the restricted actions, but the Viewer UI still exposes their controls and navigation."
  debug_session: ".planning/debug/admin-module-missing-uat-test-5.md"
- gap_id: G-02-3
  truth: "An operator can create and restore a full server backup preserving users, roles, applicable sessions, Local CA data, certificate metadata, and audit records."
  status: resolved
  reason: "Build 15 UAT passed: Administration exposes full server backup and staged recovery controls."
  test: 9
  artifacts:
    - path: "certmon/server_backup.py"
      status: implemented
    - path: "app.py"
      status: implemented
    - path: "templates/index.html"
      status: implemented
  resolved_by:
    - "Build 15 UAT on commit e2e806d50f3f5f6a99eb32b3dea5535d5f9fab7c"
  root_cause: "The stale-build delivery gap was resolved by build 15, which includes Administration backup and recovery controls."
  debug_session: ".planning/debug/admin-backup-recovery-missing.md"
<!-- YAML format for plan-phase --gaps consumption -->
