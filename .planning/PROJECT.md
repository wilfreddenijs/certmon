# CertMon Project

## What This Is

CertMon is a Windows-focused certificate monitoring and management tool for local devices, internal services, and certificate renewal workflows.

## Core Value

CertMon makes certificate monitoring, renewal, trust distribution, and deployment manageable without exposing private keys or weakening the safe desktop defaults.

## Requirements

The active functional and security requirements are maintained in `.planning/REQUIREMENTS.md`. Implementations must preserve secure key handling, loopback-safe desktop behavior, and authenticated, authorized, audited mutations in shared server mode.

## Current State

The current accepted implementation is on `main`, merge commit
`3fae74b24e5b7f0940c7e27df94a6735bf8b2d80`. Phase 02 shared server mode was
accepted on 2026-10-04: 10/10 human UAT and 288 automated tests passed. Build 24
is the main-branch delivery; build 23 is the human acceptance reference.

Completed work includes secure renewal jobs, Local CA issuance, External CA/import,
ACME DNS-01, encrypted artifacts, Toolbelt upload, device-first preparation and
authenticated shared server mode with additive roles, CSRF, audit and staged backups.
Phase 05 direct Extron certificate upload is the next phase; implementation has
not started. The live Cloudflare DNS-provider UAT remains explicitly deferred.

## Locked Decisions

- CertMon remains local/single-user by default; shared server mode requires explicit opt-in.
- The default bind target must remain loopback-safe.
- Private keys must not be sent to the browser except through explicit manual private-key export/download actions.
- The CertMon Local CA private key must never be downloadable as a normal UI artifact.
- Shared LAN/server use requires authentication, authorization, audit, and CSRF hardening before being supported.

## Next Milestone Direction

Plan Phase 05 from `docs/specs/extron-direct-upload.md`: combined PEM over SFTP
22022 followed by SIS import over SSH 22023, LAN A by default and optional LAN B.
Preserve credential, selection, cancellation, permission and audit boundaries.
Retire Toolbelt only after direct upload and HTTPS fingerprint verification pass.
