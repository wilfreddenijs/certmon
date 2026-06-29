# Phase 3: Toolbelt auto-upload UI with device progress and cancellation - Context

**Gathered:** 2026-06-29
**Status:** Ready for planning

<domain>

## Phase Boundary

This phase adds a Windows desktop Toolbelt batch-upload workflow to CertMon: it shows the `devices.txt`-derived target list, performs automatic background dry-runs, allows explicit real upload for eligible selected devices, shows progress, supports safe stop-after-current-device cancellation, and persists the latest per-device dry-run/upload result.

</domain>

<spec_lock>

## Requirements (locked via SPEC.md)

**7 requirements are locked.** See `03-SPEC.md` for full requirements, boundaries, and acceptance criteria.

Downstream agents MUST read `03-SPEC.md` before planning or implementing. Requirements are not duplicated here.

**In scope (from SPEC.md):**

- Windows desktop/single-user Toolbelt integration.
- UI panel/dialog for the `devices.txt` Toolbelt target list.
- Automatic background dry-run/reachability/targetability check.
- Real upload action for selected devices only.
- Per-device progress display during dry-run and upload.
- Safe “stop after current device” cancellation.
- Persisting latest per-device dry-run/upload status.
- Clear user-facing explanation of which list is used and what dry-run vs upload means.

**Out of scope (from SPEC.md):**

- Server-mode/multi-user roles and permissions — handled by Phase 02.
- Browser-based private-key delivery beyond existing explicit download/security boundaries.
- Replacing Extron Toolbelt with a custom protocol implementation — Toolbelt remains the automation target.
- Upload support for non-Extron devices — this phase is Extron/Toolbelt-specific.
- Full historical audit log of every run — this phase stores latest per-device status only.
- Force-aborting Toolbelt mid-device — cancellation is safe stop-after-current-device only.
- Automatic upload without user confirmation — real upload always requires explicit action.

</spec_lock>

<decisions>

## Implementation Decisions

### Toolbelt integration shape

- **D-01:** CertMon should invoke the existing `toolbelt_uploader.py` as a background CLI/subprocess for this phase.
- **D-02:** The standalone Toolbelt uploader remains the source of truth for interacting with Extron Toolbelt. Do not do a broad refactor into an importable Python service in this phase.
- **D-03:** Planning should add a machine-readable progress/result channel around the CLI path, such as JSON-lines output, a status file, or another subprocess-readable stream. This is required so the UI can show live per-device state without scraping human log text as the primary interface.

### Device list UX

- **D-04:** The UI must be device-oriented, not certificate-oriented. The user wants to see “which devices can be uploaded?” rather than only “which certificates exist?”
- **D-05:** The list should include all relevant Toolbelt upload targets derived from `devices.txt` / Local CA Extron certificates.
- **D-06:** For each device row, show at minimum: device name/IP/host, whether a Local CA Extron certificate exists, the linked certificate identity, whether the device is selected for upload, dry-run status, and latest upload status.
- **D-07:** The UI may live as a distinct Toolbelt batch section in the Upload tab, but it must clearly explain that the list is based on CertMon’s `devices.txt` device/certificate mapping.

### Dry-run gating

- **D-08:** Devices whose background dry-run fails must not be directly uploadable.
- **D-09:** Failed dry-run rows should show a clear failure reason and offer `Retry dry-run`.
- **D-10:** Real upload becomes available only after a device has a successful dry-run status.
- **D-11:** This strict gating is intentional: avoid “try anyway” behavior against Toolbelt/devices when reachability or targeting is already known to be bad.

### Credentials and Toolbelt prompts

- **D-12:** CertMon should support per-device login/password credentials and store them encrypted.
- **D-13:** First credential attempt should default to username `admin`, password `extron`.
- **D-14:** Second suggested credential attempt should be username `admin`, password equal to the device serial number.
- **D-15:** If the default and serial-number attempts fail, the UI should prompt for custom credentials for that device and allow saving them encrypted for future dry-runs/uploads.
- **D-16:** The first Toolbelt run should check whether the serial number is visible/available in Toolbelt’s discovered-devices overview. If the “Serial number / Serienummer” column is not visible, the user should receive clear instructions to enable that column in Toolbelt.
- **D-17:** Serial numbers may be used as a suggested password option but must not be exposed as secrets in persistent logs or unnecessarily echoed in UI output.

### the agent's Discretion

- Progress detail level was not explicitly discussed. Default to a user-friendly device progress dialog with concise status per device and optional expandable log details for troubleshooting.
- Exact transport for progress data is left to planning, with the constraint that it must be machine-readable and robust enough for UI polling.

</decisions>

<canonical_refs>

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Locked requirements

- `.planning/phases/certmon-03-toolbelt-auto-upload-ui-with-device-progress-and-cancellatio/03-SPEC.md` — Locked Phase 03 requirements, boundaries, constraints, and acceptance criteria.

### Project planning context

- `.planning/PROJECT.md` — Project-level locked decisions, especially local/single-user default and private-key safety.
- `.planning/REQUIREMENTS.md` — Current and future security requirements; server-mode is out of scope for Phase 03.
- `.planning/ROADMAP.md` — Phase ordering and Phase 03 goal.
- `.planning/STATE.md` — Planning state and prior phase notes.

### Existing implementation references

- `toolbelt_uploader.py` — Existing standalone Extron Toolbelt automation CLI; process/list parsing, dry-run/commit modes, Toolbelt detection, and upload behavior live here.
- `app.py` — Existing Flask routes for `/api/ca/devices-txt`, `/api/ca/issued`, `/api/upload/devices`, `/api/upload/push`, and upload-device persistence.
- `templates/index.html` — Existing Upload tab, Local CA issued certificate UI, `devices.txt` download link, and current deployment result UI.
- `certmon/deployment.py` — Existing server-side deployment abstractions and Extron deployment/manual fallback behavior.
- `certmon/artifacts.py` — Encrypted artifact store and private material boundaries.
- `certmon/vault.py` — Encrypted secret storage used for sensitive material.

</canonical_refs>

<code_context>

## Existing Code Insights

### Reusable Assets

- `toolbelt_uploader.py`: Already supports `--list`, `--device`, `--commit`, `--force`, `--device-password`, dry-run by omission of `--commit`, per-device try/except, Toolbelt detection, reconnect/retry, and summary logging.
- `/api/ca/devices-txt` in `app.py`: Existing source of `selector,certificate_id` mappings for Local CA device certificates.
- `/api/ca/issued` in `app.py`: Existing Local CA certificate list can help build the richer device-oriented UI.
- Upload tab in `templates/index.html`: Existing layout, device list cards, certificate selector, push result panel, and connection test patterns can be reused.
- Existing JSON state via `load_data()` / `save_data()`: Candidate storage location for persisted latest per-device Toolbelt dry-run/upload status if planning decides that is sufficient.
- `Vault` / encrypted storage patterns: Existing secure storage should be reused or extended for per-device credentials.

### Established Patterns

- The UI is currently a single HTML template with vanilla JavaScript fetch calls and rendered sections.
- Long-running scan progress already uses polling (`/api/scan/progress`) and a progress bar; Toolbelt progress can follow a similar polling model.
- Sensitive deployment routes use server-side certificate IDs and avoid sending private PEM through browser request bodies.
- Deployment fallback is explicit/manual for unsupported devices; this phase should preserve clear “manual vs automatic” wording.

### Integration Points

- Add Toolbelt batch UI under the existing Upload tab, likely near stored certificates/manual deployment.
- Add backend routes for Toolbelt target list, dry-run status, upload start/status/cancel, and per-device credential updates.
- Extend or wrap `toolbelt_uploader.py` so the backend can receive machine-readable per-device progress.
- Persist latest per-device status in CertMon data/database with enough identifiers to survive restart and correlate with device/certificate mappings.
- Reuse explicit private-material handling: materialize Extron combined PEM server-side/locally for Toolbelt as needed, never as silent browser state.

</code_context>

<specifics>

## Specific Ideas

- The user wants the Toolbelt batch list to be visibly tied to `devices.txt`, not hidden behind an abstract “upload all” button.
- The user wants the list to show whether a Local CA certificate exists for each relevant device and whether that device is selected for upload.
- Background dry-run should start automatically so the operator immediately sees which devices are actually uploadable.
- Credential fallback order should reflect common Extron practice: `admin` / `extron` first, then `admin` / serial number, then custom per-device credentials.
- Toolbelt’s discovered-device serial-number column may need to be enabled by the operator; the first-run flow should detect/instruct around that.

</specifics>

<deferred>

## Deferred Ideas

- Full historical run/audit log — deferred; this phase only stores latest per-device status.
- Server-mode/multi-user authorization around Toolbelt upload — deferred to Phase 02/server-mode work.
- Non-Extron automatic deployment adapters — separate future phase.
- Refactoring `toolbelt_uploader.py` into a fully importable service — explicitly not part of this phase unless planning finds a minimal shared helper is necessary.

</deferred>

---

*Phase: 3-Toolbelt auto-upload UI with device progress and cancellation*
*Context gathered: 2026-06-29*
