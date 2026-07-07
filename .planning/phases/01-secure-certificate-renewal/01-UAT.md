---
status: complete
phase: 01-secure-certificate-renewal
source:
  - docs/superpowers/plans/2026-06-13-certificate-renewal.md
  - docs/superpowers/specs/2026-06-13-certificate-renewal-design.md
started: 2026-07-01T10:24:00+02:00
updated: 2026-07-07T00:00:00+02:00
---

## Current Test

[testing complete]

## Tests

### 1. Local-Only Startup And Renewal UI
expected: CertMon starts in desktop/local mode without server-mode/auth requirements. The renewal wizard offers Let's Encrypt / ACME, CertMon Local CA, and External CA or existing certificate, with endpoint host/port separate from certificate identifiers and no Certbot/acme.sh selector.
result: pass

### 2. Local CA Issuance
expected: From the renewal wizard, choose CertMon Local CA for a private IP or internal hostname. CertMon should issue a Local CA certificate without internet access, store it securely, show the issued certificate in the renewal/job UI, and avoid returning private key material in ordinary JSON responses.
result: pass
reported: "When CertMon Local CA is selected, it asks for a certificate profile (fine), it then asks for confirmation on the selected parameters (Endpoint IP, Identifiers, Issuer and Certificate Profile, then it will put it in the renewals list with the option Deploy Now or Delete entry. 2 entries are created in the Upload tabm which leads me to belief that the certificates have been created"
resolved: "Phase 04 consolidated Upload into one prepared-device Toolbelt list and moved manual upload into a collapsed fallback section. Follow-up UAT accepted the workflow/UI."

### 3. External CA CSR Pause And Completion
expected: Choose External CA with the generated-CSR workflow. CertMon creates a CSR, pauses the job for a signed certificate, survives restart, and later accepts the signed certificate/chain without exposing the private key.
result: pass

### 4. Existing Certificate Import
expected: Choose External CA/import existing certificate. CertMon accepts a matching certificate/private-key pair after validation, rejects mismatched keys or malformed chains, and stores private material encrypted.
result: pass

### 5. Manual DNS ACME Staging
expected: Choose Let's Encrypt staging with manual DNS. CertMon shows the required _acme-challenge TXT record, waits until authoritative DNS visibility is confirmed, then completes staging issuance and stores artifacts.
result: pass

### 6. Cloudflare DNS Automation
expected: Configure a scoped Cloudflare token, choose Cloudflare DNS automation, and complete staging issuance without the token appearing in JSON storage, API responses, logs, or UI state.
result: skipped
reason: skip for now

### 7. Production Gating
expected: Production Let's Encrypt issuance is blocked until the same normalized identifier set has a successful staging proof. CertMon shows a clear staging-required action instead of bypassing the gate.
result: pass

### 8. Server-Side Deployment Boundary
expected: Deploying an issued certificate submits only certificate ID and device ID from the browser. The server decrypts private material internally, records deployment/fingerprint status, and never round-trips private PEM through browser state.
result: pass

### 9. Backup, Recovery, And Restart
expected: Encrypted artifacts, renewal metadata, credentials, and recovery material survive restart/backup-restore checks. Paused jobs remain resumable and interrupted jobs recover without duplicate advancement.
result: pass

### 10. Offline Regression Suite And Packaging
expected: The offline pytest suite passes, Python compileall succeeds, and the Windows EXE build/UAT works with a temporary CERTMON_DATA_DIR.
result: pass

## Summary

total: 10
passed: 9
issues: 0
pending: 0
skipped: 1
blocked: 0

## Gaps

- none

## Closeout

Phase 01 UAT closed on 2026-07-07. The only recorded major issue, duplicate-looking Upload surfaces after Local CA issuance, was resolved by the Phase 04 device-first Upload workflow and accepted in follow-up testing.
