---
status: testing
phase: 02-shared-server-mode
source:
  - .planning/phases/02-shared-server-mode/02-01-SUMMARY.md
started: 2026-07-07T22:47:18+02:00
updated: 2026-07-09T13:45:00+02:00
---

## Current Test

number: 2
name: LAN Bind Safety Gate
expected: |
  Start CertMon with a LAN or wildcard bind host but without `CERTMON_SERVER_MODE=1`. It should refuse startup with a clear configuration error instead of exposing the app unauthenticated on the LAN.
awaiting: user response

## Tests

### 1. Desktop Mode Safety
expected: Start CertMon without server-mode environment variables. It should run in desktop mode on loopback only, with no login screen required and normal Devices/Renewals/Local CA/Upload access.
result: [passed]

### 2. LAN Bind Safety Gate
expected: Start CertMon with a LAN or wildcard bind host but without `CERTMON_SERVER_MODE=1`. It should refuse startup with a clear configuration error instead of exposing the app unauthenticated on the LAN.
result: [issue-fixed-pending-retest]
note: Initial UAT reported the Windows EXE still started. Root cause was `launcher.py` bypassing server-mode runtime config and hardcoding loopback startup. Fixed launcher runtime resolution and added regression tests.

### 3. First Admin Setup
expected: Start CertMon with `CERTMON_SERVER_MODE=1` and a LAN/loopback bind host using a fresh data directory. The first browser open should show a "Create first admin" flow; creating the admin signs you in and opens the normal app.
result: [pending]

### 4. Login, Logout, And Session
expected: In server mode after first-admin setup, logout should return to the sign-in screen. Wrong credentials should be rejected; correct credentials should sign in and restore app access.
result: [pending]

### 5. Role Restrictions
expected: A lower-privilege user such as Viewer should be able to view allowed public information but should not be able to start certificate issuance, manage CA/private-key operations, or view restricted audit/security actions.
result: [pending]

### 6. CSRF Protection
expected: Normal UI actions should work after login, while direct state-changing API calls without the CertMon CSRF header should be rejected in server mode.
result: [pending]

### 7. Audit Log
expected: Sensitive actions such as login/logout, failed login, private-artifact download, DNS credential change, Toolbelt run, deployment, or Local CA backup/import should appear in the Audit tab with user/source IP and without secret values.
result: [pending]

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
passed: 1
issues: 1
pending: 8
skipped: 0
blocked: 0

## Gaps

- 2026-07-09: UAT 2 found that the Windows launcher bypassed the LAN bind safety gate. Fixed in `launcher.py`; retest required with a new build.
<!-- YAML format for plan-phase --gaps consumption -->
