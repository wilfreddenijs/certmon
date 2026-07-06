---
status: diagnosed
phase: 01-secure-certificate-renewal
source:
  - docs/superpowers/plans/2026-06-13-certificate-renewal.md
  - docs/superpowers/specs/2026-06-13-certificate-renewal-design.md
started: 2026-07-01T10:24:00+02:00
updated: 2026-07-01T10:49:00+02:00
---

## Current Test

[testing complete]

## Tests

### 1. Local-Only Startup And Renewal UI
expected: CertMon starts in desktop/local mode without server-mode/auth requirements. The renewal wizard offers Let's Encrypt / ACME, CertMon Local CA, and External CA or existing certificate, with endpoint host/port separate from certificate identifiers and no Certbot/acme.sh selector.
result: pass

### 2. Local CA Issuance
expected: From the renewal wizard, choose CertMon Local CA for a private IP or internal hostname. CertMon should issue a Local CA certificate without internet access, store it securely, show the issued certificate in the renewal/job UI, and avoid returning private key material in ordinary JSON responses.
result: issue
reported: "When CertMon Local CA is selected, it asks for a certificate profile (fine), it then asks for confirmation on the selected parameters (Endpoint IP, Identifiers, Issuer and Certificate Profile, then it will put it in the renewals list with the option Deploy Now or Delete entry. 2 entries are created in the Upload tabm which leads me to belief that the certificates have been created"
severity: major

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
passed: 8
issues: 1
pending: 0
skipped: 1
blocked: 0

## Gaps

- truth: "Local CA issuance creates one issued certificate/job and does not create duplicate Upload entries"
  status: failed
  reason: "User reported: When CertMon Local CA is selected, it asks for a certificate profile and confirmation, then puts it in the renewals list with Deploy Now/Delete entry. Two entries are created in the Upload tab."
  severity: major
  test: 2
  root_cause: "The Upload tab currently presents both the legacy manual target-device/push UI and the Toolbelt batch list derived from Local CA Extron certificates. A Local CA certificate can therefore appear through multiple upload surfaces even when the underlying certificate creation succeeded."
  artifacts:
    - path: "templates/index.html"
      issue: "Upload tab renders upload-device-list/push controls and toolbelt-device-list as separate primary surfaces."
    - path: "app.py"
      issue: "Local CA issuance creates a renewal/certificate artifact; Toolbelt list derives from stored Local CA certificates rather than legacy upload_devices."
  missing:
    - "Consolidate Upload into one central prepared-device list and move manual upload into a fallback section."
    - "Clarify Local CA issuance feedback so users can distinguish one issued certificate from multiple upload UI surfaces."
  debug_session: "inline UAT diagnosis 2026-07-01"
