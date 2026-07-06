---
phase: "04"
plan: "04-01"
subsystem: "Extron workflow UI"
tags: [ui, local-ca, toolbelt, upload]
key-files:
  modified:
    - "templates/index.html"
    - "app.py"
    - "tests/test_ui_contract.py"
    - "tests/test_ca_api.py"
requirements-completed:
  - "REQ-04-01"
  - "REQ-04-02"
  - "REQ-04-03"
  - "REQ-04-04"
  - "REQ-04-05"
  - "REQ-04-06"
  - "REQ-04-07"
  - "REQ-04-08"
completed: "2026-07-02"
---

# Phase 04 Plan 01 Summary: Device-first Extron Local CA and Upload Workflow

## What Changed

- Renamed the first visible navigation tab to Devices and made scanned devices the workflow starting point.
- Added Extron-only Local CA actions on scanned device rows.
- Added a device Local CA dialog that defaults to the `extron-rsa` certificate profile, creates the leaf certificate through the existing Local CA API, and refreshes the Upload list.
- Added a `Local CA ready` path for devices that already have a matching Local CA certificate, with `Use existing` and `Issue new` options.
- Moved the Upload tab's primary content to a single prepared-device Toolbelt list and added an `Add device` jump back to Devices.
- Collapsed the older manual upload form behind a Manual upload fallback details section.
- Added removal from the prepared Upload list by deleting the associated Local CA device certificate.
- Kept the Local CA tab focused on root CA management at runtime.

## Verification

- `py -3 -m pytest tests/test_ui_contract.py tests/test_ca_api.py tests/test_toolbelt_api.py -q --basetemp .tmp\pytest -p no:cacheprovider` - 29 passed
- `py -3 -m pytest tests/test_ui_contract.py tests/test_ca_api.py tests/test_toolbelt_api.py tests/test_toolbelt_service.py tests/test_deployment.py -q --basetemp .tmp\pytest -p no:cacheprovider` - 51 passed
- `py -3 -m compileall app.py launcher.py toolbelt_uploader.py certmon tests`
- `git diff --check`

## Deviations

- The internal `certs` tab id was kept to avoid a broad JavaScript migration; the user-facing label is now Devices.
- Some older Local CA issue-form template variables remain in JavaScript but are no longer rendered by the Local CA tab. Runtime behavior is root-management only.
- Manual browser UAT was not run in this environment; the implemented contract is covered by static UI and API tests.

## Commits

- `62996d7 feat(04-01): simplify Extron upload workflow`

## Self-Check

PASSED.
