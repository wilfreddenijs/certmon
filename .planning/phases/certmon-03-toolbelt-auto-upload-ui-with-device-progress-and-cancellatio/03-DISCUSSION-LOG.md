# Phase 3: Toolbelt auto-upload UI with device progress and cancellation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-29
**Phase:** 3-Toolbelt auto-upload UI with device progress and cancellation
**Areas discussed:** Toolbelt integration shape, Device list UX, Upload gating and exceptions, Credentials and Toolbelt prompts

---

## Toolbelt integration shape

| Option | Description | Selected |
|--------|-------------|----------|
| CLI/subprocess | CertMon starts `toolbelt_uploader.py` as a background run and reads progress/results through a machine-readable channel. | ✓ |
| Importable Python service | Refactor Toolbelt code so CertMon calls functions directly. | |
| Hybrid | Create a small shared core but keep the real Toolbelt run as subprocess. | |

**User's choice:** CLI/subprocess.
**Notes:** The standalone tool already works and should remain the source of truth for this phase. A machine-readable progress/result channel is needed for UI integration.

---

## Device list UX

| Option | Description | Selected |
|--------|-------------|----------|
| Aparte Toolbelt batch-sectie in Upload tab | Clear batch section based on `devices.txt`, with device rows and checkboxes. | |
| Device-oriented list with Local CA status | Show all relevant devices and whether a Local CA certificate exists and whether it is selected for upload. | ✓ |
| Modal from Local CA or Upload tab | Open a dialog with the `devices.txt` list. | |

**User's choice:** A clear list containing all relevant devices.
**Notes:** The list must show device/IP/host, Local CA certificate presence, selected-for-upload state, dry-run status, and latest upload status. The final location may be a Toolbelt batch section in Upload tab, but the content must be device-oriented.

---

## Upload gating and exceptions

| Option | Description | Selected |
|--------|-------------|----------|
| Blokkeren | Failed dry-run devices cannot upload. | |
| Waarschuwing maar toestaan | Failed dry-run devices can still be forced. | |
| Alleen retry toestaan | Failed dry-run devices can only retry dry-run; upload stays blocked until dry-run OK. | ✓ |

**User's choice:** Alleen retry toestaan.
**Notes:** A failed dry-run should block real upload for that device. The UI should show a clear reason and offer retry.

---

## Credentials and Toolbelt prompts

| Option | Description | Selected |
|--------|-------------|----------|
| Saved Upload devices where possible | Use existing saved credentials, otherwise prompt or mark credentials needed. | |
| Eén batch-passwordveld | One optional batch-wide password/passphrase field. | |
| Toolbelt zelf laten vragen | CertMon starts Toolbelt but does not fill credentials. | |
| Combinatie | Try defaults, support custom per-device credentials, and save encrypted. | ✓ |

**User's choice:** Combination with encrypted per-device credentials.
**Notes:** Try `admin` / `extron` first. Second suggested option is `admin` / device serial number. If both fail, prompt for custom per-device credentials and allow saving encrypted. First Toolbelt run should check/instruct whether the serial-number column is visible in Toolbelt’s discovered-devices overview.

---

## the agent's Discretion

- The user did not choose a detailed progress-log style. Default planning should use concise per-device statuses plus optional expandable technical details.
- The exact machine-readable progress channel is left to planning.

## Deferred Ideas

- Full historical run/audit log.
- Server-mode/multi-user permission model for Toolbelt upload.
- Non-Extron automatic upload adapters.
- Full importable-service refactor of `toolbelt_uploader.py`.
