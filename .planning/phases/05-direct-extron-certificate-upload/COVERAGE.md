# API Coverage - Extron certificate/device transport

> Full coverage by default. Opt-outs are explicit, reasoned decisions. This matrix is intentionally limited to the certificate deployment transport surface, not the wider Extron SIS command set.

| capability | decision | reason |
|---|---|---|
| `ssh-host-key-enroll-22022` | INTEGRATE | |
| `ssh-host-key-enroll-22023` | INTEGRATE | |
| `ssh-host-key-rotate-22022` | INTEGRATE | |
| `ssh-host-key-rotate-22023` | INTEGRATE | |
| `saved-device-or-shared-password-auth` | INTEGRATE | |
| `read-only-connectivity-probe` | INTEGRATE | |
| `sftp-root-stage-combined-pem` | INTEGRATE | |
| `sftp-run-owned-stage-cleanup` | INTEGRATE | |
| `sis-import-without-passphrase` | INTEGRATE | |
| `sis-import-with-passphrase` | INTEGRATE | |
| `sis-fragmented-exact-ack-parse` | INTEGRATE | |
| `lan-a-nic-1-activation` | INTEGRATE | |
| `lan-b-nic-2-activation` | INTEGRATE | |
| `selected-https-endpoint-fingerprint-verify` | INTEGRATE | |
| `verification-only-recovery` | INTEGRATE | |
| `sis-view-current-certificate-json` | OPT-OUT | HTTPS peer DER fingerprint comparison is the locked verification contract; adding a second parser would not strengthen activation acceptance. |
| `sis-delete-user-certificate` | IMPLEMENTED / HARDWARE PENDING | User explicitly authorized on 2026-10-06. One-device LAN choice, confirmation, pinned SSH, exact CertX acknowledgement and V-command JSON readback. No automatic replay; physical removal/readback acceptance remains pending. |
| `non-certificate-sis-commands` | OPT-OUT | Explicitly outside the Phase 05 certificate/device transport surface. |
