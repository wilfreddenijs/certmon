# Phase 05 Source Coverage Audit

No ROADMAP requirement IDs are mapped to Phase 05 (`phase_req_ids: null`), so every PLAN uses `requirements: []` and visible spec/context scope coverage.

| SOURCE | ID | Feature / constraint | Plan | Status | Notes |
|--------|----|----------------------|------|--------|-------|
| GOAL | - | Replace Toolbelt automation with SFTP 22022, SIS SSH 22023, and HTTPS verification while preserving upload and credential workflows | 05-01, 05-03, 05-04 | COVERED | Toolbelt remains a legacy fallback pending separate retirement acceptance. |
| REQ | - | No mapped Phase 05 requirement IDs | - | N/A | Spec-backed fallback is explicit in plan frontmatter. |
| RESEARCH | - | Server-only direct transport, exact SIS ACK, selected HTTPS fingerprint | 05-01, 05-03 | COVERED | Transfer alone cannot succeed. |
| RESEARCH | - | Paramiko legitimacy/version/packaging verification | 05-01, 05-04 | COVERED | `SUS` package receives a blocking human gate before install. |
| RESEARCH | - | Read-only probe; no PEM/SFTP writes/ingest | 05-01, 05-04 | COVERED | Focused fake-call assertions and UI contract. |
| RESEARCH | - | No stale ACK or automatic replay after ambiguous activation; verified/mismatch/indeterminate | 05-01, 05-03, 05-04 | COVERED | Fresh channel, bounded pre-send drain, post-write ACK collection, and HTTPS-only reverify are explicit. |
| RESEARCH | - | Cleanup and partial-failure handling | 05-01, 05-03, 05-04 | COVERED | Every staged basename is durable; safe guarded delete remediation survives restart and never re-ingests. |
| RESEARCH | - | Deterministic credential resolution | 05-01, 05-03, 05-04 | COVERED | Exact per-device else shared is chosen before auth; failure never tries an alternate and UI supports explicit change/retest. |
| RESEARCH | - | Exact-selected batch, cancellation, persisted status | 05-03, 05-04 | COVERED | Missing entries fail in place; stop occurs between devices. |
| RESEARCH | - | One-LAN and two-LAN physical acceptance | 05-02 | COVERED | Blocking checkpoint before expansion. |
| RESEARCH | - | Packaging, UI wording, docs, manual downloads/credentials regressions | 05-04 | COVERED | Includes PyInstaller and full offline suite. |
| CONTEXT | D-01 | Combined PEM over SFTP 22022 | 05-01, 05-03 | COVERED | Root-level unique staged file. |
| CONTEXT | D-02 | Exact SIS ingest over authenticated SSH 22023 | 05-01, 05-03 | COVERED | ESC/CR bytes and fragmented replies tested. |
| CONTEXT | D-03 | Immediate activation; no normal reboot | 05-01, 05-02, 05-03 | COVERED | Physical evidence required. |
| CONTEXT | D-04 | LAN A default; LAN B per device | 05-01, 05-02, 05-03, 05-04 | COVERED | Minimal persisted LAN B target, NIC 2 transport, UI choice, and fake tests exist before physical acceptance. |
| CONTEXT | D-05 | Encrypted/server-side private data; preserve roles/audit | 05-01, 05-03, 05-04 | COVERED | RBAC, CSRF, audit and no-secret tests. |
| CONTEXT | D-06 | Retire Toolbelt only after verified replacement | 05-01, 05-02, 05-04 | COVERED | No Toolbelt deletion is planned. |
| CONTEXT | D-07 | Explicit endpoint-specific host-key approval/persistence/audit | 05-01, 05-03, 05-04 | COVERED | Unknown/changed keys block before auth. |
| CONTEXT | D-08 | Saved passwords; known serial entered; legacy serial fallback retained | 05-01, 05-03, 05-04 | COVERED | Direct path selects one credential deterministically with no auth-failure fallback or discovery. |
| CONTEXT | D-09 | Persist separate LAN B HTTPS host/port and require config | 05-01, 05-02, 05-03, 05-04 | COVERED | LAN B is never inferred from LAN A. |

API coverage detector result after plan authoring: `detected: true`. `COVERAGE.md` therefore records the narrow Extron certificate/device transport surface and explicit opt-outs; it does not expand scope to the general SIS command set.

Result: all in-scope GOAL, RESEARCH, and CONTEXT items are covered; no source item is silently omitted.
