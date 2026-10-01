# Phase 02: Shared Server Mode - Context

**Gathered:** 2026-10-02
**Status:** Ready for gap-closure planning; phase remains incomplete

<domain>
## Phase Boundary

Close the remaining UAT 5 role-visibility gap in the existing shared-server mode. Keep the implemented authentication, role model, backend authorization, CSRF, audit, and backup/recovery behavior intact. Desktop mode retains its full local functionality.

The build-15 delivery work in plan 02-04 has already been published and retested: UAT 4 and 9 passed, UAT 5 still fails. Do not repeat publication as though the stale-build diagnosis were still current, or mark this phase complete while the remaining gap is open.
</domain>

<decisions>
## Implementation Decisions

### Navigation and Controls
- **D-01:** Hide unauthorized controls rather than showing disabled controls or letting users click them to discover a permission error. Apply this to static and dynamically rendered controls across the application, not only the two reported examples.
- **D-02:** A tab remains visible if at least one of its information views or actions is allowed. Hide the tab only if every part is unavailable to the current user. Within a partially accessible tab, hide restricted sections and actions.
- **D-03:** Derive visibility from effective permissions, including the union of multiple roles, rather than role-name shortcuts. Do not alter role assignments or backend permissions to simplify UI visibility.

### Public Information and Downloads
- **D-04:** Viewer retains device addresses, hostnames, issuers, validity, scan results, renewal overview/progress/results, and public Local CA metadata and issued-certificate information.
- **D-05:** All authenticated roles retain public device certificates, certificate chains, CSRs, the public CA certificate, the public trust bundle, the device-overview Excel export, and devices.txt references without private keys. Show downloads only where the corresponding artifact exists.
- **D-06:** Upload may remain visible for public certificate downloads even when Toolbelt deployment is unavailable. Public downloads must not depend on a deployment-only listing request. Avoid requests for inaccessible sections on startup or tab selection.
- **D-07:** Private device keys, Extron combined PEMs, the all-Extron-PEMs ZIP, encrypted CA-backup export, and full server-backup export remain restricted to their existing permissions. Viewer must see none of those controls. Public certificate trust downloads must never include private-key material.
- **D-08:** Toolbelt list and run information remain deployment-permission restricted. Audit and user administration remain restricted to their existing permissions. This is not approval to broaden access to private data, credentials, or audit records.

### Sessions
- **D-09:** Do not add live permission polling or automatically rearrange the UI during an otherwise valid session. Determine available UI from the authenticated session and refresh it after authentication.
- **D-10:** Preserve immediate session revocation on role change, account disablement, and password reset. On the next request after session expiration or revocation, return to sign-in and clear protected UI state; do not defer backend enforcement until normal session expiry.

### Implementation Discretion
Reuse existing layout, authentication state, permission identifiers, and public artifact routes. Internal helper structure and test organization are engineering choices, subject to the decisions above.
</decisions>

<canonical_refs>
## Canonical References

Downstream agents must read:
- `.planning/REQUIREMENTS.md` - desktop defaults and shared-server security constraints.
- `.planning/ROADMAP.md` - phase boundary and completed implementation plans.
- `.planning/phases/02-shared-server-mode/02-UAT.md` - nine passed tests and the unresolved Viewer visibility gap G-02-2.
- `.planning/phases/02-shared-server-mode/02-VERIFICATION.md` - prior implementation verification; older than the final build-15 UAT results.
- `.planning/phases/02-shared-server-mode/02-04-PLAN.md` - historical publication plan, not a product-code repair plan.
- `certmon/permissions.py` - authoritative permission identifiers and additive role mapping.
- `certmon/auth.py` - existing session revocation policy.
- `app.py` - authoritative route authorization and available public/private artifact routes.
- `templates/index.html` - existing authentication, navigation, and dynamic controls.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ROLE_PERMISSIONS` and `permissions_for_roles()` define effective permissions centrally.
- `authState` and existing Administration visibility helpers provide UI integration points.
- Public artifact endpoints expose certificate.pem, chain.pem, full-chain.pem, and request.csr separately from private-key.pem and combined.pem.

### Established Patterns
- Backend authorization is authoritative; visibility is a usability layer, not a security replacement.
- Download links and certificate lists are both static and dynamically rendered; visibility must cover both.
- Desktop mode grants local permissions without requiring server authentication.

### Integration Points
- Authentication initialization and login/logout transitions.
- Tab navigation and section loading, Local CA rendering, manual downloads, device and renewal controls, Toolbelt, Audit, and Administration.
- Existing UI contract, RBAC, authentication, and user-management tests. Add browser behavior coverage for role visibility rather than relying only on HTML string assertions.
</code_context>

<specifics>
## Specific Examples

A Viewer must not see the Audit tab or Download all Extron PEMs button. Upload stays available if it contains public downloads the Viewer may use. An administrator and desktop user retain their existing authorized functionality.
</specifics>

<deferred>
## Deferred Ideas

None. No new roles, permission model, live session updates, or server capabilities were requested.
</deferred>
