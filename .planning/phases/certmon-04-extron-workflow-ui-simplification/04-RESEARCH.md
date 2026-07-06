---
phase: "04"
name: "Extron workflow/UI simplification"
created: 2026-07-01
status: complete
---

# Phase 04 Research: Extron Workflow/UI Simplification

## Research Summary

CertMon already has most lower-level primitives needed for this phase. The safest implementation path is a UI/workflow restructuring with small API adapters, not a rewrite of certificate issuance or Toolbelt automation.

## Existing Assets

- `templates/index.html` is the single-page UI. The first tab is currently `Certificates` using `tab-certs`; the Upload and Local CA flows are also implemented here with inline JavaScript.
- `app.py` exposes Local CA issuance/deletion, certificate download, upload-device CRUD, and Toolbelt routes.
- `certmon/local_ca.py` issues Local CA leaf certificates and stores `profile`, `device_name`, `identifiers`, and private `combined.pem`.
- `certmon/toolbelt.py` derives Toolbelt devices from stored Local CA leaf certificates where `profile == "extron-rsa"` and a certificate artifact exists.
- `certmon/profiles.py` already defines `extron-rsa` and profile recommendation behavior.
- Existing focused tests cover UI contract strings, Toolbelt service/API behavior, Local CA issued certificate deletion/download, deployment, and profile behavior.

## Recommended Approach

1. Keep `certmon/local_ca.py` and `ToolbeltBatchService` behavior intact.
2. Treat scanned certificates/devices as the source UI list and rename the first tab to Devices while preserving existing scan data loading.
3. Add a Devices-tab Local CA preparation dialog that can create an Extron-compatible Local CA certificate and keep the user on Devices.
4. Make Upload the single prepared-device list by rendering `/api/toolbelt/devices` as the primary automatic upload list and moving legacy manual push UI into a collapsed fallback.
5. Add a small API adapter only if needed to delete an Upload-list Local CA certificate by certificate id/selector, reusing the existing `/api/ca/issued/<certificate_id>` deletion semantics.
6. Extend contract and API tests before implementation to pin the new workflow labels, deletion confirmation, and fallback placement.

## Risks

- `templates/index.html` is large and stateful; changes should be made in small sections with contract tests guarding expected strings and function names.
- The old `upload_devices` manual push list and the new Toolbelt certificate-derived list can confuse users if both remain visually primary.
- Removing a prepared device must delete the certificate artifact and database metadata without deleting the scanned certificate/device entry.
- Extron readiness must remain tied to `profile == "extron-rsa"` and private server-side artifacts; no private key material should move into browser state.

## Verification Targets

- `pytest tests/test_ui_contract.py`
- `pytest tests/test_ca_api.py tests/test_toolbelt_api.py tests/test_toolbelt_service.py`
- A focused manual browser pass through: scan/device card -> Local CA modal -> create/add -> Upload list -> dry-run/upload controls -> remove confirmation.

## RESEARCH COMPLETE
