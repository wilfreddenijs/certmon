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

Status: implemented; final build-15 UAT has 9 passed tests and one unresolved role-visibility issue. Plans 02-05 and 02-06 completed; plan 02-07 browser matrix and regression suites passed. Fresh human UAT 5 remains pending; no phase completion claimed.

Plans:

- [x] 02-01-PLAN.md
- [x] 02-02-PLAN.md
- [x] 02-03-PLAN.md
- [x] 02-04-PLAN.md - historical publication summarized; UAT 5 remains unresolved, do not re-execute
- [x] 02-05-PLAN.md - browser harness and evidence-based historical summary reconciliation
- [x] 02-06-PLAN.md - effective permissions, public catalog, UI visibility and protected-session recovery
- [ ] 02-07-PLAN.md - browser role matrix and UAT 5 acceptance

6/7 plans have execution summaries. Do not repeat the already-published build-15 delivery or advance the phase before retesting UAT 5.

**Repair Wave 0 - 02-05**

- Browser infrastructure and historical reconciliation; no dependency on rerunning 02-04.

**Repair Wave 1 - 02-06** *(blocked on repair Wave 0)*

- Permission-driven UI and public downloads; session recovery covers normal fetch and the native Audit request path.

**Repair Wave 2 - 02-07** *(blocked on repair Wave 1)*

- Complete browser matrix and human acceptance; preserve passed UAT 4 and 9.

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
- `.planning/phases/02-shared-server-mode/02-UAT.md` - Final build-15 human UAT: 9 passed, 1 major Viewer role-visibility gap
- `.planning/phases/02-shared-server-mode/02-CONTEXT.md` - Approved visibility and session decisions for the remaining repair

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

### Phase 05: Direct Extron certificate upload

**Status:** Workflow decisions captured; not yet planned or implemented.
**Goal:** Replace Toolbelt automation with combined-PEM transfer over SFTP (22022), SIS import over SSH (22023), and HTTPS certificate verification while preserving upload-list and credential workflows.
**Canonical refs:** `docs/specs/extron-direct-upload.md`
**Depends on:** Phase 04 upload workflow; preserve Phase 02 authorization boundaries.
**Decisions:** LAN A by default, optional LAN B per device; no normal reboot. Retire Toolbelt only after the direct replacement is verified.
**Plans:** 0 plans
