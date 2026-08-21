---
phase: 02-shared-server-mode
verified: 2026-08-21T10:00:00+02:00
status: human_needed
score: 14/17 must-haves verified
behavior_unverified: 3
behavior_unverified_items:
  - truth: "Sign-in submits with Enter and first-admin setup requires matching passwords in the browser."
    test: "Repeat first-admin setup and login using the keyboard."
    expected: "Mismatched setup passwords are blocked and Enter submits exactly once."
    why_human: "The server validation and HTML contract are tested, but actual browser keyboard behavior is not exercised."
  - truth: "An administrator can complete the local-user lifecycle through the Administration tab."
    test: "Create a viewer, change roles, disable and enable the account, and reset its password."
    expected: "Each action succeeds, permissions change after sign-in, and stale sessions are revoked."
    why_human: "API behavior is covered, but the complete browser workflow is not exercised by an end-to-end browser test."
  - truth: "The full server backup UI clearly stages recovery and presents safe offline activation instructions."
    test: "Export and stage a full backup from Administration using a temporary server data directory."
    expected: "Restore creates a new sibling directory, leaves active data untouched, and displays stop, switch, and rollback steps."
    why_human: "Package and API behavior are tested, but operator comprehension and the rendered workflow need human review."
---

# Phase 02: Shared Server Mode Verification Report

**Phase Goal:** Turn CertMon into a safe shared LAN service with authenticated local users, role-based access, CSRF protection, user-aware auditing, guarded key handling, user administration, and full server backup with staged recovery.
**Verified:** 2026-08-21
**Status:** human_needed

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Local-only mode remains the default. | VERIFIED | `resolve_runtime_config()` defaults to loopback and desktop mode; `tests/test_server_mode_config.py` and `tests/test_launcher_config.py` exercise both configuration and launcher reconstruction. |
| 2 | Server mode requires authentication before LAN binding is supported. | VERIFIED | LAN binding is rejected without `CERTMON_SERVER_MODE=1`; server-mode API access requires a session in `tests/test_auth_api.py`. |
| 3 | Private keys reach the browser only through explicit private-artifact exports. | VERIFIED | Private downloads are isolated routes with permission checks; UI contracts prove wizard and upload state do not embed PEM key material. |
| 4 | The Local CA private key is never offered as a normal UI artifact. | VERIFIED | Trust-bundle tests prove public-only content; Local CA key transfer remains an explicit encrypted backup operation. |
| 5 | An administrator can create, edit, disable, enable, and reset another local user. | PRESENT_BEHAVIOR_UNVERIFIED | Service and API behavior pass in `tests/test_user_management.py`; Administration UI wiring passes contract tests, but the complete browser flow needs UAT. |
| 6 | Only supported roles can be assigned and role changes affect later requests. | VERIFIED | `SUPPORTED_ROLES` exactly matches `ROLE_PERMISSIONS`; invalid roles are rejected and role changes revoke sessions. |
| 7 | Disabling users and resetting passwords revoke their sessions. | VERIFIED | Mutations and session deletion share `BEGIN IMMEDIATE` transactions; direct and API tests prove old sessions stop authenticating. |
| 8 | The final enabled administrator cannot be disabled or lose the admin role. | VERIFIED | Database-backed checks and `test_final_enabled_admin_cannot_be_disabled_or_lose_admin_role` cover both paths. |
| 9 | User-management endpoints authorize before processing submitted changes. | VERIFIED | Every `/api/users` route calls `authorize(Permission.MANAGE_USERS)` first; lower roles receive 403 across all endpoints. |
| 10 | User audit events identify actor and target without password material. | VERIFIED | Audit tests assert username, source IP, target, and absence of plaintext passwords, hashes, and PBKDF2 values. |
| 11 | Enter submits sign-in and first-admin setup requires two matching passwords. | PRESENT_BEHAVIOR_UNVERIFIED | Server confirmation is behavior-tested; form submission, client equality checks, autocomplete, and field clearing pass UI contract tests, but keyboard behavior needs UAT. |
| 12 | Authorized roles can download an encrypted, integrity-protected full backup. | VERIFIED | Admin and security-admin API tests export a ZIP backed by the authenticated `BackupService` manifest. |
| 13 | The package contains database, encrypted artifacts, vault material, and encrypted recovery data without plaintext private keys. | VERIFIED | Package layout and content tests inspect the ZIP and prove the known private value is absent. |
| 14 | Uploaded backups are authenticated, safely extracted, and staged only in a new sibling directory. | VERIFIED | Tests cover valid staging, hash tampering, traversal, unexpected layout, wrong passphrase, existing destination, and declared archive bombs. |
| 15 | Restore never overwrites or switches active data while CertMon is running. | VERIFIED | The service publishes only a new sibling directory; tests compare active files before and after and UI code performs no location switch. |
| 16 | The UI distinguishes full server backup from Local CA backup and explains offline activation. | PRESENT_BEHAVIOR_UNVERIFIED | Separate controls and activation-step rendering pass contract tests; actual operator presentation needs UAT. |
| 17 | Backup operations are permission-gated, CSRF-protected, bounded, cleaned up, and audited without secrets. | VERIFIED | API tests cover role denial before processing, CSRF, streamed limits, temporary cleanup, audit redaction, and deterministic status responses. |

**Score:** 14/17 truths verified; 3 present and wired behaviors require human verification.

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| Server-mode configuration, authentication, RBAC, CSRF, audit, and trust bundle | EXISTS + SUBSTANTIVE | Original Phase 02 implementation remains covered by its focused suites and prior UAT. |
| Database and `AuthService` user-management methods | EXISTS + SUBSTANTIVE | Transactional mutation, validation, final-admin protection, and session revocation are implemented. |
| Permission-gated `/api/users` endpoints | EXISTS + SUBSTANTIVE | List, create, update, enable/disable, and password reset routes are authorized and audited. |
| Administration user controls | EXISTS + WIRED | Admin-only tab loads supported roles and invokes every user-management endpoint. |
| `MANAGE_SERVER_BACKUP` and `ServerBackupPackageService` | EXISTS + SUBSTANTIVE | Permission mapping, versioned package export, safe validation, and staged restore are implemented. |
| Server backup API and Administration controls | EXISTS + WIRED | Export and restore routes are connected to confirmed UI forms and display staging instructions. |

**Artifacts:** 6/6 verified.

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| Administration user UI | `/api/users` routes | authenticated fetch with global CSRF injection | WIRED |
| User routes | `AuthService` and database | `MANAGE_USERS`, validation, transactions, and audit helper | WIRED |
| Security-sensitive user mutation | active sessions | transactional `DELETE FROM sessions WHERE user_id=?` | WIRED |
| Server backup UI | export and restore routes | confirmed passphrase forms and multipart upload | WIRED |
| Server backup routes | package service | `MANAGE_SERVER_BACKUP`, upload bound, audit, and temporary cleanup | WIRED |
| Package service | `BackupService` and `Vault` | authenticated manifest plus encrypted recovery package and reprotection | WIRED |

**Wiring:** 6/6 connections verified.

## Requirements Coverage

No separate requirement identifiers are mapped to these plans. Coverage is represented by all 17 plan must-haves above.

## Anti-Patterns Found

No blockers, stubs, placeholder implementations, or secret-bearing audit responses were found in the gap-closure scope.

## Human Verification Required

### 1. Authentication Form Polish
**Test:** With a fresh server data directory, try mismatched first-admin passwords, then matching passwords; later sign in by pressing Enter.
**Expected:** Mismatch prevents the request, matching setup succeeds, and Enter submits login exactly once.
**Why human:** Browser keyboard and rendered validation behavior are not exercised by the HTML contract tests.

### 2. Administration User Lifecycle
**Test:** As admin, create a viewer, verify restricted access, change its roles, disable and enable it, and reset its password.
**Expected:** UI actions succeed, unsupported privilege is denied, and old sessions/passwords stop working after security changes.
**Why human:** Service and API behavior are automated; the complete browser workflow is not.

### 3. Full Server Backup And Staged Recovery
**Test:** Export a full backup and stage it using a temporary server data directory.
**Expected:** A new sibling restore directory appears, active data remains unchanged, and the UI displays explicit stop, switch, and rollback instructions.
**Why human:** Package safety is automated, while operator-facing clarity and the rendered staging result require human review.

## Gaps Summary

**No implementation gaps found.** Automated verification passes; three focused human checks remain before Phase 02 can be marked complete.

## Verification Metadata

**Verification approach:** Goal-backward manual verification against code, tests, plan must-haves, and prior UAT.
**Must-haves source:** `02-01-PLAN.md`, `02-02-PLAN.md`, and `02-03-PLAN.md` frontmatter.
**Automated checks:** 265 passed, 1 ACME staging test deselected in the latest full regression run.
**Human checks required:** 3.

---
*Verified: 2026-08-21*
*Verifier: Codex main session, user-authorized manual fallback*
