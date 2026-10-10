---
phase: "05"
status: partial
updated: "2026-10-10"
---

# Phase 05 Human Acceptance

## Already Reported

- Working Direct certificates: SW4 USB Pro, UCS SW 313 and UCS 303.
- UCS 303 screenshot: Direct and HTTPS verified on LAN A.
- UCS cleanup after waiting/explicit confirmation: staged PEM deleted.
- Later positive Toolbelt EXE and build-38 filter feedback.

These reports are retained, not converted into invented firmware/fingerprint
evidence or blanket compatibility approval.

## Remaining Checklist

- [ ] Single-interface record complete: model, firmware, management/HTTPS endpoints,
  safe SIS acknowledgement, expected/observed certificate fingerprints, cleanup
  state and no-reboot observation.
- [ ] Two-LAN device model/firmware and distinct saved LAN B HTTPS host/port recorded.
- [ ] Upload connection host (SFTP/SIS) recorded separately from certificate NIC and
  HTTPS verification endpoint. Upload may connect through either LAN; the LAN B
  acceptance test concerns the certificate for NIC 2, not merely the connection.
- [ ] LAN A/NIC 1 result independently verified at its HTTPS endpoint.
- [ ] LAN B/NIC 2 result independently verified at its own HTTPS endpoint; no inference
  from LAN A, including expected/observed fingerprint and NIC acknowledgement.
- [ ] Both interfaces' cleanup and no-reboot observations recorded.
- [ ] Representative current batch outcomes/stop behavior checked on authorized
  hardware if existing reports do not establish them.

Use an approved maintenance window. Prefer existing logs/read-only certificate
inspection where sufficient; do not repeat an ambiguous import. Do not include
passwords, private PEMs, passphrases or raw secret-bearing diagnostics. Mock tests
and screenshot demo Audit entries cannot satisfy these hardware checks.

## Acceptance Result

**Incomplete.** The documentation update does not authorize physical device writes
or waive the open criteria. Use 05-VERIFICATION.md for non-hardware contract gaps.
