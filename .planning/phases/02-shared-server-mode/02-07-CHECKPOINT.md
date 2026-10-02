# Plan 02-07 - Browser Matrix Tracer Checkpoint

Status: awaiting human feedback; task 07-01 acceptance coverage incomplete
Type: human-verify (blocking tracer feedback gate)
Date: 2026-10-02
Executor: 01a0fc80-cad9-7300-83e0-94a498adf0d5

## Execution Evidence

- `6695f6e`: failing RBAC browser matrix tests.
- `0169c63`: browser matrix adjustments and desktop visibility fix.
- Files: tests/test_rbac_browser.py, templates/index.html.
- Executor command: `py -3 -m pytest tests/test_rbac_browser.py -q`.
- Executor result: 13 passed in 84.03s, no skips or xfails.
- Session subset: 4 passed, 9 deselected in 36.85s.
- Desktop fix makes hasPermission respect locally granted permissions without requiring a server-mode login; backend permission boundaries unchanged.

## Orchestrator Review

Passing tests are not yet complete acceptance evidence for task 07-01:

- Public artifact test checks four Upload link URLs and absent missing links, but does not retrieve public downloads or exercise CA certificate, trust bundle, Excel and devices.txt.
- Local CA and device/renewal dynamic controls are not seeded with sufficient existing state; static permission-tag checks cannot establish all dynamic behavior.
- Restricted request assertions omit the deployment-only `/api/certificates` catalog and other protected loaders.
- Role/audit request checks use role-name exceptions instead of the effective permission set; the admin case inadvertently asserts no audit requests.
- Session tests capture requests only after mutation and do not explicitly prove no background permission polling or unchanged UI before the next protected request.
- Private sentinel checks cover DOM only, not public response/download contents.

Strengthen these checks before claiming complete D-01 through D-10 coverage. Do not loosen runtime authorization or suppress real failures.

## Continuation

After feedback authorizes continuation, use a fresh executor for the remaining task 07-01 coverage, preserving prior commits. Re-run the full browser matrix and return its tracer feedback gate. Only then proceed with 07-02 regression evidence; 07-03 remains a separate human UAT gate.

No summary, phase completion, UAT 5 approval, push or executable build is implied. UAT 4 and 9 remain unchanged. Untracked .gsd/ and data/ are preserved.
