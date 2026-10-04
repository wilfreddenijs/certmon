# Phase 3: Toolbelt auto-upload UI with device progress and cancellation — Research

**Created:** 2026-06-29
**Status:** Complete

## Research Summary

The current codebase already has most of the raw ingredients for this phase, but they are not connected into a user-facing Toolbelt batch workflow.

Existing assets:

- `toolbelt_uploader.py` already drives Extron Toolbelt through `pywinauto`, supports `--list`, dry-run by default, `--commit` for real upload, Toolbelt detection, per-device failure isolation, and retry after transient UI errors.
- `/api/ca/devices-txt` already exports `selector,certificate_id` mappings that represent the intended batch upload list.
- Local CA Extron certificates now have server-side encrypted private artifacts and explicit Extron combined PEM downloads.
- The Upload tab already has saved device cards, certificate selection, manual deployment results, and fetch-based UI patterns.
- Scan progress already uses polling, which is a good fit for Toolbelt dry-run/upload progress.

Main gaps:

- `toolbelt_uploader.py` writes human logs but has no stable machine-readable event stream for UI progress.
- The script still assumes legacy `%ProgramData%\CertMon\CA` PEM paths when parsing `devices.txt`; Phase 3 must bridge secure artifact IDs to temporary combined PEM paths without exposing private material to browser state.
- There is no backend run manager for long-running Toolbelt subprocesses, cancellation, latest status persistence, or per-device encrypted credentials.
- There is no UI that renders `devices.txt` as a device-oriented batch list.

## Recommended Approach

Use a thin subprocess contract rather than refactoring Toolbelt automation into a service.

1. Extend `toolbelt_uploader.py` with machine-readable output:
   - `--jsonl` prints one JSON event per line to stdout.
   - `--stop-file <path>` lets CertMon request safe stop after the current device.
   - `--device-password-file <path>` or equivalent avoids putting credentials directly on the command line.
   - Keep the existing human log for troubleshooting.

2. Add a CertMon backend Toolbelt run manager:
   - Builds the device list from `/api/ca/devices-txt` / certificate metadata.
   - Materializes Extron `combined.pem` artifacts to a temporary run directory.
   - Launches `toolbelt_uploader.py` as a subprocess.
   - Reads JSONL events and stores in-memory current run state plus latest per-device persisted status.
   - Deletes temporary PEM files after run completion/failure/cancel.

3. Add UI under the Upload tab:
   - A dedicated “Toolbelt batch upload” section.
   - Device-oriented rows with checkbox, Local CA certificate status, dry-run status, upload status, and credential status.
   - Opening/refreshing the section starts background dry-run when appropriate.
   - Real upload is explicit and only allowed for checked devices with dry-run OK.

4. Store credentials/status safely:
   - Store per-device credentials encrypted through the existing Vault/Database secret pattern.
   - Store latest dry-run/upload status in SQLite settings or a small dedicated table.
   - Do not persist serial numbers as secrets; use them only as a fallback candidate and avoid logging them unnecessarily.

## Key Risks

- Toolbelt UI automation is brittle. The JSONL event contract should make failures visible and diagnosable without making the UI depend on human log parsing.
- Toolbelt can be elevated while CertMon is not, causing Windows UI Automation access failures. Existing Toolbelt detection messages should be surfaced clearly.
- Secure artifact storage means the backend must materialize temporary PEMs for Toolbelt and remove them reliably.
- “Automatic background dry-run” must not accidentally click Apply/upload/reboot. Tests must assert dry-run launches without `--commit`.
- Per-device credentials must not leak into process command lines, browser state, logs, or planning docs.

## Research Complete

The phase is ready for planning as one vertical implementation plan.
