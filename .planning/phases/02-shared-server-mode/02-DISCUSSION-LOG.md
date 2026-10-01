# Phase 02: Shared Server Mode - Discussion Log

**Date:** 2026-10-02
**Purpose:** Human audit trail only; planning and execution consume 02-CONTEXT.md.

## Partially Accessible Tabs

The user selected: tabs remain visible if any part may be used; hide only when nothing in the tab is permitted. Unauthorized controls should be hidden, as already requested during UAT 5.

## Public Information and Downloads

The user initially requested a complete inventory before deciding. The inventory covered device and renewal information, Local CA metadata, public certificates/chains/CSRs, CA trust downloads, Excel, devices.txt, private keys/combined PEMs, backups, Toolbelt, Audit, and Administration.

Options presented:
1. Keep all listed public information and downloads, hide unauthorized actions.
2. Limit Viewer to Devices and CA trust downloads.
3. Select individual exclusions.

The user selected option 1. Private downloads and restricted operational information retain existing backend permissions. Public Upload downloads should not require Toolbelt deployment access.

## Session Changes

The user initially requested no changes during a session, only when it expires. The existing policy immediately revokes sessions on role changes. The distinction between live UI updates and backend session enforcement was explained.

Options presented:
1. No automatic UI changes; sign in again on the next request if the session has expired or been revoked. Preserve existing security.
2. Apply new permissions only on normal session expiry, changing the existing security policy.

The user selected option 1.

## Approval

The decisions were summarized, including hiding unauthorized controls, retaining partially accessible tabs, retaining public Viewer access, and preserving backend controls and revocation. The user selected option 1: record these decisions as context for the repair plan.

## Deferred Ideas

None. No product changes, publication, or build were authorized by this discussion.
