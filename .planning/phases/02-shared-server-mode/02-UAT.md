---
status: testing
phase: 02-shared-server-mode
source:
  - .planning/phases/02-shared-server-mode/02-01-SUMMARY.md
started: 2026-07-07T22:47:18+02:00
updated: 2026-07-09T15:42:00+02:00
---

## Current Test

number: 7
name: Audit Log
expected: |
  Sensitive actions such as login/logout, failed login, private-artifact download, DNS credential change, Toolbelt run, deployment, or Local CA backup/import should appear in the Audit tab with user/source IP and without secret values.
awaiting: user response

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
result: [blocked-issue]
note: Roles and permission checks exist, but no admin UI/API exists yet to create additional users. End-to-end UAT cannot create a Viewer user through normal app workflow.

### 6. CSRF Protection
expected: Normal UI actions should work after login, while direct state-changing API calls without the CertMon CSRF header should be rejected in server mode.
result: [passed]
note: Browser console XHR without CSRF header returned 403 with `{"error":"CSRF token required"}`. Earlier fetch-based helper was invalid because the UI wraps `window.fetch` and injects CSRF automatically; helper updated to use XMLHttpRequest.

### 7. Audit Log
expected: Sensitive actions such as login/logout, failed login, private-artifact download, DNS credential change, Toolbelt run, deployment, or Local CA backup/import should appear in the Audit tab with user/source IP and without secret values.
result: [issue-fixed-pending-retest]
note: Initial UAT reported the Audit tab stayed indefinitely on "Loading audit...". Added UI timeout and error rendering for `/api/audit` failures so the tab no longer hangs silently.

### 8. Local CA Trust Bundle
expected: The Local CA tab should offer a Trust bundle download. The downloaded ZIP should contain the public CA certificate and instructions only, not the Local CA private key.
result: [pending]

### 9. Backup And Recovery Metadata
expected: Backup/restore behavior should preserve server-mode users, roles, sessions where applicable, Local CA data, certificate metadata, and audit records; private-key backup/export actions should remain permission-gated.
result: [pending]

### 10. LAN Browser UAT
expected: From a second machine or browser on the LAN, open the server-mode URL. Unauthenticated access should show login/setup, authenticated access should work according to role, and desktop/local mode should remain unaffected on the host machine.
result: [pending]

## Summary

total: 10
passed: 5
issues: 2
pending: 3
skipped: 0
blocked: 1

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
<!-- YAML format for plan-phase --gaps consumption -->
