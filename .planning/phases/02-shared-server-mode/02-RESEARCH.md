# Phase 02: Shared Server Mode - RBAC UI Gap Closure Research

**Researched:** 2026-10-02
**Domain:** Existing shared-server RBAC UI visibility and browser validation
**Confidence:** HIGH for current code/test facts; MEDIUM for browser-harness design because no runner is installed.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
<!-- DATA_G7K4P2XM_START -->
- **D-01:** Hide unauthorized controls rather than showing disabled controls or letting users click them to discover a permission error. Apply this to static and dynamically rendered controls across the application, not only the two reported examples.
- **D-02:** A tab remains visible if at least one of its information views or actions is allowed. Hide the tab only if every part is unavailable to the current user. Within a partially accessible tab, hide restricted sections and actions.
- **D-03:** Derive visibility from effective permissions, including the union of multiple roles, rather than role-name shortcuts. Do not alter role assignments or backend permissions to simplify UI visibility.
- **D-04:** Viewer retains device addresses, hostnames, issuers, validity, scan results, renewal overview/progress/results, and public Local CA metadata and issued-certificate information.
- **D-05:** All authenticated roles retain public device certificates, certificate chains, CSRs, the public CA certificate, the public trust bundle, the device-overview Excel export, and devices.txt references without private keys. Show downloads only where the corresponding artifact exists.
- **D-06:** Upload may remain visible for public certificate downloads even when Toolbelt deployment is unavailable. Public downloads must not depend on a deployment-only listing request. Avoid requests for inaccessible sections on startup or tab selection.
- **D-07:** Private device keys, Extron combined PEMs, the all-Extron-PEMs ZIP, encrypted CA-backup export, and full server-backup export remain restricted to their existing permissions. Viewer must see none of those controls. Public certificate trust downloads must never include private-key material.
- **D-08:** Toolbelt list and run information remain deployment-permission restricted. Audit and user administration remain restricted to their existing permissions. This is not approval to broaden access to private data, credentials, or audit records.
- **D-09:** Do not add live permission polling or automatically rearrange the UI during an otherwise valid session. Determine available UI from the authenticated session and refresh it after authentication.
- **D-10:** Preserve immediate session revocation on role change, account disablement, and password reset. On the next request after session expiration or revocation, return to sign-in and clear protected UI state; do not defer backend enforcement until normal session expiry.
<!-- DATA_G7K4P2XM_END -->

### the agent's Discretion
<!-- DATA_N8V6R1CJ_START -->
Reuse existing layout, authentication state, permission identifiers, and public artifact routes. Internal helper structure and test organization are engineering choices, subject to the decisions above.
<!-- DATA_N8V6R1CJ_END -->

### Deferred Ideas (OUT OF SCOPE)
<!-- DATA_Q3L9H5WD_START -->
None. No new roles, permission model, live session updates, or server capabilities were requested.
<!-- DATA_Q3L9H5WD_END -->
</user_constraints>

## Summary

This is a narrow frontend repair, not a fresh shared-server implementation. Build-15 UAT passed tests 4 and 9; UAT 5 remains open because a Viewer can see Audit navigation and the private Download all Extron PEMs action although backend authorization denies those requests. [VERIFIED: .planning/phases/02-shared-server-mode/02-UAT.md, "Tests" and G-02-2]

The permission model and session-revocation behavior already exist. The exposed UI is the gap: Audit and the Extron ZIP are static markup, while current visibility helpers use role-name checks. [VERIFIED: certmon/permissions.py:25-62; templates/index.html:866-871,1048-1050,1398-1425]

**Primary recommendation:** Add server-derived effective permissions to the authenticated status response, use one centralized visibility pass for static and rendered controls, and add a Wave 0 browser harness. Preserve UAT 4/9 and plans 02-01 through 02-04 as historical work.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|---|---|---|---|
| Effective permission calculation | API / Backend | Browser / Client | Existing permissions_for_roles centrally unions roles; the browser should consume that answer. [VERIFIED: certmon/permissions.py:58-62] |
| Tab, section, and control visibility | Browser / Client | API / Backend | This is a usability layer only; API authorization remains authoritative. [VERIFIED: app.py:283-312] |
| Public/private download enforcement | API / Backend | Browser / Client | Existing routes authorize public and private artifact classes independently. [VERIFIED: app.py:1300-1339,1606-1646,1850-1890] |
| Revocation/expiry enforcement | API / Backend | Browser / Client | The server deletes/invalidates sessions; the browser must handle the next protected-request 401. [VERIFIED: certmon/auth.py:220-235; app.py:283-300] |
| Role-visibility regression coverage | Browser / Client | API / Backend | The UAT defect is rendered behavior; current Flask/HTML tests do not execute the application in a browser. [VERIFIED: tests/test_ui_contract.py:39-81; 02-UAT.md, G-02-2] |

## Project Constraints (from AGENTS.md)

No AGENTS.md was present at the repository root when researched. [VERIFIED: workspace root inspection]

## Standard Stack

| Component | Version | Purpose | Decision |
|---|---:|---|---|
| Existing pytest | 9.1.1 | Unit, API, and HTML-contract tests | Retain it for focused/full regression. [VERIFIED: environment probe; pytest.ini] |
| Existing Flask test-client pattern | Existing | Backend authorization/session checks | Retain it; it cannot prove rendered UI visibility. [VERIFIED: tests/test_auth_api.py:17-129; tests/test_user_management.py:166-304] |
| Browser automation harness | Not installed | Execute JavaScript and inspect actual controls | Add as Wave 0 before the UI repair. [VERIFIED: environment probe; tests file inventory] |

No production dependency is required. Reuse authState, the existing CSRF fetch wrapper, permission identifiers, and public/private artifact routes. [VERIFIED: templates/index.html:1278-1296; certmon/permissions.py:9-18; app.py:1300-1339,1606-1646,1850-1890]

**Installation:** This research intentionally selects no external browser package. Wave 0 must choose an approved Python/browser integration, pin it in development requirements, and complete the package-legitimacy gate before installation. [ASSUMED]

## Package Legitimacy Audit

Not applicable: no external package is recommended or installed by this research. [VERIFIED: research scope]

## Architecture Patterns

### System Architecture Diagram

~~~text
Authenticated request
        |
        v
/api/auth/status -> AuthService -> permissions_for_roles(roles)
        |                                  |
        | user + effective permissions      v
        v                            session/database state
authState in browser
        |
        v
applyPermissionVisibility()
  |--> static tabs/actions
  |--> dynamically rendered controls
  |
  v
existing API authorize(Permission)
  |--> allowed response
  |--> 401 revoked/expired: clear UI and show sign-in
  +--> 403: retain backend protection
~~~

### Pattern 1: Server-Derived Visibility Contract

**Use:** Return effective permissions from the authenticated status endpoint, derive them with the existing server function, and map browser controls to those values. [VERIFIED: certmon/permissions.py:58-62; templates/index.html:1298-1336]

**Why:** The present client code checks literal role names for Administration visibility, which cannot implement the required union of multiple roles. [VERIFIED: templates/index.html:1398-1425; D-03 in 02-CONTEXT.md]

~~~javascript
// Proposed gap-closure pattern. This controls visibility only.
function applyPermissionVisibility(root = document) {
  const granted = new Set(authState.permissions || []);
  root.querySelectorAll('[data-required-permission]').forEach((node) => {
    node.hidden = !granted.has(node.dataset.requiredPermission);
  });
  updateTabVisibilityFromVisibleChildren(root);
}
~~~

Call this only after authentication and after renderers create permission-bound controls. Do not poll or relocate the UI during a valid session. [VERIFIED: D-09 in 02-CONTEXT.md]

### Pattern 2: Preserve Partially Accessible Tabs

Gate sections/actions inside Upload and Local CA independently. Keep a tab when one public workflow remains. The current Upload tab contains both a private Extron ZIP and manual download content, so Viewer must not lose Upload wholesale. [VERIFIED: templates/index.html:1015-1100; D-02, D-05, D-06, and D-07 in 02-CONTEXT.md]

### Pattern 3: Global Unauthorized-Session Recovery

At the fetch boundary, detect a protected API 401, clear protected in-memory UI state, and invoke the existing authentication initialization once. Do not retry the failed operation. The current wrapper adds CSRF headers but does not reset the UI on 401. [VERIFIED: templates/index.html:1285-1296,1298-1336]

### Anti-Patterns to Avoid

- Do not duplicate ROLE_PERMISSIONS in JavaScript. Use the server-derived union. [VERIFIED: certmon/permissions.py:25-62]
- Do not patch only Audit and the Extron ZIP. D-01 applies to static and dynamic controls. [VERIFIED: D-01 in 02-CONTEXT.md]
- Do not hide all of Upload from Viewer. It breaks public downloads. [VERIFIED: D-05 and D-06 in 02-CONTEXT.md]
- Do not replace API authorization with hidden controls. [VERIFIED: app.py:283-312,1606-1609,1850-1853,1887-1890]
- Do not reopen build publication or Phase 05 direct SFTP/SIS work. [VERIFIED: 02-CONTEXT.md, "Phase Boundary"; .planning/STATE.md, "Notes"]

## Don't Hand-Roll

| Problem | Do not build | Use instead | Why |
|---|---|---|---|
| Role union | A second browser role map | Existing permissions_for_roles exposed in auth status | A duplicate can drift and violates D-03. [VERIFIED: certmon/permissions.py:25-62] |
| Backend authorization | UI-only restrictions | Existing authorize checks | The server already returns 403 for denied permissions. [VERIFIED: certmon/permissions.py:73-82; app.py:310-312] |
| Session revocation | Browser timers/polling | Existing session delete/expiry plus next-request 401 cleanup | Server enforcement is per protected request. [VERIFIED: certmon/auth.py:220-235; certmon/db.py:159-234] |
| Artifact classification | New download API | Existing public/private artifact routes | They already isolate public artifacts from private key material. [VERIFIED: app.py:1850-1890] |

## Role Matrix for Browser Validation

| Case | Required visible behavior | Required absent behavior |
|---|---|---|
| Desktop/local | Existing Devices, Renewals, Local CA, and Upload without sign-in | Server sign-in gate. [VERIFIED: certmon/config.py:47-79; tests/test_auth_api.py:17-22] |
| Viewer | D-04/D-05 public data and artifacts; Upload remains if public content exists | Audit, private-key controls, Extron combined PEM/ZIP, Toolbelt list/run, user admin, encrypted CA backup, full server backup. [VERIFIED: D-04 through D-08 in 02-CONTEXT.md] |
| Operator | Viewer content plus effective permitted actions | Private/audit/admin/backup controls unless an additional role grants them. [VERIFIED: certmon/permissions.py:31-36] |
| CA admin | Viewer content plus Local CA management | Private/audit/admin/backup controls unless an additional role grants them. [VERIFIED: certmon/permissions.py:38-43] |
| Security admin | Private export, audit, and full-server-backup controls | User management unless also admin. [VERIFIED: certmon/permissions.py:45-52] |
| Admin | Existing authorized application/admin workflows | No removal of local full-permission behavior. [VERIFIED: certmon/permissions.py:21,54] |
| Multi-role | Union of all role permissions | Any action outside that union. [VERIFIED: certmon/permissions.py:58-62; D-03 in 02-CONTEXT.md] |

### Public Versus Private Download Cases

<!-- DATA_B6T1Z8KR_START -->
Public route allowed names: {"certificate.pem", "chain.pem", "full-chain.pem", "request.csr"}.
Private route allowed names: {"private-key.pem", "combined.pem"}.
<!-- DATA_B6T1Z8KR_END -->

[VERIFIED: app.py:1850-1890]

Browser coverage must also prove public Local CA/trust-bundle access and absence of private material. The all-Extron ZIP is a private route and must be absent for Viewer. [VERIFIED: app.py:1300-1339,1606-1646; tests/test_local_ca_server_mode.py:15-60]

## Common Pitfalls

### Static control remains after correct backend denial

**What goes wrong:** Viewer sees Audit or the Extron ZIP and receives a permission error after clicking. [VERIFIED: 02-UAT.md, G-02-2]

**Avoidance:** Centralize effective-permission visibility for every static and rendered control. [ASSUMED]

### Mixed-access tab disappears

**What goes wrong:** Hiding Upload to remove deployment/private controls removes retained public downloads. [VERIFIED: D-05 and D-06 in 02-CONTEXT.md]

**Avoidance:** Hide sections/actions, then hide the tab only when no allowed child remains. [ASSUMED]

### Revoked browser remains visually authenticated

**What goes wrong:** The server denies the next request but protected screen state remains. [ASSUMED]

**Avoidance:** Convert the next protected 401 into a one-time sign-in reset and clear protected UI state. [ASSUMED]

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Framework | pytest 9.1.1. [VERIFIED: environment probe] |
| Config | pytest.ini. [VERIFIED: pytest.ini] |
| Existing focused command | py -3 -m pytest tests/test_ui_contract.py tests/test_user_management.py tests/test_auth_api.py tests/test_rbac.py tests/test_audit_api.py tests/test_local_ca_server_mode.py -q |
| Existing full command | py -3 -m pytest -m "not acme_staging" -q |
| Research result | These commands were not run during this research; no test result is claimed. [VERIFIED: research session actions] |

### Existing Coverage and Gap

Existing tests cover Viewer denial for audit/renewal, public/private artifact routes, trust-bundle behavior, and session invalidation after role change, disablement, or password reset. [VERIFIED: tests/test_audit_api.py:69-84; tests/test_user_management.py:83-107,235-276; tests/test_ca_api.py:202-260; tests/test_local_ca_server_mode.py:15-60]

The UI-contract suite reads HTML and asserts strings/fragments; it does not execute JavaScript in a browser. [VERIFIED: tests/test_ui_contract.py:39-81,149-174,328-363]

No browser automation package, browser-driver command, browser test file, or browser/server fixture was found. [VERIFIED: environment probe; tests file inventory]

### Wave 0 Browser Infrastructure

Before product-code repair work:

- Choose and legitimacy-audit one Python/browser test integration and install its matching browser runtime. [ASSUMED]
- Add a fixture that starts server mode on an ephemeral local port with a temporary CERTMON_DATA_DIR, then reliably disposes server/browser state. [ASSUMED]
- Add helpers for first-admin setup, user creation, login, and download capture without storing private material in fixtures. [ASSUMED]
- Add tests/test_rbac_browser.py to execute JavaScript and assert actual visibility. [ASSUMED]

**Required command after Wave 0:**

~~~powershell
py -3 -m pytest tests/test_rbac_browser.py -q
~~~

This command is not runnable today because the file and browser runner do not exist. [VERIFIED: environment probe; tests file inventory]

### Phase Behaviors -> Test Map

| Behavior | Test type | Command | Status |
|---|---|---|---|
| Viewer lacks Audit and Extron ZIP UI | Browser E2E | py -3 -m pytest tests/test_rbac_browser.py -q | Wave 0 gap |
| Public links remain; private controls/routes remain denied | Browser E2E plus API | py -3 -m pytest tests/test_rbac_browser.py tests/test_ca_api.py tests/test_local_ca_server_mode.py -q | Browser gap; API exists |
| Partially accessible tab stays visible | Browser E2E | py -3 -m pytest tests/test_rbac_browser.py -q | Wave 0 gap |
| Multi-role union drives visibility | Browser E2E plus unit | py -3 -m pytest tests/test_rbac_browser.py tests/test_permissions.py -q | Browser gap |
| Role change, disablement, reset revoke and clear UI on next request | Browser E2E plus API | py -3 -m pytest tests/test_rbac_browser.py tests/test_user_management.py tests/test_auth_api.py -q | Browser gap; API exists |
| Expired session returns to sign-in and clears UI | Browser E2E plus auth API | py -3 -m pytest tests/test_rbac_browser.py tests/test_auth_api.py -q | Browser gap |
| Desktop mode remains ungated | Browser E2E plus config/API | py -3 -m pytest tests/test_rbac_browser.py tests/test_server_mode_config.py tests/test_auth_api.py -q | Browser gap; config/API exists |

### Required Browser Scenarios

1. Viewer: assert Audit, private-key, Extron ZIP, Toolbelt, backup, and administration controls are absent; assert retained public content/downloads are present when data exists.
2. Multi-role: assert the visible set equals the effective union, not any single role shortcut.
3. Upload: assert it remains for public downloads and does not request inaccessible deployment-only listings.
4. Revocation: change roles, disable, and reset a target in a second authenticated context; on target's next protected request, assert sign-in and cleared protected UI.
5. Expiry: invalidate/expire target session, make one protected request, and assert the same reset without polling.
6. Desktop: start without server mode and assert normal local UI with no sign-in gate.

### Sampling Rate

- Per repair task: py -3 -m pytest tests/test_ui_contract.py tests/test_permissions.py tests/test_user_management.py tests/test_auth_api.py tests/test_rbac.py tests/test_audit_api.py tests/test_ca_api.py tests/test_local_ca_server_mode.py -q
- Per browser task: py -3 -m pytest tests/test_rbac_browser.py -q, after Wave 0.
- Phase gate: py -3 -m pytest -m "not acme_staging" -q plus the browser matrix. Do not repeat publication/build work. [VERIFIED: 02-04-PLAN.md, "Verification"; 02-CONTEXT.md, "Phase Boundary"]

## Security Domain

Security enforcement is enabled because config does not set security_enforcement to false. [VERIFIED: .planning/config.json]

| ASVS category | Applies | Standard control |
|---|---|---|
| V2 Authentication | Yes | Existing authenticated status/login routes and browser reset on protected 401. [VERIFIED: app.py:500-584; certmon/auth.py:202-239] |
| V3 Session Management | Yes | Existing deletion on role change, disablement, reset, and expiry. [VERIFIED: certmon/auth.py:125-170,220-239; certmon/db.py:159-234] |
| V4 Access Control | Yes | Existing authorize checks; UI visibility does not replace them. [VERIFIED: certmon/permissions.py:73-82; app.py:283-312] |
| V5 Input Validation | Yes | Existing user/auth validation remains unchanged. [VERIFIED: certmon/auth.py:125-200; app.py:587-764] |
| V6 Cryptography | No new work | Do not alter key/vault/backup behavior. [VERIFIED: D-07 in 02-CONTEXT.md] |

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|---|---|---|
| A1 | A selected browser integration can host the app and inspect rendered controls. | Wave 0 | Harness design must change. |
| A2 | A guarded 401 handler can clear protected in-memory UI without login/setup loops. | Architecture | Needs focused implementation/test design. |
| A3 | Permission data attributes plus a post-render pass are the least invasive implementation. | Architecture | An equivalent central hook may fit the template better. |

## Open Questions

1. **RESOLVED (planning follow-up, 2026-10-02): Which approved browser runner should Wave 0 install?**
   - Initial research-date fact: no runner was installed/configured when this research was produced. [VERIFIED: environment probe; tests file inventory]
   - Later resolution: Plan 02-05 selects and legitimacy-audits `pytest-playwright==0.9.0` with `playwright==1.63.0`, using Chromium and the existing pytest runner. Browser binaries are installed separately with `py -3 -m playwright install chromium`; dependencies remain development-only. [RESOLVED: `.planning/phases/02-shared-server-mode/02-05-PLAN.md`, Task 05-01]
   - The initial environment observation is retained as historical research evidence; the runner choice is no longer open.

## Environment Availability

| Dependency | Required by | Available | Version | Fallback |
|---|---|---|---|---|
| Python launcher | pytest commands | Yes | Python 3.14.6 [VERIFIED: environment probe] | - |
| pytest | Existing tests | Yes | 9.1.1 [VERIFIED: environment probe] | - |
| Browser test runner/runtime | Rendered RBAC tests | No [VERIFIED: environment probe] | - | Wave 0 selection/install |
| Browser test file/fixture | Rendered RBAC tests | No [VERIFIED: tests file inventory] | - | Wave 0 implementation |

**Missing dependency with no current fallback:** a JavaScript-capable browser runner. Flask test-client and HTML-string contracts cannot verify rendered visibility or 401 UI cleanup. [VERIFIED: tests/test_ui_contract.py:39-81; environment probe]

## Sources

### Primary (HIGH confidence)

- certmon/permissions.py:9-82 - permission enum, role mapping, union, and authorization.
- certmon/auth.py:125-239 and certmon/db.py:159-234 - user mutation, revocation, and expiry.
- app.py:283-312,500-768,1300-1339,1606-1646,1850-1890 - middleware and artifact boundaries.
- templates/index.html:866-871,1048-1050,1278-1425,2490-2504 - current static UI, auth state, and role-name gating.
- Existing focused tests and Phase 02 context/UAT/verification/plans - test inventory, exact gap, and scope.

### Secondary (MEDIUM confidence)

None. No internet research was needed for local behavior.

### Tertiary (LOW confidence)

Browser-harness implementation details, recorded in the Assumptions Log.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - local test stack and missing browser infrastructure inspected.
- Architecture: HIGH - permission, session, API, and template seams opened this session.
- Pitfalls: HIGH - UAT failure and static/role-name control patterns establish the risks.

**Research date:** 2026-10-02
**Valid until:** Until the RBAC UI repair changes these inspected surfaces.
