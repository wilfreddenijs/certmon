---
phase: 02
slug: shared-server-mode
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-10-02
---

# Phase 02 - Gap-Closure Validation Strategy

This is a validation contract, not evidence of tests having passed. It supplements
the nine passed UAT cases and targets the remaining G-02-2 visibility gap. Historical
plans 02-01 through 02-04 are retained; their publication work is not repeated.

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | Existing pytest plus pinned `pytest-playwright==0.9.0` / `playwright==1.63.0` with Chromium, established by 02-05-01 |
| Config file | pytest.ini |
| Quick run command | `py -3 -m pytest tests/test_permissions.py tests/test_rbac.py tests/test_auth_api.py tests/test_user_management.py tests/test_ui_contract.py tests/test_audit_api.py tests/test_ca_api.py tests/test_local_ca_server_mode.py -q` |
| Browser install command | `py -3 -m playwright install chromium` (development/CI only; 02-05-01) |
| Browser run command | `py -3 -m pytest tests/test_rbac_browser.py -q` (created by 02-05-01, expanded by 02-06 and 02-07) |
| Full suite command | `py -3 -m pytest -m "not acme_staging" -q` |
| Estimated runtime | Not measured; executor records duration before setting a sampling budget |

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
| Browser execution boundary | G-02-2 | 02-05-01 | False browser confidence | Real Chromium executes CertMon auth and desktop JavaScript against isolated live servers | Browser | `py -3 -m pytest tests/test_rbac_browser.py -k "browser_harness_executes_certmon_javascript or desktop_mode" -q` | Planned in 02-05 | Pending |
| Permission contract | D-03 | 02-06-01 | Access-control drift | Server-derived additive permissions; desktop retains full local behavior | API/unit | `py -3 -m pytest tests/test_rbac.py tests/test_auth_api.py -q` | Existing files; assertions planned | Pending |
| Restricted UI | G-02-2, D-01, D-02, D-07, D-08 | 02-06-02, 02-07-01 | Unauthorized controls/data | Static and dynamic controls hidden; tabs retained only with allowed content | Browser | `py -3 -m pytest tests/test_rbac_browser.py -q` | Planned in 02-05 | Pending |
| Public downloads | D-04, D-05, D-06 | 02-06-01, 02-06-02, 02-07-01 | Secret leakage | Public catalog/downloads work without deploy-only requests; keys remain denied | Browser/API | `py -3 -m pytest tests/test_rbac_browser.py tests/test_ca_api.py tests/test_local_ca_server_mode.py -q` | Planned in 02-05 | Pending |
| Multi-role matrix | D-03 | 02-07-01 | Incorrect role shortcut | Viewer/operator/ca_admin/security_admin/admin and unions match effective rights | Browser/unit | `py -3 -m pytest tests/test_rbac_browser.py tests/test_permissions.py -q` | Planned in 02-05 | Pending |
| Session lifecycle | D-09, D-10 | 02-06-03, 02-07-01 | Stale privileged state | No permission polling; next protected 401 clears UI and shows sign-in without replay | Browser/API | `py -3 -m pytest tests/test_rbac_browser.py tests/test_user_management.py tests/test_auth_api.py -q` | Planned in 02-05 | Pending |
| Desktop regression | Phase boundary | 02-05-01, 02-07-01 | Accidental local restriction | Existing standalone operation remains available without sign-in | Browser/API | `py -3 -m pytest tests/test_rbac_browser.py tests/test_server_mode_config.py tests/test_auth_api.py -q` | Planned in 02-05 | Pending |
| Full regression evidence | G-02-2, D-01 through D-10 | 02-07-02 | False closure | Focused and full non-staging suites pass with zero browser skips/xfails before UAT | Full suite | `py -3 -m pytest -m "not acme_staging" -q` | Existing suite plus planned browser file | Pending |

## Wave 0 Requirements

- [ ] Execute 02-05-01 with the verified Microsoft Playwright Python stack pinned in `requirements-dev.txt`; install Chromium separately with `py -3 -m playwright install chromium`.
- [ ] Add `tests/test_rbac_browser.py` and `live_certmon` browser/server fixtures using ephemeral ports and temporary data directories, with reliable cleanup.
- [ ] Seed existing public/private artifacts and role accounts without real credentials or production CA material.
- [ ] Establish a smoke test that executes JavaScript in the actual app and records a real pass/fail; do not substitute HTML-string tests.
- [ ] Include browser dependency installation in the test/CI path so full-suite success cannot silently exclude this coverage.

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

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Instructions |
|----------|-------------|------------|--------------|
| Final role-based usability acceptance | G-02-2, D-01 through D-10 | User acceptance of repaired workflow | Viewer: Devices/Renewals/public CA/public Upload downloads remain; Audit, administration, private keys/PEM ZIP and deployment controls are absent. Check an additive role account and admin. Trigger expiry/revocation on the next request and verify sign-in cleanup. |

Retain the passed UAT 4 and 9 results. No build or publication is authorized by
this planning document; a later build requires the normal user gate.

## Validation Sign-Off

- [ ] Every repair task maps to automated verification or Wave 0 prerequisites.
- [ ] No three consecutive tasks lack automated feedback.
- [ ] Browser tests cover each standalone role, additive roles, downloads, requests, and session cleanup.
- [ ] Existing backend denials remain tested independently of visibility.
- [ ] Full suite and focused timings recorded; no watch mode or silent skips.
- [ ] `nyquist_compliant: true` and validated status set only after actual validation evidence.

**Approval:** Pending implementation and validation; planning is not test sign-off.
