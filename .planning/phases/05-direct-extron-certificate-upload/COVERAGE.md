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
| `sis-delete-user-certificate` | OPT-OUT | Destructive certificate removal is outside direct upload and requires separate explicit authorization/acceptance. |
| `non-certificate-sis-commands` | OPT-OUT | Explicitly outside the Phase 05 certificate/device transport surface. |
