# Phase 05: Direct Extron Certificate Upload - Pattern Map

**Mapped:** 2026-10-04  
**Files classified:** 10 (implementation names for the new transport are tentative)  
**Analogs found:** 9 / 10

## File Classification

| New/modified file | Role | Data flow | Closest analog | Match |
|---|---|---|---|---|
| `certmon/direct_extron.py` (new; name TBD) | service | batch, request-response | `certmon/toolbelt.py` | exact behavior, transport differs |
| `certmon/toolbelt.py` | service | batch | itself | replacement/retirement boundary |
| `app.py` | route/controller | request-response | `app.py:1977-2103` | exact |
| `templates/index.html` | component/UI | event-driven, polling | `templates/index.html:1030-1055,3138-3305` | exact |
| `certmon/deployment.py` | service/utility | request-response | `certmon/deployment.py:83-174,404-435` | exact verification |
| `requirements.txt` | config | dependency | none | add `paramiko==5.0.0` |
| `tests/test_direct_extron.py` (new; name TBD) | test | batch, file-I/O | `tests/test_toolbelt_service.py` | role-match |
| `tests/test_toolbelt_api.py` | test | request-response | itself | route replacement |
| `tests/test_deployment.py` | test | request-response | itself | exact verification/security |
| `tests/test_ui_contract.py` | test | event-driven | itself | exact UI contract |

## Pattern Assignments

### `certmon/direct_extron.py` (service, batch/file-I/O)
**Analog:** `certmon/toolbelt.py`.
Copy the run DTO/lock/thread/status shape at lines 27-72 and `start()` validation/thread launch at 148-185. Preserve server-only combined-PEM handling and cleanup:
```python
temp_dir = Path(tempfile.mkdtemp(prefix=f"certmon-toolbelt-{run.id}-"))
try:
    with self.artifacts.materialize_private(certificate_id, "combined.pem") as materialized:
        shutil.copy2(materialized, pem_path)
    self._record_device_event(run, {"event": "device_pending", ...})
finally:
    shutil.rmtree(temp_dir, ignore_errors=True)
```
From lines 360-390, return sanitized per-device events and persist latest status keyed by selector/certificate/mode. Model `probe` separately from `activate`: probe must not materialize PEM, open SFTP, or send SIS import. For activate, only mark `*_ok` after SFTP, exact SIS acknowledgement (`CertV x1` per screenshot), and HTTPS fingerprint verification. On SIS timeout/disconnect, do not retry; surface indeterminate then verify.

### `app.py` (routes, request-response)
**Analog:** `app.py:1977-2103`. Retain `authorize(Permission.DEPLOY_CERTIFICATE)`, unavailable `503`, JSON validation, `ValueError -> 400`, audit event, run GET, and stop POST. Copy the private-material rejection at 2045-2080:
```python
if any(key in body for key in ("private_key_pem", "combined_pem", "pem")):
    return jsonify({"error": "Private certificate material must stay server-side"}), 400
```
Use `app.py:256-301` global server-mode CSRF middleware; do not add per-route CSRF. Audit success/failure like `app.py:2372-2387`, but audit only IDs/interface/state, never host-key, password, PEM, or raw SIS sensitive data.

### `templates/index.html` (UI, event-driven)
**Analog:** prepared upload panel `templates/index.html:1030-1055`, state/polling `3138-3162`, renderer `3171+`. Preserve one central list, per-row selection/credentials/status, explicit test and explicit activation buttons, and stop-after-current-device. Replace Toolbelt wording/endpoints; add per-device LAN A default / LAN B choice. Do not auto-start probe (`test_ui_contract.py:433-464`); connectivity testing must communicate no import/activation.

### `certmon/deployment.py` (verification utility)
**Analog:** `verify_device_certificate`, lines 404-430. Pass the chosen interface's HTTPS host/port in the device/target; preserve `unreachable`, `different_certificate`, and SHA-256 DER comparison. Copy service result gate at 127-173: transfer/import is pending/failure unless `verification.status == "verified"`.

### Vault, RBAC, and audit (cross-cutting)
**Vault analog:** `certmon/toolbelt.py:121-146,428-437`; encrypt JSON credentials with a dedicated purpose and store metadata limited to selector/username. `certmon/vault.py:109-180` is the primitive. No secret fields in `list_devices()` (`toolbelt.py:74-108`).

**Authorization analog:** `certmon/permissions.py:9-55,73-96` and all existing Toolbelt routes. Use only `DEPLOY_CERTIFICATE`; preserve global CSRF. Audit redaction is asserted by `tests/test_audit_api.py:88-99`.

## Tests and Verification Patterns

- Copy fake service injection/API assertions from `tests/test_toolbelt_api.py:10-150`: safe list, route payload, start/stop, no password/private-key response.
- Copy async fake transport/cleanup test from `tests/test_toolbelt_service.py:81-118`; add fake Paramiko cases: unknown key rejected before auth/SFTP, SFTP-only fails, exact SIS reply required, staged-file cleanup, cancellation, and no automatic replay after ambiguous import.
- Copy fingerprint pending/unreachable assertions from `tests/test_deployment.py:253-379`: matching, mismatch, unreachable, selected LAN B endpoint.
- Keep regression boundaries from `tests/test_deployment.py:25-111`, `tests/test_rbac.py:154-173`, `tests/test_csrf.py:18-74`, and `tests/test_ui_contract.py:184-199`.
- Physical deployment verification has **no code analog**: test one-LAN and two-LAN devices, record model/firmware, enrolled host key, safe SIS evidence, selected HTTPS endpoint, and fingerprint before Toolbelt retirement.

## Uncertainties

- New direct-service/module and endpoint names are planner choices; existing `ToolbeltBatchService` is the replacement analog.
- Do not assume serial fallback, host-key enrollment persistence, encrypted-PEM passphrase framing, remote cleanup permission, LAN B address, or model/firmware compatibility. Screenshot requires ESC and CR control bytes; use `Esc I x1 * <filename> CERT \r` (passphrase variant includes `<passphrase>`) and verify on hardware.

## Metadata
**Search scope:** `certmon/`, `app.py`, `templates/`, `tests/`, `docs/`, requirements.  
**Concrete analogs read:** deployment, Toolbelt service, routes, permissions/vault, UI, API/service/RBAC/CSRF/audit tests.
