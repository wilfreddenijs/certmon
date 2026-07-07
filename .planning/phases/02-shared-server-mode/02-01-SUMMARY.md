---
phase: "02-shared-server-mode"
plan: "02-01"
subsystem: "Shared server mode"
tags: [server-mode, auth, csrf, rbac, audit, local-ca, backup]
key-files:
  created:
    - "certmon/auth.py"
    - "certmon/audit.py"
    - "certmon/csrf.py"
    - "tests/test_auth_api.py"
    - "tests/test_audit_api.py"
    - "tests/test_csrf.py"
    - "tests/test_local_ca_server_mode.py"
    - "tests/test_rbac.py"
    - "tests/test_server_backup_recovery.py"
    - "tests/test_server_mode_config.py"
  modified:
    - "app.py"
    - "certmon/config.py"
    - "certmon/db.py"
    - "certmon/permissions.py"
    - "templates/index.html"
    - "README.md"
    - ".gitignore"
requirements-completed:
  - "server-mode configuration"
  - "local user authentication"
  - "role-based authorization"
  - "CSRF protection"
  - "user-aware audit log"
  - "Local CA public trust bundle export"
completed: "2026-07-07"
---

# Phase 02 Plan 01 Summary: Shared Server Mode and Team Local CA

## What Changed

- Added explicit server-mode configuration. Desktop mode remains loopback-only by default; LAN binding requires `CERTMON_SERVER_MODE=1`.
- Added local users, first-admin setup, login/logout, HttpOnly session cookies, and current-user UI.
- Added server-mode CSRF protection for mutating requests with automatic UI header injection.
- Added role-based permissions for viewer, operator, CA admin, security admin, and admin.
- Added user-aware audit storage, audit API, and Audit tab. Sensitive details are redacted.
- Added public Local CA trust bundle ZIP export and hardened Local CA private-key/backup operations behind permissions.
- Added backup/recovery tests proving server auth/session/audit metadata is preserved.
- Added deterministic 409 conflict handling for stale renewal updates.
- Updated README with shared server mode, roles, audit, trust bundle, and backup notes.
- Ignored generated `.tmp/`, `build/`, and `dist/` output folders.

## Verification

- `py -3 -m pytest -m "not acme_staging" -q --basetemp .tmp\pytest -p no:cacheprovider` - 220 passed, 1 deselected.
- `py -3 -m compileall app.py launcher.py toolbelt_uploader.py certmon tests` - passed.
- `.\\build.bat` - dependency install succeeded but the batch failed because `pyinstaller` is not on this shell's `PATH`.
- `py -3 -m PyInstaller certmon.spec --clean --noconfirm` - passed; produced `dist\CertMon.exe` at 30,092,077 bytes.

## Deviations

- Local build was completed via `py -3 -m PyInstaller` instead of the `pyinstaller` command shim used by `build.bat`, because the shim is not on `PATH` in this environment.
- LAN UAT from a second machine/browser was not performed in this environment and should be covered by `$gsd-verify-work 02 --text`.

## Commits

- `63a0a9d` - server mode safety gate.
- `75cb933` - local users and sessions.
- `d4ef470` - server-mode CSRF.
- `8c1ccce` - role-based permissions.
- `254470b` - user-aware audit log.
- `be5af11` - Local CA trust bundle.
- `e990d6a` - server-mode backup metadata coverage.
- `183d509` - stale renewal conflict handling.
- `d95ea69` - shared server mode documentation.

## Self-Check

PASSED.
