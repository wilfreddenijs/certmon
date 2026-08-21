# CertMon Roadmap

## Current Phase

### Phase 01: Secure Certificate Renewal

Status: complete.

Source plan:

- `docs/superpowers/plans/2026-06-13-certificate-renewal.md`

Goal: replace generated renewal commands with secure Local CA, External CA/import, native ACME DNS-01 issuance, encrypted artifacts, explicit private-key export, and server-side deployment support.

Closed: 2026-07-07. UAT passed with Cloudflare DNS automation explicitly skipped for now.

## Future Phases

### Phase 02: Shared Server Mode and Team Local CA

Status: implemented; human UAT completed; all gap-closure plans executed and verification pending.

Plans:

- [x] 02-01-PLAN.md
- [x] 02-02-PLAN.md
- [x] 02-03-PLAN.md

3/3 plans executed

**Wave 1 — completed implementation**

- [x] `.planning/phases/02-shared-server-mode/02-01-PLAN.md` — Shared server mode and team Local CA

**Wave 2 — gap closure** *(depends on Wave 1)*

- [x] `.planning/phases/02-shared-server-mode/02-02-PLAN.md` — User and role administration plus authentication polish

**Wave 3 — gap closure** *(depends on Wave 2)*

- [x] `.planning/phases/02-shared-server-mode/02-03-PLAN.md` — Full server backup and staged recovery

Cross-cutting constraints:

- Server-side permissions remain authoritative and every sensitive mutation is CSRF-protected and audited without secrets.
- Account and recovery workflows must prevent administrator lockout, stale sessions, plaintext-key exposure, and in-place replacement of active server data.

Goal: turn CertMon into a safe shared LAN service with local users, roles, sessions, CSRF protection, user-aware audit logs, guarded private-key export, and shared Local CA trust bundle export.

Implementation summary:

- `.planning/phases/02-shared-server-mode/02-01-SUMMARY.md` â€” Shared server mode and team Local CA
- `.planning/phases/02-shared-server-mode/02-02-SUMMARY.md` — User and role administration plus authentication polish
- `.planning/phases/02-shared-server-mode/02-03-SUMMARY.md` — Full server backup and staged recovery
- `.planning/phases/02-shared-server-mode/02-UAT.md` — Human UAT: 8 passed, 2 major gaps captured in Plans 02-02 and 02-03

### Phase 3: Toolbelt auto-upload UI with device progress and cancellation

**Goal:** Add a desktop UI flow that uses the existing CertMon `devices.txt` list to run Extron Toolbelt dry-runs and uploads with visible per-device progress, cancellation, and saved last-result status.
**Requirements**: Locked in `.planning/phases/certmon-03-toolbelt-auto-upload-ui-with-device-progress-and-cancellatio/03-SPEC.md`
**Depends on:** Phase 1 / current `main`
**Plans:** 1 plan

Plans:

- [x] `.planning/phases/certmon-03-toolbelt-auto-upload-ui-with-device-progress-and-cancellatio/03-01-PLAN.md` — Toolbelt auto-upload UI with device progress and cancellation

### Phase 04: Extron workflow/UI simplification

**Goal:** Restructure the CertMon workflow around scanned Extron devices, a single upload list, and centralized Local CA device-certificate handling in the Upload tab, while keeping the existing certificate and Toolbelt implementation logic unchanged.
**Requirements:** Locked in `.planning/phases/certmon-04-extron-workflow-ui-simplification/04-SPEC.md`
**Depends on:** Phase 03 Toolbelt auto-upload UI
**Plans:** 1 plan

Plans:

- [x] `.planning/phases/certmon-04-extron-workflow-ui-simplification/04-01-PLAN.md` — Device-first Extron Local CA and Upload workflow
