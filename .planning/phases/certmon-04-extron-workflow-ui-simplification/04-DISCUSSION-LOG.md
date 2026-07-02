# Phase 4: Extron workflow/UI simplification - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md - this log preserves the alternatives considered.

**Date:** 2026-07-01
**Phase:** 4-Extron workflow/UI simplification
**Areas discussed:** Device flow, Local CA action behavior, Upload flow, Local CA tab cleanup

---

## Device Flow

| Option | Description | Selected |
|--------|-------------|----------|
| Status + choice | Existing Extron-compatible certificate shows ready status; clicking asks use existing, issue new, or cancel. | yes |
| Direct to Upload | Ready devices jump mainly to Upload. | |
| Always choice | All Local CA clicks always open a choice menu. | |

**User's choice:** Status + choice.
**Notes:** Existing certificate should be visible as a ready `Local CA` status, not silently replaced.

| Option | Description | Selected |
|--------|-------------|----------|
| All scanned devices | Devices tab shows all scanned devices; Extron actions only where applicable. | yes |
| Only Extron devices | Devices tab becomes Extron-only for this phase. | |
| Grouped devices | Extron devices separate from other scanned devices. | |

**User's choice:** All scanned devices.
**Notes:** Upload/Toolbelt is Extron-only for now, but Devices remains the general scanned-device starting point.

| Option | Description | Selected |
|--------|-------------|----------|
| One-click Local CA | Create certificate and add to Upload immediately. | |
| Detail/form first | Open CN/SAN/profile form before creating and adding. | yes |
| Jump to Upload | Let Upload guide certificate creation. | |

**User's choice:** Detail/form first.
**Notes:** The user wants control before creating the Local CA device certificate.

---

## Local CA Action Behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Inline paneel | Open preparation UI inside/under the device row. | |
| Modal/dialog | Open a focused dialog for CN/SAN/profile and create/add action. | yes |
| Side paneel | Use a right-side selected-device pane. | |

**User's choice:** Modal/dialog.
**Notes:** Dialog should keep the Devices list simple while making certificate creation deliberate.

| Option | Description | Selected |
|--------|-------------|----------|
| Use existing / Issue new / Cancel | Simple three-choice dialog. | |
| Use existing / Replace certificate / Cancel | Stronger replacement wording. | |
| Details first + primary Use existing | Show existing certificate details first, with use existing primary and issue new/replace secondary. | yes |

**User's choice:** Details first + primary Use existing.
**Notes:** Safer because the operator sees what will be reused before replacing anything.

| Option | Description | Selected |
|--------|-------------|----------|
| Default Extron compatible RSA | Recognized Extron devices default to Extron-compatible RSA profile. | yes |
| Require explicit profile confirmation | No default until user chooses. | |
| Last-used profile | Remember preference and warn if not Extron-compatible. | |

**User's choice:** Default Extron compatible RSA.
**Notes:** User may still change the profile when needed.

| Option | Description | Selected |
|--------|-------------|----------|
| Jump to Upload | Automatically switch after create/add. | |
| Stay on Devices | No navigation after create/add. | |
| Stay with feedback/link | Stay on Devices and show feedback with link/action to Upload. | yes |

**User's choice:** Stay with feedback/link.
**Notes:** Supports preparing multiple devices in sequence.

---

## Upload Flow

| Option | Description | Selected |
|--------|-------------|----------|
| Manual collapsed bottom | Toolbelt/prepared-device list is primary; manual upload collapsed as fallback at bottom. | yes |
| Manual subtab | Split Upload into Toolbelt and Manual subtabs. | |
| Manual visible lower | Keep manual visible below Toolbelt list. | |

**User's choice:** Manual collapsed bottom.
**Notes:** Matches previously accepted variant 1.

| Option | Description | Selected |
|--------|-------------|----------|
| Strong confirmation | Explicitly mention removing from Upload and deleting Local CA device certificate, including device/cert name. | yes |
| Short confirmation | Short remove text with smaller certificate deletion note. | |
| Two-step row confirmation | Remove then confirm inline. | |

**User's choice:** Strong confirmation.
**Notes:** Deleting a certificate must be unmistakable.

| Option | Description | Selected |
|--------|-------------|----------|
| Empty-state Devices link | Only when Upload is empty, show link to Devices. | |
| Explanation + Devices button | Empty-state explanation plus button. | |
| Always Add device button | Always show `Add device`; jumps to Devices. | yes |

**User's choice:** Always Add device button.
**Notes:** The button should remain visible even when the Upload list is not empty.

---

## Local CA Tab Cleanup

| Option | Description | Selected |
|--------|-------------|----------|
| All device-certificate UI removed | Local CA tab only handles root CA status/create, Windows trust/install, root download. | yes |
| Read-only device certificates | Show device certs without actions. | |
| Small Upload reference | Keep root CA functions plus link to Upload. | |

**User's choice:** All device-certificate UI removed.
**Notes:** User explicitly confirmed all device-certificate UI belongs at Devices.

## the agent's Discretion

- Exact styling and labels should follow existing CertMon UI patterns.
- Upload list naming may be chosen during implementation if only one primary list remains visible.

## Deferred Ideas

None.