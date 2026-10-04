---
phase: "02-shared-server-mode"
plan: "02-03"
subsystem: "Full server backup and staged recovery"
tags: [backup, recovery, security, rbac, administration]
requires:
  - phase: "02-01"
    provides: "Server mode authentication, permissions, CSRF protection, encrypted storage, and audit logging"
  - phase: "02-02"
    provides: "Administrator and security-administrator role workflows"
provides:
  - "Versioned authenticated full-server backup ZIP with encrypted recovery material"
  - "Archive-safe staged restore into a new inactive sibling directory"
  - "Permission-gated, bounded, audited export and restore APIs"
  - "Administration UI and rollback-safe Windows activation guidance"
affects: [server-mode, administration, disaster-recovery, windows-deployment]
tech-stack:
  added: []
  patterns:
    - "Validate every ZIP member before extraction and publish restores only after full verification"
    - "Authorize sensitive routes before parsing passphrases or multipart uploads"
    - "Bind temporary download cleanup to the response transfer iterator"
key-files:
  created:
    - "certmon/server_backup.py"
    - "tests/test_server_backup_package.py"
    - "tests/test_server_backup_api.py"
  modified:
    - "app.py"
    - "certmon/backup.py"
    - "certmon/config.py"
    - "certmon/permissions.py"
    - "templates/index.html"
    - "README.md"
    - "tests/test_ui_contract.py"
key-decisions:
  - "Full server backup is restricted to security_admin and admin and remains separate from Local CA backup."
  - "Restore always targets a new sibling directory and requires an offline operator-controlled activation."
  - "The recovery package is embedded encrypted and used unchanged for manifest authentication and vault reprotection."
requirements-completed: []
coverage:
  - id: D1
    description: "Portable package layout, archive validation, integrity verification, and vault reprotection"
    verification:
      - kind: integration
        ref: "tests/test_backup.py tests/test_server_backup_package.py tests/test_server_backup_recovery.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Permission-gated, CSRF-protected, bounded, audited server backup APIs"
    verification:
      - kind: integration
        ref: "tests/test_server_backup_api.py tests/test_csrf.py tests/test_audit_api.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Administration controls and rollback-safe recovery documentation"
    verification:
      - kind: automated_ui
        ref: "tests/test_ui_contract.py"
        status: pass
    human_judgment: true
    rationale: "UI contracts and JavaScript syntax are automated; final browser appearance remains suitable for UAT."
duration: "32min"
completed: "2026-08-20"
status: complete
---

# Phase 02 Plan 03: Full Server Backup And Staged Recovery Summary

**Authenticated full-server backup packages with hostile-archive validation, account-bound vault recovery, and offline-only activation of staged restores**

## Performance

- **Duration:** 32 min
- **Completed:** 2026-08-20
- **Tasks:** 3
- **Files modified:** 10

## Accomplishments

- Added a versioned ZIP package around `BackupService` containing the database, encrypted artifacts and vault files, an encrypted recovery package, and operator notes without plaintext private material.
- Added pre-extraction path, link, duplicate, member-count, layout, and uncompressed-size validation followed by authenticated restore and current-account vault reprotection.
- Added permission-gated export and streamed restore APIs with CSRF enforcement, upload limits, redacted audits, deterministic status codes, and temporary-file cleanup.
- Added full-server backup controls for Admin and Security Admin users while retaining Admin-only user management and separate Local CA backup controls.
- Documented secure package handling and rollback-safe offline activation on Windows.

## Task Commits

1. **Task 1: Add a portable, versioned server-backup package service** - `5e11d30`
2. **Task 2: Add permission-gated export and staged-restore APIs** - `7898448`
3. **Task 3: Add Server backup controls and recovery documentation** - `85c57d6`

## Verification

- `py -3 -m pytest tests/test_backup.py tests/test_server_backup_package.py tests/test_server_backup_api.py tests/test_server_backup_recovery.py tests/test_csrf.py tests/test_audit_api.py tests/test_ui_contract.py -q` - 62 passed.
- `py -3 -m compileall app.py certmon` - passed.
- Embedded JavaScript syntax check with Node - passed.
- Acceptance grep confirmed distinct full-server and Local CA controls, matching passphrase confirmation, staged-path rendering, activation steps, rollback instructions, and package sensitivity guidance.
- `py -3 -m pytest -m "not acme_staging" -q --basetemp .tmp\pytest-execute-02-rerun -p no:cacheprovider` - 265 passed, 1 deselected after the launcher regression fix.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Closed SQLite backup connections explicitly**
- **Found during:** Task 1
- **Issue:** Python's SQLite connection context committed but did not close the backup destination, preventing required temporary-directory cleanup on Windows.
- **Fix:** Wrapped source and destination connections with `contextlib.closing` in `BackupService._backup_database()`.
- **Files modified:** `certmon/backup.py`
- **Verification:** Task 1 package suite passes and temporary backup directories are removed.
- **Commit:** `5e11d30`

**2. [Rule 1 - Bug] Bound download cleanup to the transfer iterator**
- **Found during:** Task 2
- **Issue:** Flask test response wrapping did not preserve a plain `call_on_close` cleanup callback, leaving the temporary download directory behind.
- **Fix:** Wrapped the response iterable with Werkzeug `ClosingIterator` and added explicit cleanup regression coverage.
- **Files modified:** `app.py`, `tests/test_server_backup_api.py`
- **Verification:** API suite proves both export and upload temporary paths are removed.
- **Commit:** `7898448`

**3. [Rule 1 - Bug] Preserved the backup upload limit in desktop launcher runtime reconstruction**
- **Found during:** Phase regression gate
- **Issue:** Desktop mode rebuilt `RuntimeConfig` with a free loopback port but omitted the newly required `max_backup_upload_bytes` field.
- **Fix:** Copied the resolved limit into the rebuilt runtime and added a launcher regression assertion.
- **Files modified:** `launcher.py`, `tests/test_launcher_config.py`
- **Verification:** The complete non-staging suite passes with 265 tests.
- **Commit:** `6afd584`

**Total deviations:** 3 auto-fixed bugs. **Impact:** The fixes enforce planned cleanup behavior and preserve desktop startup without expanding feature scope.

## Known Stubs

None. Empty UI values clear passphrases after use, and empty collections in tests assert rejected destinations remain untouched.

## Issues Encountered

None beyond the auto-fixed Windows cleanup issues above.

## User Setup Required

None. `CERTMON_MAX_BACKUP_UPLOAD_MB` is optional and defaults to 512 MiB.

## Next Phase Readiness

Phase 02 gap closure is implementation-complete. Full server backup and staged recovery are ready for focused browser UAT and a Windows service-account migration rehearsal.

## Self-Check: PASSED

- Created files exist: `certmon/server_backup.py`, `tests/test_server_backup_package.py`, and `tests/test_server_backup_api.py`.
- Task commits exist: `5e11d30`, `7898448`, and `85c57d6`.
- No unexpected deletions or untracked generated files were found.

---
*Phase: 02-shared-server-mode*
*Completed: 2026-08-20*
