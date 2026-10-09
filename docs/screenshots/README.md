# User Manual Screenshots

These images illustrate the [user manual](../user-manual.md). They show the actual
CertMon interface using fictional data in an isolated temporary installation.
They are not evidence of a successful device upload or live network scan.

## Refresh The Images

From the repository root, with the development dependencies installed:

```powershell
py -m pip install -r requirements-dev.txt
py -m playwright install chromium chromium-headless-shell
py tools/capture_user_manual.py
```

The capture script starts its own local server on an available port, creates
demonstration certificates and credentials, and uses Chromium to capture the
screens. It sets `CERTMON_DATA_DIR` only inside that process to a temporary
directory; it does not reuse the normal installation. Network scanning, deployment
and trust installation are not performed. Upload outcomes shown in Audit are
seeded examples, not real uploads. The temporary server is stopped and its data
removed when capture finishes.

The source-run header intentionally shows `build dev`. Update the manual's
baseline build only after checking its instructions against the released UI.

Inspect every updated image for clipping and readability. Keep filenames aligned
with the manual's image links and captions. Do not substitute screenshots that
expose real credentials, private keys, customer names or private network details.
