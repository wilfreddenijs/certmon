# Phase 3: Toolbelt auto-upload UI with device progress and cancellation — Specification

**Created:** 2026-06-28
**Ambiguity score:** 0.15 (gate: ≤ 0.20)
**Requirements:** 7 locked

## Goal

CertMon adds a Windows desktop UI flow that uses the existing `devices.txt` Local CA device list to automatically dry-run and then optionally upload Extron PEM certificates through Extron Toolbelt, while showing per-device status, progress, cancellation, and saved last-result outcomes.

## Background

CertMon currently has:

- a standalone `toolbelt_uploader.py` that can process a `devices.txt` list and drive Extron Toolbelt;
- a Local CA `devices.txt` export listing device selectors and certificate IDs;
- Local CA Extron PEM downloads;
- an Upload tab with saved devices and manual deployment fallback;
- server-side deployment infrastructure, but no UI-driven Toolbelt batch upload workflow.

The missing capability is a user-facing workflow where CertMon shows which `devices.txt` devices are targeted, performs a background dry-run/reachability check, lets the user start a real upload only for eligible devices, shows progress per device, supports safe cancellation, and records the latest dry-run/upload result per device.

## Requirements

1. **Desktop-first Toolbelt flow**: The feature must work in the current single-user Windows desktop/main branch without requiring server-mode or multi-user authentication.
   - Current: Toolbelt automation exists only as a standalone script and is not integrated into the UI.
   - Target: CertMon exposes Toolbelt batch dry-run/upload controls in the desktop UI.
   - Acceptance: A Windows desktop build can open the Toolbelt upload UI without any Phase 02 server-mode features enabled.

2. **`devices.txt` as primary source**: The upload target list must be based on the same device/certificate mapping used by the existing Local CA `devices.txt` export.
   - Current: `devices.txt` can be downloaded manually, but the UI does not show it as the upload batch source.
   - Target: The UI clearly states that the Toolbelt batch uses the `devices.txt` device/certificate list and renders the selected devices before upload.
   - Acceptance: A verifier can compare the UI target list with `/api/ca/devices-txt` and see matching device selectors/certificate mappings.

3. **Visible selectable device list**: The UI must show the selected upload devices as a list and allow the user to select or deselect devices before real upload.
   - Current: Local CA issued certificates are listed, but there is no Toolbelt batch selection state.
   - Target: Devices eligible for Toolbelt upload are shown with checkboxes, certificate identity, and current dry-run/upload status.
   - Acceptance: Unchecking a device prevents that device from being included in the subsequent real upload run.

4. **Automatic background dry-run**: CertMon must run a safe dry-run/reachability check in the background without requiring a separate user click.
   - Current: Users must manually invoke `toolbelt_uploader.py` dry-run outside CertMon.
   - Target: Opening or refreshing the Toolbelt upload panel starts a background dry-run that checks whether each device is reachable and targetable without applying/uploading a certificate.
   - Acceptance: The UI updates each device to a pass/fail dry-run status without the user pressing an extra dry-run button, and no certificate is uploaded during this check.

5. **Real upload starts only from explicit user action**: Actual upload must require a deliberate user click after dry-run results are visible.
   - Current: No UI path exists for Toolbelt upload.
   - Target: A real upload button is available after targets are shown; it uploads only selected devices.
   - Acceptance: No real upload occurs merely by opening the tab or running the background dry-run.

6. **Safe cancellation**: The user must be able to stop a running batch after the current device completes.
   - Current: Standalone script execution has no CertMon UI stop control.
   - Target: The progress dialog includes a stop/cancel control that prevents starting the next device while allowing the current device operation to finish safely.
   - Acceptance: During a multi-device run, pressing stop marks pending devices as not started/cancelled and does not begin another device after the active one finishes.

7. **Persist last per-device result**: CertMon must save the latest dry-run and upload result per device.
   - Current: Toolbelt script logs to `toolbelt_upload.log`, but CertMon does not store per-device status for UI reuse.
   - Target: CertMon records per device: last dry-run status, last upload status, timestamp, and message.
   - Acceptance: After restarting CertMon, the Toolbelt upload UI still shows each device’s latest dry-run/upload outcome.

## Boundaries

**In scope:**

- Windows desktop/single-user Toolbelt integration.
- UI panel/dialog for the `devices.txt` Toolbelt target list.
- Automatic background dry-run/reachability/targetability check.
- Real upload action for selected devices only.
- Per-device progress display during dry-run and upload.
- Safe “stop after current device” cancellation.
- Persisting latest per-device dry-run/upload status.
- Clear user-facing explanation of which list is used and what dry-run vs upload means.

**Out of scope:**

- Server-mode/multi-user roles and permissions — handled by Phase 02.
- Browser-based private-key delivery beyond existing explicit download/security boundaries.
- Replacing Extron Toolbelt with a custom protocol implementation — Toolbelt remains the automation target.
- Upload support for non-Extron devices — this phase is Extron/Toolbelt-specific.
- Full historical audit log of every run — this phase stores latest per-device status only.
- Force-aborting Toolbelt mid-device — cancellation is safe stop-after-current-device only.
- Automatic upload without user confirmation — real upload always requires explicit action.

## Constraints

- Must run on Windows desktop where Extron Toolbelt is installed or already running.
- Must not upload certificates or reboot devices during background dry-run.
- Must keep the existing private-key safety model: private material is only materialized server-side/locally as needed for Toolbelt and is not silently exposed to browser state.
- Must handle Toolbelt missing/not running with a clear user-facing message.
- Must tolerate partial failure: one device failure must not prevent remaining selected devices from being processed.
- Must avoid blocking the UI while dry-run/upload is active.

## Acceptance Criteria

- [ ] Toolbelt upload UI opens on the desktop build without requiring server-mode features.
- [ ] UI clearly labels `devices.txt` as the source of the batch target list.
- [ ] UI displays the same device/certificate mappings as `/api/ca/devices-txt`.
- [ ] Background dry-run starts without a separate dry-run click and does not perform a real upload.
- [ ] Each device shows dry-run result: pending/running/ok/failed plus timestamp/message.
- [ ] Real upload requires an explicit user action after the target list is visible.
- [ ] Only checked devices are uploaded.
- [ ] Progress dialog shows current device, completed count, failed count, and pending count.
- [ ] Stop/cancel prevents the next device from starting after the active device finishes.
- [ ] Per-device latest dry-run/upload status persists after CertMon restart.
- [ ] Missing Toolbelt produces a clear UI error and no crash.
- [ ] Failure on one device does not stop the whole batch unless the user cancels.

## Ambiguity Report

| Dimension           | Score | Min   | Status | Notes |
|---------------------|-------|-------|--------|-------|
| Goal Clarity        | 0.90  | 0.75  | ✓      | Desktop Toolbelt batch workflow is specific and measurable. |
| Boundary Clarity    | 0.86  | 0.70  | ✓      | Server-mode, non-Extron, force abort, and full history are explicitly excluded. |
| Constraint Clarity  | 0.80  | 0.65  | ✓      | Windows/Toolbelt/dry-run/private-material constraints are locked. |
| Acceptance Criteria | 0.82  | 0.70  | ✓      | Pass/fail UI, persistence, cancellation, and failure criteria are listed. |
| **Ambiguity**       | 0.15  | ≤0.20 | ✓      | Ready for discuss/plan. |

Status: ✓ = met minimum, ⚠ = below minimum (planner treats as assumption)

## Interview Log

| Round | Perspective | Question summary | Decision locked |
|-------|-------------|------------------|-----------------|
| 1 | Researcher | Should this be desktop/main now or after server-mode? | Direct desktop/main first; no dependency on Phase 02. |
| 1 | Researcher | Which device source should drive the batch? | Existing `devices.txt` list is primary source and must be visible in UI. |
| 1 | Researcher/Simplifier | Should uploads run immediately or start with dry-run? | Background dry-run happens automatically; real upload requires explicit action. |
| 2 | Boundary Keeper | What counts as dry-run success? | Device is reachable and Toolbelt can target it; no upload/apply/reboot occurs. |
| 2 | Failure Analyst | How should cancellation work? | Stop after current device; do not force-abort mid-device. |
| 2 | Seed Closer | What result history is required? | Persist latest per-device dry-run/upload status, timestamp, and message; full run history is out of scope. |

---

*Phase: certmon-03-toolbelt-auto-upload-ui-with-device-progress-and-cancellatio*
*Spec created: 2026-06-28*
*Next step: $gsd-discuss-phase 3 — implementation decisions (how to build what's specified above)*
