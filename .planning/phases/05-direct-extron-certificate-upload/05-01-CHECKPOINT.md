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
