# Plan 05-01 Checkpoint: Paramiko Package Identity Approval

**Status:** implementation checked; awaiting human tracer UI feedback
**Task:** 05-01-01 - Approve the official Paramiko package identity before installation
**Gate:** blocking-human
**Recorded:** 2026-10-05

## Automated Official Metadata Check

The plan's exact read-only verification command completed successfully against
`https://pypi.org/pypi/paramiko/json`. No package was installed and no project
file was edited.

| Field | Official PyPI result |
|---|---|
| Project | `paramiko` |
| Current stable version | `5.0.0` |
| Requires-Python | `>=3.9` |
| Release-file count | 2 |
| Project page | https://pypi.org/project/paramiko/ |
| Documentation | https://docs.paramiko.org |
| Upstream source | https://github.com/paramiko/paramiko |

## Official Release Files

| File | Type | Size | Uploaded (UTC) | SHA-256 |
|---|---|---:|---|---|
| `paramiko-5.0.0-py3-none-any.whl` | wheel (`py3`) | 208,919 bytes | 2026-05-09T18:28:50.295900Z | `b7044611c30140d9a75261653210e2002977b71a0497ff3ba0d98d7edbf62f7c` |
| `paramiko-5.0.0.tar.gz` | source distribution | 1,548,586 bytes | 2026-05-09T18:28:52.256263Z | `36763b5b95c2a0dcfdf1abc48e48156ee425b21efe2f0e787c2dd5a95c0e5e79` |

## Evidence and Decision Needed

The official PyPI metadata names the project `paramiko`, lists the official
documentation URL under `Docs`, and lists `https://github.com/paramiko/paramiko`
under `Source`. This matches the provisional research identity. The provisional
version has not been added to `requirements.txt`.

Approve this exact candidate only if the PyPI project, documentation, and
upstream repository are the intended dependency for the direct Extron SSH/SFTP
transport.

## Resume Signal

Human response received on 2026-10-05: `approved-paramiko 5.0.0`.
The exact official version is approved. No approval of real-device activation,
push, or build is implied by this dependency checkpoint.

Type `approved-paramiko 5.0.0` to authorize Task 05-01-02. Any other version
or a legitimacy concern keeps the plan blocked; no dependency pin or install
will occur without a new explicit approval.

## Current Tracer Feedback Checkpoint

The preceding dependency instructions are historical; approval was received.
The user selected inline takeover after the stall warning. The executor then
returned late commits and was closed; implementation was reviewed, not repeated.

| Work | Commit | Evidence |
|---|---|---|
| Test-first baseline | 9d23402 | Missing module produced RED failure |
| Direct tracer | b397995 | Initial 13 tests and 68 regressions reported by executor |
| Inline corrections | fafa0b8 | Exact SIS command test initially failed, then passed; independent port approvals/probe, fresh shell/fragmented ACK, staged endpoint recovery, post-disconnect verification and UI activation gating |

Fresh combined verification: 86 passed in 22.43s. Includes 18 direct tracer
tests (Chromium UI included) and 68 existing regression tests. Desktop/mobile
screenshots were inspected; no physical device requests were issued. This is
not full-suite, packaged-runtime, or hardware acceptance.

Preview: http://127.0.0.1:5052/ using `.tmp/direct-preview-data`, not existing
user data. Confirm the Direct Extron section, LAN selection/endpoint controls,
initially disabled activation button, and retained Toolbelt section in Upload.
Do not start a device action for this UI checkpoint. Respond `tracer verified`
or describe the interface issue. Plan 05-01 remains unsummarized until feedback;
physical one-LAN/two-LAN gates in 05-02 remain pending. No push/build performed.

User visually accepted the initial interface but requested prepared-device
selection rather than typed addresses. Commit e6ac3ec connects Devices > Open
Upload to the same prepared-device list, automatically filling IP/certificate;
creation's upload-options action and each prepared row follow the same path.
The browser regression proves no automatic probe/activation. Direct/UI suites:
50 passed in 28.90s. Latest interface feedback and hardware gates remain pending.

## Test Build Requested

On 2026-10-05 the user approved the prepared-device interface and button layout,
then requested a Windows build for testing at work. Commit 75178df labels the
combined transfer/activation action `Upload certificate` and places the LAN B
endpoint save action last. This authorizes build delivery, not device activation.

Full local suite: 306 passed, 1 skipped, 1 failed in 442.96s. The failure was a
TimeoutError in the browser fixture's initial HTTP readiness request, before
role assertions. Both parameterized role-union cases passed on retry (2 passed
in 33.50s). The 19 direct-upload tests passed. Physical one-LAN/two-LAN upload
acceptance and packaged-runtime verification remain pending.

## Build 25 Physical Feedback / Diagnostic Follow-up

On 2026-10-06 the user reported SFTP TCP 22022 reachable but TCP 22023
unavailable on the tested IPL device. The SW4 USB Pro supports both ports.
Host-key approval required unexplained repeated test clicks. A later SW4
activation produced two pending records for selector 10.10.116.187 with
`verification=different_certificate` and `known_completion=false`.
No successful activation or hardware acceptance is claimed.

User approved a diagnostic follow-up build. It adds endpoint-specific network
and authentication messages, automatic re-probe after explicit key approval
(never automatic key approval or activation), request error logging in the
windowed executable, and bounded escaped SIS reply/pre-send diagnostics in the
result and persistent staged record. Existing pending jobs are not replayed.
Targeted direct upload, launcher, UI, CSRF and role suites: 79 passed in 38.69s.
Physical activation remains an open checkpoint; no Toolbelt retirement.

## Command Framing and Terminal Feedback

The user demonstrated manual SW4 import in PuTTY using
`ESC I1*certmon.pemCERT CR` with response `CertI1`. Build 27 removed the
incorrect space before `CERT`. Subsequent UCS SW 313 feedback showed HTTPS
verification succeeded but no SIS acknowledgement was read. Build 28 requested
a VT100 PTY and increased the bounded SIS reply wait to 30 seconds.

Build 28 screenshots for SW4 USB Pro and UCS SW 313 now show the command echo
as the entire captured response and HTTPS verification `verified`. The reader
stopped at the echo's first carriage return, before a subsequent ACK could be
read. The user reports both certificates appear to work; this does not establish
causality or complete the strict automatic activation acceptance gate.

The follow-up reads beyond the echo and accepts only the exact transmitted
command echo (raw ESC or terminal `^[` notation) followed by the expected NIC
ACK, or an exact ACK alone. Echo-only, wrong NIC, unrelated output and duplicate
ACKs remain rejected. SFTP checks remote file size before SIS and persists that
evidence. Disappearance from FileZilla after import is not yet proven to be
device-side consumption. No automatic replay of pending imports is added.

## Recorded SW4 Reply After Build 29

The user supplied the exact persisted response:
`^[I1*certmon-a04907d3bd3f498387185e9a0bd405bd.pemCERT\r\nCertI1\r\r\n`.
SFTP confirmed 3428 bytes and HTTPS verification was `verified`. The parser
incorrectly rejected the trailing PTY CRCRLF conversion. A test using this
exact reply failed before correction and passes after normalizing terminal
line endings, while wrong NICs, duplicate ACKs and unrelated echoes remain
rejected. Cleanup now treats only SFTP ENOENT as already cleaned; permission
and other I/O failures still surface. Existing historical jobs are not replayed
or automatically marked complete. Targeted regression suites: 99 passed in
41.71s. Final automatic success/cleanup confirmation on hardware remains open.

## Build 31 Device Feedback

The user confirmed SW4 USB Pro automatic upload completed without an error
and the certificate works; screenshot shows `verified`, SFTP size confirmation,
the SIS echo and `CertI1` acknowledgement. UCS SW 313 also acknowledged import,
but the immediate HTTPS observation returned `different_certificate`; the user
subsequently confirmed its certificate works. This suggests HTTPS activation
propagation, not a missing SIS acknowledgement.

After a confirmed SIS import, the follow-up retries only read-only HTTPS
fingerprint verification for a bounded 30-second window, exits early on a match,
and never replays SFTP or SIS. Persistent mismatch remains pending. Regression
tests cover delayed success, temporary unreachability and timeout without replay.
Targeted suites: 94 passed in 46.16s. UCS final automated verification and LAN B
hardware acceptance remain open; Toolbelt retirement is not approved.

## UCS 303 Hardware Feedback After Build 32 Delivery

On 2026-10-06 the user tested a UCS 303, explicitly distinguishing it from
the UCS SW 313. The screenshot for selector 192.168.0.114 on LAN A shows
`Direct activation: verified`, `HTTPS verification: verified`, SFTP transfer
confirmation of 3375 bytes, `SIS sent: true`, and the expected `CertI1`
acknowledgement after the command echo. No pending cleanup warning is shown.
This establishes automatic direct-upload success on this tested UCS 303.
The build number is not visible in the supplied screenshot; feedback followed
delivery of build 32. Do not infer UCS SW 313 or LAN B acceptance from this
different model's result. Those hardware gates remain open, and Toolbelt
retirement is not approved.

## Device Certificate Removal Requested

On 2026-10-06 the user explicitly requested deletion of the active device
certificate, retaining the stored CertMon certificate. User supplied commands
`ESC X1CERT CR` / `ESC X2CERT CR`, then `ESC V1CERT CR` / `ESC V2CERT CR`.
The project's `docs/SIS command for Cert Ingest.png` confirms `CertX<nic>`
acknowledgements and JSON certificate information, optionally prefixed with
`CertV<nic>`. It does not specify the post-deletion value of the JSON `C` field.

Implementation adds a LAN-choice dialog, device/endpoint confirmation,
DEPLOY_CERTIFICATE and CSRF guards, audit attribution, pinned SSH trust, strict
confirmation/NIC validation, and readback without automatic deletion replay.
Pending imports block removal on that interface; upload/removal operations
cannot overlap in this service. No private material or CertMon artifact is
deleted. Results distinguish a device acknowledgement from independent
confirmation of the fallback certificate; raw/public readback is available in
collapsed technical details. Exact post-deletion response and hardware
acceptance remain pending. The user has been asked for this PuTTY response.

Successful uploads now show a green `Certificate uploaded and verified.`
message with diagnostics collapsed; warning states remain visible.
Targeted direct-upload, UI, role and CSRF suites: 123 passed in 40.40s.
No new packaged build has been produced for these changes yet.

## Unified Upload Workspace Requested

On 2026-10-06 the user requested one prepared-device list with selectable
Direct (SFTP + SIS) and Toolbelt methods, separate identifiable downloads,
and an opaque sticky navigation area without scrolling text visible above it.
The list now has a per-device method selector and an Open upload action.
Direct upload uses a selected-device dialog retaining explicit probe, host-key
approval, upload and removal controls; it does not add automatic direct batch
execution. Toolbelt runs include only selected rows whose method is Toolbelt.
Opening/changing a method does not start a probe or upload.

Certificate downloads show the selected identifiers and certificate ID, plus
the actual server download filenames. Links update immediately on selection
and are cleared for an empty selection. Public catalog metadata contains
public download names and the shared safe filename prefix, not private material.
The filename suffix uses the last eight certificate-ID characters so certificates
with a shared device-name prefix remain distinguishable. Existing permission
checks on private/public downloads are unchanged.

The sticky tabs cover the content scrollport's top padding; a regression test
first detected a 24-pixel gap, then passed after the sticky offset correction.
Desktop, scrolled, download, direct-dialog and mobile screenshots were inspected.
Final targeted service/API/UI/role/CSRF suites: 150 passed in 55.35s. The expanded
run also passed all role-browser cases; its earlier navigation failure passed
in a dedicated three-test UI rerun after correction. Preview runs on loopback
port 5053 with isolated .tmp/upload-preview-data. No packaged build yet.

## Direct Batch And Credentials Follow-Up

On 2026-10-07 the user reported that shared/per-device credential prompts do
not open in the embedded browser and requested sequential Direct batch uploads.
Browser prompt-based credential entry was replaced by a native HTML dialog
with an explicit password field, save/error states and password clearing on
close. Shared and individual credentials retain the existing encrypted vault
and are used by both Direct and Toolbelt.

All prepared devices now have selectable checkboxes. Direct and Toolbelt
actions include only selected rows for their respective method. Direct batch
supports LAN A/B, read-only connection preflight, explicit upload confirmation,
per-device results and stop-after-current-device. The server resolves certificate
IDs from prepared devices and runs uploads sequentially in a background worker,
holding the existing certificate-operation lock. Every selected endpoint must
pass trust/authentication checks before any transfer; host-key approval is still
an explicit per-endpoint action. Uploads recheck trust and stop on uncertainty,
never replaying an import automatically. Pending staged imports block a new
batch for that device/interface until reviewed. Private material stays server-side.

Batch progress is process-local; a server restart does not resume or replay a
batch. Durable staged-PEM records remain available for recovery. Closing the
device dialog does not stop the server worker. New service/API/browser tests
cover sequencing, key approval, ambiguous imports, stop/exclusion, auth/CSRF,
server-side certificate selection and the credential dialogs. Desktop/mobile
screenshots of batch controls and credential entry were inspected. Hardware
batch acceptance and LAN B testing remain pending. Preview remains on 5053;
no new EXE has been packaged or pushed.

Final targeted batch, upload UI, Direct service/API, UI contract, deployment,
RBAC, CSRF and CA suites: 160 passed in 62.89 seconds. The earlier page-load
timeout was addressed by waiting for DOM readiness in the workspace browser
fixture instead of waiting for all external assets. Preview HTTP check: 200.

## Build 33 Hardware Follow-Up: First-Use Trust And Per-Device LAN

On 2026-10-07 the user confirmed most of build 33 works, but explicitly requested
background host-key acceptance and a separate LAN A/B choice for every device.
This supersedes the earlier manual first-use enrollment requirement. Direct
API probes and batch preflight now automatically pin both observed endpoint
keys on first use. Stored-key changes still block before password authentication
or private PEM transfer and require explicit review; the code never blindly
replaces a known key. Transport connections still compare the pinned fingerprint.
An observation failure on either port does not store partial new approvals.

Each Direct row now persists its own interface in database settings. LAN B
requires the device's explicit LAN B host/HTTPS port in a row-scoped native
dialog. The central batch NIC selector and single-device Save LAN B endpoint
button are removed. Batch requests resolve each selected device's certificate
and persisted NIC on the server; a batch may mix LAN A and LAN B. The individual
upload dialog shows this row's interface read-only. Changing either interface
or endpoint invalidates the previous batch test. Legacy explicit batch NIC
requests remain accepted for compatibility with build 33 clients.

Tests cover distinct first-use SFTP/SIS keys, rejection of changed keys before
authentication, mixed-interface sequential upload, persisted prepared-row
metadata, invalid NIC/missing LAN B target, interface auth/CSRF guards and the
row-scoped responsive UI. LAN B device/hardware acceptance remains pending.

Build 34 candidate verification: 183 targeted tests passed in 63.38 seconds,
covering Direct/batch/UI/deployment/RBAC/CSRF/CA and Toolbelt API/service suites.
Desktop/mobile per-device LAN controls were captured; mobile layout inspected.
