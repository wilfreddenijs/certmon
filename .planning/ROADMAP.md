# CertMon Roadmap

## Current Phase

### Phase 01 — Secure Certificate Renewal

Status: in UAT/final acceptance.

Source plan:

- `docs/superpowers/plans/2026-06-13-certificate-renewal.md`

Goal: replace generated renewal commands with secure Local CA, External CA/import, native ACME DNS-01 issuance, encrypted artifacts, explicit private-key export, and server-side deployment support.

## Future Phases

### Phase 02 — Shared Server Mode and Team Local CA

Status: planned, not started.

Plans:

- `.planning/phases/02-shared-server-mode/02-01-PLAN.md` — Shared server mode and team Local CA

Goal: turn CertMon into a safe shared LAN service with local users, roles, sessions, CSRF protection, user-aware audit logs, guarded private-key export, and shared Local CA trust bundle export.


### Phase 3: Toolbelt auto-upload UI with device progress and cancellation

**Goal:** Add a desktop UI flow that uses the existing CertMon `devices.txt` list to run Extron Toolbelt dry-runs and uploads with visible per-device progress, cancellation, and saved last-result status.
**Requirements**: Locked in `.planning/phases/certmon-03-toolbelt-auto-upload-ui-with-device-progress-and-cancellatio/03-SPEC.md`
**Depends on:** Phase 1 / current `main`
**Plans:** 1 plan

Plans:
- [ ] `.planning/phases/certmon-03-toolbelt-auto-upload-ui-with-device-progress-and-cancellatio/03-01-PLAN.md` — Toolbelt auto-upload UI with device progress and cancellation
