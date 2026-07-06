# Phase 4: Extron workflow/UI simplification - Context

**Gathered:** 2026-07-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 04 delivers a device-first workflow/UI restructuring for CertMon: scanned devices become the starting point, Local CA device-certificate preparation moves to the Devices workflow, the Upload tab becomes one central prepared-device list for Toolbelt dry-run/upload, and the Local CA tab is limited to root CA management for this PC/laptop.

This phase does not rewrite certificate generation, storage, retrieval, renewal, or Toolbelt automation internals. Existing lower-level certificate and upload behavior should be reused unless a small adapter is needed to expose it in the new UI flow.

</domain>

<spec_lock>
## Requirements (locked via SPEC.md)

**8 requirements are locked.** See `04-SPEC.md` for full requirements, boundaries, and acceptance criteria.

Downstream agents MUST read `04-SPEC.md` before planning or implementing. Requirements are not duplicated here.

**In scope (from SPEC.md):**

- UI tab naming and workflow restructuring.
- Device-first presentation of scanned Extron devices.
- A single central Upload list for devices with Local CA device certificates.
- Extron-only automatic upload workflow for now.
- Local CA root-management cleanup on the Local CA tab.
- Confirmation flow for deleting an upload-list device certificate.
- Collapsed Manual upload fallback section at the bottom of Upload.

**Out of scope (from SPEC.md):**

- Rewriting certificate generation, storage, retrieval, or Toolbelt upload internals.
- Adding non-Extron automatic upload support.
- Changing renewal logic.
- Server-mode or role/permission changes.
- Replacing Toolbelt automation with a custom protocol.

</spec_lock>

<decisions>
## Implementation Decisions

### Device Flow

- **D-01:** The first tab becomes `Devices` and shows all scanned devices that CertMon can present, not only Extron devices.
- **D-02:** Extron/Local CA/Upload preparation actions are shown only where they are applicable. Non-Extron scanned devices may remain visible but do not get the Extron Toolbelt preparation path.
- **D-03:** A scanned device without a Local CA device certificate gets a `Local CA` action that opens a modal/dialog first. The user must be able to review or adjust CN, SAN, and certificate profile before creating the certificate and adding the device to Upload.
- **D-04:** A scanned device that already has an Extron-compatible Local CA device certificate shows a clear `Local CA` ready status, such as `Local CA ready`.

### Local CA Device-Certificate Action

- **D-05:** Clicking `Local CA ready` for a device with an existing Extron-compatible certificate opens a dialog that first shows the existing certificate details.
- **D-06:** In that existing-certificate dialog, the primary action is `Use existing`. A secondary action allows issuing/replacing with a new certificate. `Cancel` must remain available.
- **D-07:** For recognized Extron devices, the Local CA preparation dialog defaults to `Extron compatible (RSA)`. The user may change the profile when needed.
- **D-08:** After `Create & add to Upload`, CertMon stays on the Devices tab and shows clear feedback with a link/action to view Upload. It must not automatically pull the user away from batch-preparing multiple devices.
- **D-09:** All normal device-certificate UI belongs in the Devices workflow, not the Local CA tab.

### Upload Flow

- **D-10:** The Upload tab's primary content is the central prepared-device list for Toolbelt dry-run/upload.
- **D-11:** The Upload tab always shows an `Add device` button, even when the list is not empty. This button jumps to the Devices tab so the user can prepare another scanned device via `Local CA`.
- **D-12:** Manual upload is moved to a collapsed fallback section at the bottom of the Upload tab. It is no longer the main path.
- **D-13:** The red X/remove action must use a strong confirmation that explicitly says the device will be removed from Upload and the associated Local CA device certificate will be deleted. Include the device/certificate name in the confirmation.
- **D-14:** After removal, the device disappears from Upload but remains visible in Devices if it is still discovered/scanned.

### Local CA Tab Cleanup

- **D-15:** The Local CA tab is strictly for root CA management for this PC/laptop: root CA creation/status, Windows trust check/install, and root certificate download.
- **D-16:** Remove all normal device-certificate UI from the Local CA tab. Device certificate work is handled from Devices.

### the agent's Discretion

- The exact visual styling of `Local CA`, `Local CA ready`, modal layout, and toast/link feedback should follow existing CertMon button/card/dialog patterns.
- The Upload list title can be chosen by the implementer as long as there is only one visible primary prepared-device list.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Requirements

- `.planning/phases/certmon-04-extron-workflow-ui-simplification/04-SPEC.md` - Locked Phase 04 requirements, boundaries, acceptance criteria, and source notes.
- `.planning/ROADMAP.md` - Phase ordering and relationship to Phase 03 Toolbelt auto-upload UI.

### Source Workflow Notes

- `C:\Users\wilfr\Downloads\Certmon workflow.docx` - Original user workflow document that motivated Phase 04. This file is outside the repo; use the extracted decisions in `04-SPEC.md` and this CONTEXT if the file is unavailable.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `templates/index.html` contains the current tab navigation, Upload tab markup, Local CA tab markup, device card actions, and Toolbelt batch UI. Phase 04 will primarily restructure this file.
- `certmon/toolbelt.py` already exposes the Toolbelt batch service and prepared Local CA/Extron readiness concepts used by `/api/toolbelt/devices`.
- `app.py` already has routes for `/api/toolbelt/devices`, dry-run/upload runs, `/api/ca/devices-txt`, and legacy `/api/upload/devices` manual upload state.
- `certmon/profiles.py` defines Extron-compatible certificate profiles; planning should reuse this profile identity rather than inventing a new compatibility flag if existing data is sufficient.
- `tests/test_ui_contract.py`, `tests/test_toolbelt_service.py`, `tests/test_toolbelt_api.py`, and `tests/test_ca_api.py` already cover UI strings, Toolbelt behavior, and devices.txt behavior and should be extended for Phase 04.

### Established Patterns

- The current UI is a single `templates/index.html` application with tab switching, inline JavaScript state, fetch-based API calls, and existing button/card classes.
- Existing Toolbelt UI already uses selected devices, dry-run status, upload status, credentials state, and run polling; Phase 04 should preserve those semantics while moving the workflow around them.
- Existing Local CA UI already exposes `Extron compatible (RSA)` profile text and issued device certificate downloads; Phase 04 should relocate or hide device-certificate actions rather than changing certificate internals.

### Integration Points

- Tab navigation around `switchTab('certs')`, `switchTab('ca')`, and `switchTab('upload')` must be updated so the former Certificates tab becomes Devices.
- Existing functions around `sendToCA`, `sendToUpload`, `loadCAStatus`, `loadToolbeltDevices`, `renderToolbeltDevices`, `renderUploadDevices`, and `removeUploadDevice` are likely planning targets.
- API behavior may need a small adapter to support the Devices-tab Local CA modal and upload-list deletion semantics, especially deleting the associated Local CA device certificate when removing from Upload.

</code_context>

<specifics>
## Specific Ideas

- Use `Local CA` for the device action label and a check/status variant such as `Local CA ready` when ready.
- The Local CA preparation modal should expose CN, SAN, and profile before creating the certificate.
- For existing certificates, show certificate details first, then offer `Use existing` as primary and `Issue new`/replace as secondary.
- Keep the user on Devices after adding to Upload; show feedback with a direct path to Upload.
- The Upload tab must always have an `Add device` button that jumps to Devices.

</specifics>

<deferred>
## Deferred Ideas

None - discussion stayed within phase scope.

</deferred>

---

*Phase: 4-Extron workflow/UI simplification*
*Context gathered: 2026-07-01*