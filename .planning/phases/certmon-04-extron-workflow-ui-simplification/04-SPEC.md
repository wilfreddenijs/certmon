# Phase 4: Extron workflow/UI simplification - Specification

**Created:** 2026-06-30
**Ambiguity score:** 0.12 (gate: <= 0.20)
**Requirements:** 8 locked

## Goal

CertMon simplifies the operator workflow so users start from scanned devices, prepare Local CA device certificates from one central place, and upload Extron certificates through one clear Upload list. The phase is a UI/workflow restructuring phase only: the underlying certificate creation, storage, retrieval, and upload logic remains unchanged unless a small adapter is needed to expose existing behavior in the new flow.

## Background

UAT of the Toolbelt batch upload UI showed that CertMon now has the required lower-level pieces, but the user journey is split across tabs and concepts:

- the first tab is certificate-oriented while the operator thinks in devices;
- Local CA device-certificate actions are partly represented on the Local CA tab and partly in Upload;
- the upload target list can feel separate from discovered devices;
- manual certificate offering is still visible as a primary action even though it is now a fallback path.

The desired workflow is device-first: scan devices, choose Extron-compatible Local CA handling for a device, add it to the upload list, then run dry-run/upload from Upload.

## Requirements

1. **Rename the first tab from Certificates to Devices**
   - Current: the first tab is labeled around certificates.
   - Target: the first tab is labeled `Devices` and presents discovered/scanned devices as the primary starting point.
   - Acceptance: the main navigation shows `Devices` where the first tab currently says `Certificates`.

2. **Show scanned Extron devices as the source list**
   - Current: local upload targets and scanned devices can feel like separate concepts.
   - Target: local upload targets must always come from scanned devices, and the Devices tab should show all scanned devices that CertMon can present for this workflow.
   - Acceptance: a device cannot appear in the Upload list unless it also exists as a scanned device in the Devices workflow.

3. **Use Extron-compatible certificate profiles to determine Local CA device actions**
   - Current: Local CA device-certificate actions are not clearly tied to Extron-compatible profile choice in the workflow.
   - Target: Extron upload preparation is available when an Extron-compatible Local CA certificate profile is used, such as `Extron compatible (RSA)`.
   - Acceptance: the UI only offers the Extron Toolbelt upload workflow for Extron-compatible device certificates.

4. **Centralize Local CA device-certificate preparation in the Upload workflow**
   - Current: device certificate creation is visible in the Local CA area and upload flow.
   - Target: device Local CA certificate creation/preparation is centralized in the Upload workflow. The Local CA tab handles only the root/local CA side for this PC/laptop.
   - Acceptance: users do not need to go to the Local CA tab to create or manage a device certificate for Toolbelt upload.

5. **Upload tab contains one central device upload list**
   - Current: the upload flow can imply multiple lists or target concepts.
   - Target: the Upload tab shows one list of devices that have a Local CA device certificate and are therefore upload candidates.
   - Acceptance: adding a device to Upload creates or selects its Local CA device certificate, and Upload only lists devices with such a certificate.

6. **Remove from Upload also removes the associated Local CA device certificate**
   - Current: removal semantics are unclear.
   - Target: the red X removes the device from the Upload list and deletes the associated Local CA device certificate. The scanned device remains visible on Devices.
   - Acceptance: removal requires confirmation, the row disappears from Upload, and the device no longer has the generated Local CA device certificate associated with the upload list.

7. **Local CA tab is limited to root CA management for this PC/laptop**
   - Current: Local CA tab mixes root/local CA management and device-certificate concepts.
   - Target: Local CA tab is for creating/checking/installing the Local CA root in Windows and downloading the root certificate.
   - Acceptance: Local CA tab no longer presents the normal device-certificate creation path for Toolbelt upload.

8. **Manual upload is a fallback section, not the main workflow**
   - Current: `Push Certificate to Device` / manual certificate offering is visible as a primary flow even though it is obsolete for the new automatic flow.
   - Target: manual upload is hidden behind a collapsed section at the bottom of Upload.
   - Acceptance: the automatic Toolbelt upload list is the primary Upload content, and the existing manual upload UI is available only after expanding a bottom fallback section.

## Boundaries

**In scope:**

- UI tab naming and workflow restructuring.
- Device-first presentation of scanned Extron devices.
- A single central Upload list for devices with Local CA device certificates.
- Extron-only automatic upload workflow for now.
- Local CA root-management cleanup on the Local CA tab.
- Confirmation flow for deleting an upload-list device certificate.
- Collapsed Manual upload fallback section at the bottom of Upload.

**Out of scope:**

- Rewriting certificate generation, storage, retrieval, or Toolbelt upload internals.
- Adding non-Extron automatic upload support.
- Changing renewal logic.
- Server-mode or role/permission changes.
- Replacing Toolbelt automation with a custom protocol.

## Acceptance Criteria

- [ ] First tab is renamed to `Devices`.
- [ ] Devices tab presents scanned devices as the start of the workflow.
- [ ] Extron automatic upload actions are shown only for Extron-compatible Local CA profiles.
- [ ] Adding/preparing a device for Upload creates or selects its Local CA device certificate.
- [ ] Upload tab shows only devices with a Local CA device certificate.
- [ ] Upload tab presents one central list, not separate competing target lists.
- [ ] Removing a row from Upload asks for confirmation and deletes the associated Local CA device certificate.
- [ ] Removed devices disappear from Upload but remain visible on Devices when scanned.
- [ ] Local CA tab focuses on root CA creation, Windows trust check/install, and root certificate download.
- [ ] Manual upload is collapsed at the bottom of Upload and is no longer the main action path.
- [ ] Existing certificate and upload implementation tests continue to pass.

## Open Design Details

- Exact button text for preparing/adding a device should follow the current CertMon button style. Working label: `Local CA`.
- The Upload list name can remain pragmatic as long as there is only one visible primary list.

## Source Notes

- Based on `C:\Users\wilfr\Downloads\Certmon workflow.docx`.
- Clarifications captured during UAT on 2026-06-30:
  - local upload targets should always be scanned devices;
  - only Extron devices are in scope for now;
  - device certificates should be centralized in Upload, not Local CA;
  - removing from Upload deletes the Local CA device certificate;
  - manual upload should be a collapsed fallback section at the bottom of Upload.

---

*Phase: certmon-04-extron-workflow-ui-simplification*
*Spec created: 2026-06-30*
*Next step: $gsd-discuss-phase 4 - implementation decisions, then $gsd-plan-phase 4*