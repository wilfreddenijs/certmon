---
status: complete
phase: 02-shared-server-mode
source:
  - .planning/phases/02-shared-server-mode/02-01-SUMMARY.md
started: 2026-07-07T22:47:18+02:00
updated: 2026-08-20T14:15:00+02:00
---

## Current Test

[testing complete]

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
note: Follow-up polish requested: Enter key should submit Sign in; first-admin password setup should require entering the password twice with match validation.

### 5. Role Restrictions
expected: A lower-privilege user such as Viewer should be able to view allowed public information but should not be able to start certificate issuance, manage CA/private-key operations, or view restricted audit/security actions.
result: issue
reported: "All works as expected, however there are no user roles available other than admin. This whole module to create and manage user roles is still missing"
severity: major
note: Roles and permission checks exist, but no admin UI/API exists to create or manage users and their roles. End-to-end role restriction testing is therefore unavailable through the normal application workflow.

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
result: issue
reported: "Where is the backup button?"
severity: major
note: The Local CA tab exposes Export CA backup and Import CA backup, but these only transfer the encrypted Local CA. The full BackupService exists in code and automated tests, but no UI, API, or CLI workflow exposes full server backup/restore to an operator.

### 10. LAN Browser UAT
expected: From a second machine or browser on the LAN, open the server-mode URL. Unauthenticated access should show login/setup, authenticated access should work according to role, and desktop/local mode should remain unaffected on the host machine.
result: [passed]
note: LAN access, authentication, and unaffected desktop mode were confirmed. The unavailable lower-privilege role test is recorded separately as the UAT 5 user-management gap.

## Summary

total: 10
passed: 8
issues: 2
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
- truth: "An administrator can create and manage users, assign supported roles, and verify that lower-privilege users are restricted accordingly."
  status: failed
  reason: "User reported: All works as expected, however there are no user roles available other than admin. This whole module to create and manage user roles is still missing."
  severity: major
  test: 5
  artifacts:
    - path: "certmon/auth.py"
      issue: "Authentication creates the initial admin but exposes no subsequent user-management service."
    - path: "app.py"
      issue: "No authenticated user-management API routes are available."
    - path: "templates/index.html"
      issue: "No user or role administration interface is available."
  missing:
    - "Add permission-gated user creation, editing, disabling, and password reset operations."
    - "Add role assignment using the supported CertMon roles."
    - "Add an administrator UI and end-to-end role restriction tests."
- truth: "An operator can create and restore a full server backup preserving users, roles, applicable sessions, Local CA data, certificate metadata, and audit records."
  status: failed
  reason: "User reported: Where is the backup button? Full BackupService functionality is not exposed through the UI, API, or CLI; only Local CA export/import is available in the UI."
  severity: major
  test: 9
  artifacts:
    - path: "certmon/backup.py"
      issue: "BackupService is implemented but has no operator-facing entry point."
    - path: "templates/index.html"
      issue: "Only Local CA backup controls are present."
  missing:
    - "Add an authenticated, permission-gated full server backup workflow."
    - "Add a documented restore workflow that restores into a new directory and supports safe activation."
<!-- YAML format for plan-phase --gaps consumption -->
