# Plan 05-01 Checkpoint: Paramiko Package Identity Approval

**Status:** approved by the user; resume Task 05-01-02
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
