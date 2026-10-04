---
phase: 02
slug: shared-server-mode
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-10-02
---

# Phase 02 - Gap-Closure Validation Strategy

## Final Acceptance (2026-10-04)

Build 23 human UAT passed all final six retest items; UAT total is 10/10 passed.
G-02-2 is resolved. Latest full CI run 37218519929: 288 passed, one external
ACME staging test deselected in 83.07s. Build run 37218527033 succeeded on
`5da496d1501feafbb6d881d89e82aab587c4d5e8`. Earlier tables below are historical
measured evidence. Build-22's intermittent SQLite file-comparison failure passed
on the subsequent run with unchanged backup code; keep as test-stability risk.

This validation contract now includes measured automated test evidence below. It
does not replace human acceptance. It supplements the nine passed UAT cases and
targets the remaining G-02-2 visibility gap. Historical
plans 02-01 through 02-04 are retained; their publication work is not repeated.

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | Existing pytest plus pinned `pytest-playwright==0.9.0` / `playwright==1.63.0` with Chromium, established by 02-05-01 |
| Config file | pytest.ini |
| Focused regression command | `py -3 -m pytest tests/test_permissions.py tests/test_rbac.py tests/test_auth_api.py tests/test_user_management.py tests/test_ui_contract.py tests/test_audit_api.py tests/test_ca_api.py tests/test_local_ca_server_mode.py tests/test_rbac_browser.py -q` |
| Browser install command | `py -3 -m playwright install chromium` (development/CI only; 02-05-01) |
| Browser run command | `py -3 -m pytest tests/test_rbac_browser.py -q` (created by 02-05-01, expanded by 02-06 and 02-07) |
| Full suite command | `py -3 -m pytest -m "not acme_staging" -q` |
| Measured regression runtime | Browser matrix: 113.58s; focused regression: 147.27s; full non-staging suite: 232.45s |

## Sampling Rate

- After every repair task: run its focused tests and the quick command.
- After every UI task: run the affected browser cases once Wave 0 exists.
- After every plan wave and before verification: full suite and browser matrix must pass.
- No watch-mode commands. Do not silently skip missing browser infrastructure.
- Target focused feedback latency: 60 seconds; measure and narrow cases if necessary.

## Verification Map

The planner must assign concrete task IDs and waves to these cases in executable
plans and keep this map synchronized. Requirement references use the existing
G-02-2 and D-01 through D-10 identifiers; REQUIREMENTS.md has no numbered IDs.

| Case | Requirement | Plan / Task | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|------|-------------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| Browser execution boundary | G-02-2 | 02-05-01, 02-07-01 | False browser confidence | Real Chromium executes CertMon auth and desktop JavaScript against isolated live servers | Browser | `py -3 -m pytest tests/test_rbac_browser.py -q` | Yes | Passed: 13 passed in 113.58s; 0 skipped, 0 xfailed |
| Permission contract | D-03 | 02-06-01, 02-07-02 | Access-control drift | Server-derived additive permissions; desktop retains full local behavior | API/unit | Focused regression command | Yes | Passed within 94 focused tests in 147.27s |
| Restricted UI | G-02-2, D-01, D-02, D-07, D-08 | 02-06-02, 02-07-01 | Unauthorized controls/data | Static and dynamic controls hidden; tabs retained only with allowed content | Browser | `py -3 -m pytest tests/test_rbac_browser.py -q` | Yes | Passed: 13 passed in 113.58s; 0 skipped, 0 xfailed |
| Public downloads | D-04, D-05, D-06 | 02-06-01, 02-06-02, 02-07-01 | Secret leakage | Public catalog/downloads work without deploy-only requests; keys remain denied | Browser/API | Focused regression command | Yes | Passed within 94 focused tests in 147.27s |
| Multi-role matrix | D-03 | 02-07-01 | Incorrect role shortcut | Viewer/operator/ca_admin/security_admin/admin and unions match effective rights | Browser/unit | `py -3 -m pytest tests/test_rbac_browser.py -q` | Yes | Passed: 13 passed in 113.58s; 0 skipped, 0 xfailed |
| Session lifecycle | D-09, D-10 | 02-06-03, 02-07-01 | Stale privileged state | No permission polling; next protected 401 clears UI and shows sign-in without replay | Browser/API | `py -3 -m pytest tests/test_rbac_browser.py -q` | Yes | Passed: 13 passed in 113.58s; 0 skipped, 0 xfailed |
| Desktop regression | Phase boundary | 02-05-01, 02-07-01 | Accidental local restriction | Existing standalone operation remains available without sign-in | Browser/API | `py -3 -m pytest tests/test_rbac_browser.py -q` | Yes | Passed: 13 passed in 113.58s; 0 skipped, 0 xfailed |
| Full regression evidence | G-02-2, D-01 through D-10 | 02-07-02 | False closure | Focused and full non-staging suites pass with zero browser skips/xfails before UAT | Full suite | `py -3 -m pytest -m "not acme_staging" -q` | Yes | Passed: 286 passed, 1 deselected (`acme_staging`) in 232.45s; 0 skipped, 0 xfailed |

## Wave 0 Requirements

- [x] Execute 02-05-01 with the verified Microsoft Playwright Python stack pinned in `requirements-dev.txt`; install Chromium separately with `py -3 -m playwright install chromium`.
- [x] Add `tests/test_rbac_browser.py` and `live_certmon` browser/server fixtures using ephemeral ports and temporary data directories, with reliable cleanup.
- [x] Seed existing public/private artifacts and role accounts without real credentials or production CA material.
- [x] Establish a smoke test that executes JavaScript in the actual app and records a real pass/fail; do not substitute HTML-string tests.
- [x] Include browser dependency installation in the test/CI path so full-suite success cannot silently exclude this coverage.

## Executable Task Map

| Task | Deliverable | Depends on | Evidence gate |
|------|-------------|------------|---------------|
| 02-05-01 | Pinned Playwright harness, live server fixture, Chromium smoke, CI lifecycle | none | Browser smoke command passes without skips |
| 02-05-02 | Evidence-based 02-04 summary | none | Build-15 identifiers and unresolved G-02-2 are present |
| 02-06-01 | Effective-permission status, safe public catalog, authoritative mutation checks | 02-05 | Focused RBAC/auth/CA API suites pass |
| 02-06-02 | Static/dynamic permission visibility, mixed Upload, guarded loaders | 02-06-01 | Focused UI/browser visibility and request tests pass |
| 02-06-03 | One-shot next-protected-401 cleanup | 02-06-02 | Browser revocation and auth API tests pass |
| 02-07-01 | All roles, additive unions, artifacts, sessions, and desktop matrix | 02-06 | Complete browser file passes with zero skips/xfails |
| 02-07-02 | Focused/full regression evidence | 02-07-01 | Full non-staging suite passes and timings are recorded |
| 02-07-03 | Human UAT 5 only | 02-07-02 | Fresh approval or exact remaining failure; UAT 4/9 preserved |

## Automated Evidence: 02-07-02

Executed on 2026-10-02 after the approved 02-07-01 coverage-strengthening commits.
Chromium was available and the complete browser file was collected and executed.

| Task | Exact command | Result | Browser skips / xfails |
|------|---------------|--------|------------------------|
| 02-07-01 matrix regression | `py -3 -m pytest tests/test_rbac_browser.py -q` | 13 passed in 113.58s | 0 / 0 |
| 02-07-02 focused regression | `py -3 -m pytest tests/test_permissions.py tests/test_rbac.py tests/test_auth_api.py tests/test_user_management.py tests/test_ui_contract.py tests/test_audit_api.py tests/test_ca_api.py tests/test_local_ca_server_mode.py tests/test_rbac_browser.py -q` | 94 passed in 147.27s | 0 / 0 |
| 02-07-02 full non-staging regression | `py -3 -m pytest -m "not acme_staging" -q` | 286 passed, 1 deselected (`acme_staging`) in 232.45s | 0 / 0 |

The browser matrix covers the five standalone roles, the `viewer + ca_admin` and
`operator + security_admin` effective-permission unions, public-artifact retrieval
and private-data exclusion, all four next-request session cases, and desktop mode.
The next-request cases advance the controlled browser clock by 15 seconds before
the protected action and assert no status polling; this evidence does not rely on
earlier two-RAF timing observations.

These automated results satisfy the Wave 0 and Nyquist preconditions for the
human UAT 5 checkpoint only. They do not change UAT 4 or UAT 9, resolve G-02-2,
or constitute human approval.

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Instructions |
|----------|-------------|------------|--------------|
| Final role-based usability acceptance | G-02-2, D-01 through D-10 | User acceptance of repaired workflow | Viewer: Devices/Renewals/public CA/public Upload downloads remain; Audit, administration, private keys/PEM ZIP and deployment controls are absent. Check an additive role account and admin. Trigger expiry/revocation on the next request and verify sign-in cleanup. |

Retain the passed UAT 4 and 9 results. No build or publication is authorized by
this planning document; a later build requires the normal user gate.

## Validation Sign-Off

- [x] Every repair task maps to automated verification or Wave 0 prerequisites.
- [x] No three consecutive tasks lack automated feedback.
- [x] Browser tests cover each standalone role, additive roles, downloads, requests, and session cleanup.
- [x] Existing backend denials remain tested independently of visibility.
- [x] Full suite and focused timings recorded; no watch mode or silent skips.
- [x] `nyquist_compliant: true` and validated status set only after actual validation evidence.

**Approval:** Automated validation complete. Human UAT 5 remains the blocking sign-off;
planning and regression evidence are not a UAT result.

## CI Follow-Up: 2026-10-03

GitHub test run 37071945639 on f405625 failed with 3 session-test failures,
283 passes and one staging case deselected. The session snapshot was taken after
the login shell appeared but before loadData finished rendering device controls.
The sign-in test helper now waits for the rendered device count before capturing
the snapshot. The four session cases passed in 45.64s after that correction.

Rendered-visibility assertions also exposed a real CSS issue: display:flex could
override the native hidden attribute on permission-restricted selection controls.
The new assertion failed for Viewer before the fix (1 failed, 12 deselected in
18.09s). A global hidden rule now enforces display:none; assertions check actual
browser visibility as well as permission metadata.

The first full run with both corrections had an unrelated initial-admin
network failure (Failed to fetch before the setup POST reached the server):
1 failed, 285 passed, 1 deselected in 226.27s. The unchanged suite was repeated:
`py -3 -m pytest -m "not acme_staging" -q` returned 286 passed, 1 deselected in
226.98s. No skips or xfails were introduced. Remote CI confirmation is pending;
the original local pass is not a substitute for it. Human UAT 5 remains open.
