# Direct Extron Certificate Upload

Date: 2026-10-02
Status: User-confirmed workflow; implementation and device coverage pending

## Confirmed Workflow

The user successfully tested the following replacement for Toolbelt upload:

1. Upload the combined PEM (device certificate and matching private key) using SFTP on TCP port 22022. The device's SFTP root directory is acceptable.
2. Use an authenticated SSH connection on TCP port 22023 to send the SIS certificate-import command naming the uploaded file.
3. The imported certificate becomes active immediately; no device reboot is required in the tested workflow.

The command reference is the screenshot `docs/SIS command for Cert Ingest.png` on the repository's main branch. Retrieve that reference into the implementation branch before finalizing the protocol implementation. It documents the import command, success response, passphrase variant, and NIC values. ESC and carriage return must be encoded as control bytes, not literal text.

On 2026-10-06 the user confirmed import on SW4 USB Pro V1.02 via PuTTY.
The exact no-passphrase wire command is `\x1bI1*certmon.pemCERT\r`, with response
`CertI1`. There is no space between the filename and `CERT`; spaces in the
reference screenshot separate notation, not literal command bytes. The earlier
implementation inserted a space there and received no acknowledgement.
This confirms the manual import, not the corrected automated SSH path or LAN B.

## Locked Product Decisions

- Replace and ultimately retire the Toolbelt-based automatic certificate-upload workflow.
- Preserve the central upload list, per-device selection, credentials, shared device credentials, progress, cancellation, and per-device result reporting.
- Default each device to LAN A (SIS NIC value 1).
- Provide a per-device option for LAN B (SIS NIC value 2). Only a limited number of devices have two LAN interfaces; LAN B must not become a global default or a required choice for every upload.
- The network-interface choice belongs to the upload target and must not change the certificate's intended identifiers.
- Do not reboot devices as part of the normal import workflow.

## Planning and Verification Requirements

- Confirm SSH/SFTP authentication behavior, supported device models/firmware, host-key trust, command framing, response parsing, passphrase handling, and timeout behavior before retiring the working Toolbelt implementation.
- Serial-number fallback must have a supported direct source; do not depend on reading Toolbelt's discovery column. Do not claim that direct serial retrieval is already solved.
- Keep private material encrypted at rest and out of browser responses and logs; use the existing permission, credential-vault, and audit boundaries.
- Separate connectivity/authentication checks from certificate activation. A test action must not silently import a certificate.
- Do not report upload success merely because SFTP succeeded. Require the expected SIS import response and verification that the intended HTTPS endpoint presents the expected certificate fingerprint.
- For LAN B, establish which reachable address/HTTPS endpoint corresponds to that interface. Do not verify LAN A and infer LAN B success.
- Plan cleanup of the staged combined PEM after confirmed import and safe handling of partial failures; deletion semantics are not yet confirmed by the user.
- Verify one-LAN and two-LAN devices in real device tests. The successful user experiment is not proof that every Extron model/firmware supports the same flow.
- Include packaging changes, regression coverage, UI wording, and documentation in the migration plan. Toolbelt removal must follow successful replacement verification, not precede it.

## Scope Separation

This is a new upload-transport capability, separate from the remaining Phase 02 role-visibility repair. The Phase 02 context remains valid for both the existing UI and the eventual direct-upload UI. Capturing this specification does not close UAT 5, implement direct upload, or authorize publication/build execution.
