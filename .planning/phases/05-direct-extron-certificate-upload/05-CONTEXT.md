# Phase 05: Direct Extron Certificate Upload - Context

Captured: 2026-10-04
Status: Confirmed workflow captured; ready for planning, not implemented

## Scope

Replace Toolbelt automation with direct certificate transfer and activation while
retaining the working Upload list, selection, credential storage, per-device
progress, cancellation, authorization and audit boundaries. Phase 02 is accepted
and merged to main; do not reopen its passed UAT as part of this new transport.

<decisions>

## Confirmed User Decisions

- **D-01:** Transfer the combined device-certificate/private-key PEM over SFTP on TCP 22022;
  the SFTP root folder is acceptable in the user's successful experiment.
- **D-02:** Send the SIS certificate-ingest command over authenticated SSH on TCP 22023.
- **D-03:** Activation is immediate in the tested workflow; no normal reboot.
- **D-04:** Default to LAN A (NIC 1); offer LAN B (NIC 2) per device, not as a global default.
- **D-05:** Keep private material encrypted at rest and server-side; preserve Phase 02 roles,
  credential handling and audit rules.
- **D-06:** Retire Toolbelt only after the direct replacement has passed device verification.

## Planning Checkpoint Accepted 2026-10-04

User response: `1A, 2A 3A`.

- **D-07 (1A):** Unknown or changed SSH host keys block authentication/transfer.
  A user with the existing `deploy_certificate` permission may explicitly approve
  the SHA-256 host-key fingerprint. Persist approvals and audit enrollment and
  rotation; introduce no new role. Approval must identify the endpoint/port/key
  and must not silently accept a substituted key.
- **D-08 (2A):** Direct upload uses stored per-device/shared credentials. A known
  serial number can be entered as the device password. Keep the existing Toolbelt
  route with automatic serial fallback until that fallback is explicitly retired
  or a supported serial source before authentication is available. Do not block
  the direct transport on speculative unauthenticated serial discovery.
- **D-09 (3A):** Persist a separate LAN B HTTPS hostname/address and port per
  device. LAN B cannot be selected until that endpoint is configured. Never
  verify LAN B against LAN A or infer success from LAN A's certificate.

</decisions>

## Canonical References

- `docs/specs/extron-direct-upload.md`: confirmed workflow and verification constraints.
- `docs/SIS command for Cert Ingest.png`: command, response, passphrase and NIC reference,
  now present on main. Read the screenshot before finalizing protocol framing.
- `certmon/deployment.py`, `certmon/toolbelt.py`, `certmon/vault.py`, `app.py` and
  `templates/index.html`: existing transport, orchestration, secrets and UI boundaries.

## Open Planning Questions

Confirm supported models/firmware, SFTP/SSH authentication,
SIS control bytes/responses, encrypted-PEM passphrase handling and timeout behavior.
Direct automatic serial discovery is deferred under D-08; do not assume it works.
Confirm staged-file
cleanup and safe handling of transfer/import/verification partial failures.
For LAN B capture the reachable HTTPS endpoint under D-09 and verify on hardware.

## Acceptance Boundaries

- A connectivity/test action must not silently ingest or activate a certificate.
- Transfer success alone is not upload success: require SIS success and HTTPS
  verification of the expected certificate fingerprint on the chosen interface.
- Test one-LAN and two-LAN devices on real hardware; one successful experiment
  is not universal compatibility evidence.
- Plan packaging, UI wording, documentation and regression coverage with the
  migration. No new roles, weakened authorization or browser-visible private PEM.

## Deferred Work

This context captures existing decisions and the accepted planning checkpoint.
It authorizes phase planning, not implementation, device writes or publication/build.
