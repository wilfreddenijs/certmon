---
phase: "05"
plan: "05-02"
status: partial
subsystem: physical-acceptance
reconciled: "2026-10-10"
requirements-completed: []
---

# Plan 05-02: Partial Hardware Evidence

**Not complete.** This is a reconciliation of observations, not the original
`approved-one-lan` / `approved-two-lan` acceptance record.

## Human Observations Already Available

- User reported working certificates after Direct upload on SW4 USB Pro and UCS
  SW 313. The latter initially reported a mismatch/cleanup-pending result despite
  the certificate working after processing.
- After waiting and confirming processing finished, the user showed
  `Staged PEM cleanup: deleted` on the UCS workflow.
- UCS 303 screenshot showed `Direct activation: verified` and
  `HTTPS verification: verified`, with a NIC-1 import acknowledgement.
- The examples use LAN A. They support practical single-interface functionality;
  they do not establish independent LAN B deployment.
- Later user reports that builds work mostly/well and that Toolbelt EXE tests
  succeed are useful feature feedback, not universal Direct transport acceptance.

## Missing Acceptance Evidence

For an authorized maintenance test, record model and firmware, chosen management
and HTTPS endpoints, expected/observed certificate SHA-256 fingerprints, safe
NIC-specific acknowledgement, cleanup outcome and no-reboot observation.

LAN B needs its own configured endpoint and independent observed fingerprint;
LAN A success cannot substitute. Firmware and the complete no-reboot/fingerprint
record were not provided in the available reports. Do not invent them.

Use 05-UAT.md for the remaining evidence. Do not repeat uploads merely to fill
paperwork where existing device logs can establish the required facts.
