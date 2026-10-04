# CertMon Project

## What This Is

CertMon is a Windows-focused certificate monitoring and management tool for local devices, internal services, and certificate renewal workflows.

## Core Value

CertMon makes certificate monitoring, renewal, trust distribution, and deployment manageable without exposing private keys or weakening the safe desktop defaults.

## Requirements

The active functional and security requirements are maintained in `.planning/REQUIREMENTS.md`. Implementations must preserve secure key handling, loopback-safe desktop behavior, and authenticated, authorized, audited mutations in shared server mode.

## Current State

The current active implementation branch is `feature/certificate-renewal`.

The certificate-renewal phase adds secure renewal jobs, Local CA issuance, External CA/import workflows, ACME DNS-01 issuance, server-side artifact storage, explicit private-key export, and deployment integration.

## Locked Decisions

- CertMon remains local/single-user by default until shared server mode is explicitly implemented.
- The default bind target must remain loopback-safe.
- Private keys must not be sent to the browser except through explicit manual private-key export/download actions.
- The CertMon Local CA private key must never be downloadable as a normal UI artifact.
- Shared LAN/server use requires authentication, authorization, audit, and CSRF hardening before being supported.

## Next Milestone Direction

After certificate-renewal UAT is complete, the next planned phase is shared server mode for team use and shared Local CA operations.
