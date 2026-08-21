---
status: diagnosed
trigger: "Test 4: pressing Enter should submit authentication, but only clicking the button works."
created: 2026-08-21T16:30:00+02:00
updated: 2026-08-21T16:30:00+02:00
goal: find_root_cause_only
---

## Current Focus

hypothesis: "The tested build predates the form-based authentication UI."
test: "Compare the remote branch template used by GitHub builds with local HEAD and run the UI contract tests."
expecting: "Remote has a click-only button while local HEAD has a submit form and passing contract coverage."
next_action: "Publish local HEAD and build a new executable for UAT."

## Symptoms

expected: "Pressing Enter submits the active login or first-admin setup action exactly once."
actual: "Clicking the on-screen action works, but pressing Enter does nothing."
errors: "None reported."
reproduction: "UAT test 4 in the currently downloaded GitHub build."

## Eliminated

- Runtime event-handler defect in current source: the current template uses a form submit handler and a submit button.

## Evidence

- Remote commit `e89fa8d` renders `auth-submit` as a click-only button outside a form.
- Local commit `60f86cf` wraps the fields in `auth-form` with `onsubmit` and uses `type=submit`.
- `tests/test_ui_contract.py` verifies the form semantics and passes on local HEAD.
- The local branch is ahead of the remote branch, so the tested GitHub build cannot contain the local change.

## Resolution

root_cause: "The tested executable was built from remote commit e89fa8d and does not contain local commit 60f86cf, which adds keyboard Enter submission through native form semantics."
fix: "Push the current branch and create a new build; no additional product-code change is required for this finding."
verification: "Local source comparison and passing UI contract tests; browser UAT remains after rebuilding."
files_changed: []
