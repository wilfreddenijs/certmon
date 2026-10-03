# Plan 02-07 - Browser Matrix Tracer Checkpoint

Status: automated work complete; awaiting human UAT 5 (task 07-03)
Type: human-verify (blocking tracer feedback gate)
Date: 2026-10-03
Executor: 01a0fc80-cad9-7300-83e0-94a498adf0d5

## Execution Evidence

- `6695f6e`: failing RBAC browser matrix tests.
- `0169c63`: browser matrix adjustments and desktop visibility fix.
- Files: tests/test_rbac_browser.py, templates/index.html.
- Executor command: `py -3 -m pytest tests/test_rbac_browser.py -q`.
- Executor result: 13 passed in 84.03s, no skips or xfails.
- Session subset: 4 passed, 9 deselected in 36.85s.
- Desktop fix makes hasPermission respect locally granted permissions without requiring a server-mode login; backend permission boundaries unchanged.

## Historical Orchestrator Review (Resolved)

The original 13 passes were not complete acceptance evidence for task 07-01. The following review items were addressed by 0edc25f and 91f8a74:

- Public artifact test checks four Upload link URLs and absent missing links, but does not retrieve public downloads or exercise CA certificate, trust bundle, Excel and devices.txt.
- Local CA and device/renewal dynamic controls are not seeded with sufficient existing state; static permission-tag checks cannot establish all dynamic behavior.
- Restricted request assertions omit the deployment-only `/api/certificates` catalog and other protected loaders.
- Role/audit request checks use role-name exceptions instead of the effective permission set; the admin case inadvertently asserts no audit requests.
- Session tests capture requests only after mutation and do not explicitly prove no background permission polling or unchanged UI before the next protected request.
- Private sentinel checks cover DOM only, not public response/download contents.

Those checks were strengthened without loosening runtime authorization or suppressing failures. Final browser and regression results are recorded below.

## Continuation

User selected option 1: strengthen the missing tests and then run regression tests. This authorizes the remaining automated work, not final human UAT 5 approval. Preserve prior task commits and continue with a fresh executor.

Coverage extension commit `0edc25f` retrieves all listed public downloads in Chromium, seeds populated information views and corrects permission-derived request assertions. Browser matrix: 13 passed in 120.70s, no skips/xfails. Additional commit `91f8a74` checks union loaders and advances the controlled browser clock 15 seconds before the next protected request; focused command `py -3 -m pytest tests/test_rbac_browser.py -k 'additive_roles or next_protected_request' -q`: 6 passed, 7 deselected in 69.22s. Syntax compilation of app.py, launcher.py and certmon/permissions.py passed.

Fresh executor `01a0fe95-17fe-7f10-aa32-118a090d432b` completed 07-02 under that explicit authorization; regression evidence is committed as `abb0791` in 02-VALIDATION.md:

- Browser matrix: 13 passed in 113.58s.
- Nine-file focused suite: 94 passed in 147.27s.
- Full non-staging suite: 286 passed, 1 deselected in 232.45s. The excluded case is the opt-in external ACME staging test, not a browser skip.
- Zero skips or xfails. Syntax and GSD schema/UI gates passed; codebase drift gate skipped because no structure map exists.
- 02-UAT.md is unchanged; passed UAT 4 and 9 remain intact.

## Human UAT 5

1. As admin, create a fresh Viewer through Administration and sign in through the normal UI.
2. Verify public Devices, Renewals, Local CA metadata and Upload downloads (including public certificate/chain/CSR and CA certificate/trust bundle/Excel/devices.txt where available).
3. Verify Audit, Administration, issuance, private key/combined PEM/ZIP, Toolbelt and backup controls are absent for Viewer; opening Upload must not raise a permission error.
4. Change supported roles from a separate admin context. On the target's next protected request verify sign-in and cleared protected UI; sign back in to verify the changed role and an additive-role union. Admin retains full authorized access.
5. Disable the user: next protected request signs out and disabled login fails. Re-enable and verify login resumes.
6. Reset the password: next protected request signs out, old password fails, new password succeeds.
7. Revoke a security_admin session, then use Audit as the next protected request. Verify sign-in, cleared protected content and no replay. Verify expired-session cleanup too.
8. Verify desktop mode opens without login and retains full local access.

Provide fresh observations or an exact remaining failure. Do not infer approval from option 1 authorizing automated work. If a new executable is needed, obtain separate push/build authorization before publishing. After human approval use a fresh executor to record only UAT 5/G-02-2 and complete the plan summary; preserve UAT 4/9.

No summary, phase completion, UAT 5 approval, push or executable build is implied. UAT 4 and 9 remain unchanged. Untracked .gsd/ and data/ are preserved.

## Publication and CI Follow-Up

User explicitly authorized push and test build delivery. Commit f405625 was pushed
and Windows build 20 succeeded (run 37071962284). Its separate Test CertMon run
37071945639 failed because session snapshots preceded initial rendering.

The follow-up synchronizes sign-in tests with completed device rendering and
adds actual rendered-visibility checks. Those checks exposed a CSS override of
hidden on selection controls, which is now fixed. Latest full local suite:
286 passed, 1 deselected in 226.98s. Remote verification and replacement executable
delivery follow; no human acceptance is inferred from these corrections.

## Human Retest Follow-Up (2026-10-03)

Build 21 CI passed (286 tests, one external staging test deselected). Human UAT
confirmed public Viewer tabs/downloads, forbidden private/security controls absent,
and successful Upload navigation. Role changes, account disable/enable, password
reset and Audit refresh after revocation behaved as expected; desktop opens without
login. Devices/Renewals navigation can show cached data until a protected request.

Remaining reported defect: dynamic Renewals cards expose Delete entry and Deploy
now to Viewer. These actions are now gated by effective issuance/deployment
permissions, with public CSR downloads and status information retained. Browser
coverage now checks nine renewal states for each role and representative union.
Enable/Disable are separate adjacent controls with the current-state action disabled;
their enabled/disabled behavior and adjacency are tested at 1440px and 390px.

Focused evidence: expanded existing browser matrix 13 passed in 156.43s; the new
Administration control test passed in 13.19s (13 deselected). No new build or human
approval of the corrected controls is implied. UAT 5 remains open for that retest.
