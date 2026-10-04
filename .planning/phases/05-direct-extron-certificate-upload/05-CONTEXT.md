# Phase 05: Direct Extron Certificate Upload - Context

Captured: 2026-10-04
Status: Confirmed workflow captured; ready for planning, not implemented

## Scope

Replace Toolbelt automation with direct certificate transfer and activation while
retaining the working Upload list, selection, credential storage, per-device
progress, cancellation, authorization and audit boundaries. Phase 02 is accepted
and merged to main; do not reopen its passed UAT as part of this new transport.

## Confirmed User Decisions

- Transfer the combined device-certificate/private-key PEM over SFTP on TCP 22022;
  the SFTP root folder is acceptable in the user's successful experiment.
- Send the SIS certificate-ingest command over authenticated SSH on TCP 22023.
- Activation is immediate in the tested workflow; no normal reboot.
- Default to LAN A (NIC 1); offer LAN B (NIC 2) per device, not as a global default.
- Keep private material encrypted at rest and server-side; preserve Phase 02 roles,
  credential handling and audit rules.
- Retire Toolbelt only after the direct replacement has passed device verification.

## Canonical References

- `docs/specs/extron-direct-upload.md`: confirmed workflow and verification constraints.
- `docs/SIS command for Cert Ingest.png`: command, response, passphrase and NIC reference,
  now present on main. Read the screenshot before finalizing protocol framing.
- `certmon/deployment.py`, `certmon/toolbelt.py`, `certmon/vault.py`, `app.py` and
  `templates/index.html`: existing transport, orchestration, secrets and UI boundaries.

## Open Planning Questions

Confirm supported models/firmware, SFTP/SSH authentication, host-key trust,
SIS control bytes/responses, encrypted-PEM passphrase handling and timeout behavior.
Find a supported direct serial-number source; do not assume Toolbelt discovery
is available or that direct serial retrieval already works. Confirm staged-file
cleanup and safe handling of transfer/import/verification partial failures.
For LAN B identify the reachable address and HTTPS endpoint for that interface.

## Acceptance Boundaries

- A connectivity/test action must not silently ingest or activate a certificate.
- Transfer success alone is not upload success: require SIS success and HTTPS
  verification of the expected certificate fingerprint on the chosen interface.
- Test one-LAN and two-LAN devices on real hardware; one successful experiment
  is not universal compatibility evidence.
- Plan packaging, UI wording, documentation and regression coverage with the
  migration. No new roles, weakened authorization or browser-visible private PEM.

## Deferred Work

This context is an administrative capture of existing decisions, not a new plan,
implementation authorization, device test or publication/build request.
