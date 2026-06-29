---
phase: "03-toolbelt-auto-upload-ui-with-device-progress-and-cancellation"
plan: "03-01"
subsystem: "Toolbelt batch upload"
tags:
  - toolbelt
  - upload
  - local-ca
  - extron
key-files:
  created:
    - "certmon/toolbelt.py"
    - "tests/test_toolbelt_api.py"
    - "tests/test_toolbelt_service.py"
  modified:
    - "toolbelt_uploader.py"
    - "app.py"
    - "templates/index.html"
    - "README.md"
    - "tests/test_ui_contract.py"
    - "certmon/renewals.py"
requirements-completed:
  - "SPEC-R1 desktop-first Toolbelt flow"
  - "SPEC-R2 devices.txt primary source"
  - "SPEC-R3 visible selectable device list"
  - "SPEC-R4 automatic background dry-run"
  - "SPEC-R5 explicit real upload"
  - "SPEC-R6 safe cancellation"
  - "SPEC-R7 persist latest per-device result"
  - "D-01 CLI/subprocess Toolbelt integration"
  - "D-03 machine-readable progress/result channel"
  - "D-08 failed dry-run blocks upload"
  - "D-12 encrypted per-device credentials"
completed: "2026-06-29"
---

# Phase 03 Plan 01 Summary: Toolbelt auto-upload UI

Implemented a first vertical Toolbelt batch upload flow for Extron Local CA certificates.

## What Changed

- Added `certmon/toolbelt.py`, a server-side Toolbelt batch service.
- Added `/api/toolbelt/*` routes for device list, selection, dry-run, upload, run polling, stop-after-current-device, and encrypted credentials.
- Extended `toolbelt_uploader.py` with:
  - `--jsonl` machine-readable progress events;
  - `--stop-file` safe cancellation between devices;
  - `--device-password-file` so credentials do not appear on the command line;
  - dry-run events without `--commit` and upload events with `--commit`.
- Added a Toolbelt batch section in the Upload tab:
  - visible device list from CertMon `devices.txt` / Local CA Extron mapping;
  - automatic safe dry-run when opening Upload;
  - selected-device upload only after dry-run OK;
  - per-device dry-run/upload status;
  - stop-after-current-device control;
  - encrypted per-device credential prompt.
- Documented first-run Toolbelt requirements and UAT steps in `README.md`.

## Security Notes

- Private Extron combined PEM material is materialized only server-side in a temporary run directory and removed after run completion/failure/stop cleanup.
- Toolbelt credentials are encrypted through the existing vault/database secret path.
- Browser APIs use selectors and certificate IDs only; private PEM material is rejected in Toolbelt request bodies.
- Upload is blocked until a selected device has a latest dry-run OK result.

## Verification

Passed:

```powershell
py -3 -m pytest tests/test_toolbelt_service.py tests/test_toolbelt_api.py tests/test_ui_contract.py -q --basetemp .tmp\pytest -p no:cacheprovider
# 21 passed

py -3 -m pytest tests/test_toolbelt_service.py tests/test_toolbelt_api.py tests/test_ui_contract.py tests/test_ca_api.py tests/test_deployment.py tests/test_db.py tests/test_vault.py -q --basetemp .tmp\pytest -p no:cacheprovider
# 43 passed

py -3 -m pytest -m "not acme_staging" -q --basetemp .tmp\pytest -p no:cacheprovider
# 148 passed, 1 deselected

py -3 -m compileall app.py launcher.py toolbelt_uploader.py certmon tests
```

## Deviations from Plan

- `certmon/db.py` and `certmon/vault.py` did not need code changes; the service reuses existing settings/secrets APIs.
- `tests/test_toolbelt_uploader.py` was not added; the JSONL/subprocess behavior is covered through `tests/test_toolbelt_service.py`, and UI/API coverage is in `tests/test_toolbelt_api.py` and `tests/test_ui_contract.py`.
- Automatic serial-number password discovery is not complete in this slice. The UI and README instruct the operator to enable/check the serial-number column in Toolbelt and save that value as encrypted per-device credentials when needed.
- Real Extron Toolbelt/device UAT is still required because CI cannot prove Windows GUI automation against a physical Extron device.

## Next Phase Readiness

Ready for build and Windows UAT on real Toolbelt/Extron hardware.

## Self-Check: PASSED
