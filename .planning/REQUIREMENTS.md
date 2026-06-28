# CertMon Requirements

## Current Release Requirements

The current certificate-renewal release requirements are tracked in:

- `docs/superpowers/specs/2026-06-13-certificate-renewal-design.md`
- `docs/superpowers/plans/2026-06-13-certificate-renewal.md`

## Future Server-Mode Requirements

- CertMon must remain local-only by default.
- LAN/server mode must be explicit opt-in.
- LAN/server mode must require authentication.
- Users must have roles and server-side permissions.
- Private-key downloads must require explicit permission and audit.
- Local CA public trust material may be exported.
- Local CA private key must not be downloadable.
- Mutating requests must be CSRF protected.
- Sensitive events must be user-attributed in audit logs.
- Backup/restore must preserve users, roles, Local CA material, artifacts, and audit data.

