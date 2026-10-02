---
phase: 02-shared-server-mode
plan: "02-05"
subsystem: testing
tags: [pytest, playwright, Chromium, CI, historical-reconciliation]
requires:
  - phase: 02-shared-server-mode
    provides: existing server-mode authentication workflow and Build 15 UAT evidence
provides:
  - Chromium pytest harness backed by an isolated live CertMon server
  - Windows CI lifecycle for pinned browser test dependencies
  - Factual historical record for plan 02-04 without replaying publication
affects: [02-06, 02-07, G-02-2]
actuals:
  tokens: 3724
  tasks: 2
  commits: 3
tech-stack:
  added: [pytest-playwright==0.9.0, playwright==1.63.0, Chromium]
  patterns:
    - "Browser tests use a function-scoped loopback server and a temporary CertMon data directory."
    - "CI installs browser binaries separately from pinned development dependencies."
key-files:
  created:
    - tests/test_rbac_browser.py
    - .github/workflows/test.yml
    - .planning/phases/02-shared-server-mode/02-04-SUMMARY.md
    - .planning/phases/02-shared-server-mode/02-05-SUMMARY.md
  modified:
    - requirements-dev.txt
    - tests/conftest.py
key-decisions:
  - "Keep Playwright and Chromium development-only, outside production dependencies and executable builds."
  - "Preserve UAT 5 / G-02-2 as unresolved while reconciling historical Build 15 evidence."
patterns-established:
  - "Rendered CertMon behavior is covered through Playwright against an ephemeral HTTP server, not by HTML-only assertions."
  - "Historical publication documentation cites retained evidence rather than replaying remote actions."
requirements-completed: []
coverage:
  - id: D1
    description: "Chromium executes the server-mode first-admin authentication transition against an isolated live CertMon instance."
    requirement: G-02-2
    verification:
      - kind: automated_ui
        ref: tests/test_rbac_browser.py#test_browser_harness_executes_certmon_javascript
        status: pass
    human_judgment: false
  - id: D2
    description: "Desktop mode renders its main UI without an authentication gate in Chromium."
    requirement: G-02-2
    verification:
      - kind: automated_ui
        ref: tests/test_rbac_browser.py#test_browser_harness_executes_certmon_javascript_desktop_mode
        status: pass
    human_judgment: false
  - id: D3
    description: "The Build 15 historical record keeps UAT 4 and 9 passed and UAT 5 / G-02-2 unresolved."
    requirement: G-02-2
    verification:
      - kind: other
        ref: .planning/phases/02-shared-server-mode/02-04-SUMMARY.md
        status: pass
    human_judgment: false
duration: continuation session
completed: 2026-10-02
status: complete
---

# Phase 02 Plan 05: Browser Harness and Historical Reconciliation Summary

**Pinned Playwright Chromium coverage now executes CertMon's real JavaScript against isolated server and desktop instances, while Build 15 history remains truthful about the open Viewer visibility defect.**

## Performance

- **Duration:** Continuation session
- **Completed:** 2026-10-02
- **Tasks:** 2/2
- **Files created or modified:** 6

## Accomplishments

- Added a development-only Playwright/Chromium pytest harness with function-scoped live CertMon servers, isolated temporary data, and deterministic teardown.
- Added Windows CI installation of `requirements-dev.txt`, Chromium, and the complete non-staging pytest suite.
- Captured the missing 02-04 historical summary from retained evidence: published commit `e2e806d50f3f5f6a99eb32b3dea5535d5f9fab7c`, GitHub Actions run `32497863521`, build 15, and `CertMon-Windows`.
- Kept UAT 4 and UAT 9 passed and UAT 5 / G-02-2 explicitly unresolved; this plan establishes test infrastructure and does not repair product role visibility.

## Verification

- Task 1 tracer: `py -3 -m pytest tests/test_rbac_browser.py -k "browser_harness_executes_certmon_javascript or desktop_mode" -q` passed with `2 passed in 7.64s` before the approved tracer checkpoint.
- Task 2: the plan's Python assertion against `02-04-SUMMARY.md` passed, confirming all required Build 15 identifiers and the unresolved G-02-2 record.
- The approved tracer was not rerun during this continuation, per the user's explicit instruction.

## Task Commits

1. **Task 1: Run one real CertMon authentication path in Chromium** - `142ad32` (RED tests), `e90bf72` (GREEN harness)
2. **Task 2: Reconcile the historical 02-04 record without replaying it** - `816bedd` (docs)

## Files Created/Modified

- `requirements-dev.txt` - pinned development-only Playwright dependencies.
- `tests/conftest.py` - isolated loopback CertMon server fixture.
- `tests/test_rbac_browser.py` - Chromium server-mode and desktop-mode smoke coverage.
- `.github/workflows/test.yml` - Windows dependency, Chromium, and non-staging test lifecycle.
- `.planning/phases/02-shared-server-mode/02-04-SUMMARY.md` - factual Build 15 publication and UAT record.
- `.planning/phases/02-shared-server-mode/02-05-SUMMARY.md` - this plan's execution record.

## Decisions Made

- Used the plan-approved Chromium-only Playwright stack through existing pytest, with the browser installed as a distinct local and CI lifecycle step.
- Recorded 02-04 from immutable identifiers already present in planning evidence instead of restarting remote publication work.
- Did not mark G-02-2 complete: its role-visibility repair and fresh browser UAT belong to later plans.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added the Chromium headless-shell installation needed by the CI browser runtime.**
- **Found during:** Task 1 (Chromium harness)
- **Issue:** The local Chromium runtime installation did not include the headless shell required by the test environment.
- **Fix:** Included the required headless-shell installation in the existing Chromium CI lifecycle.
- **Files modified:** `.github/workflows/test.yml`
- **Verification:** The tracer completed with `2 passed in 7.64s`.
- **Committed in:** `e90bf72`

---

**Total deviations:** 1 auto-fixed (1 blocking issue)
**Impact on plan:** The change remains development-only and makes the specified browser lifecycle runnable; it does not alter product behavior or publication state.

## Issues Encountered

The historical Build 15 commit is not present in this checkout's object database. Its immutable identifier and release outcome were already retained in `02-UAT.md` and `STATE.md`; no remote lookup, push, build, or UAT rerun was needed.

## Auth Gates

None.

## Known Stubs

None.

## Next Phase Readiness

Plans 02-06 and 02-07 can use the isolated browser boundary to implement and retest the Viewer visibility repair. G-02-2 remains open, and Phase 02 is not complete.

## Self-Check: PASSED

- `142ad32`, `e90bf72`, and `816bedd` exist in local Git history.
- `02-04-SUMMARY.md` and this summary exist on disk.
- No Phase 05, product, `STATE.md`, `ROADMAP.md`, or UAT file was staged by this continuation.

---
*Phase: 02-shared-server-mode*
*Completed: 2026-10-02*
