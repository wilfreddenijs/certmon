# CertMon

CertMon scans TLS endpoints, tracks certificate expiry, issues replacement certificates, and deploys stored certificates to supported devices such as Extron products.

## Security Status

This release is still single-user software and has no application authentication. Run it on `127.0.0.1` only. Do not bind it to a LAN interface or place it behind a shared reverse proxy until Phase 2 authentication and roles are implemented.

Certificate private keys, ACME account keys, device credentials, and Cloudflare tokens are encrypted at rest. Manual private-key export is intentionally separate, permission checked, and audited. Exported keys must be handled as secrets.

## Issuer Workflows

- **Let's Encrypt / ACME:** Public DNS names using DNS-01. Manual DNS and Cloudflare automation are supported. The exact normalized identifier set must succeed against Let's Encrypt staging before production is enabled.
- **CertMon Local CA:** Offline issuance for private IP addresses and internal DNS names. Install the public CertMon CA certificate on operator computers. Never distribute the CA private key.
- **External CA:** Generate a CSR, pause the job, obtain a signed certificate from an enterprise or public CA, then resume by importing the validated chain. Existing certificate/key pairs can also be imported after cryptographic validation.

For Cloudflare automation, create an API token limited to `Zone:DNS:Edit` and `Zone:Zone:Read` for only the zones CertMon manages. Do not use the Global API Key.

## Extron Toolbelt Batch Upload

The Upload tab contains a **Toolbelt batch upload** section for Extron devices. It is separate from the generic/manual upload flow.

- The device list comes from CertMon's Local CA Extron mapping, the same data exported as `devices.txt`.
- Opening the Upload tab starts a safe dry-run first. Dry-run prepares Toolbelt targeting and fields, but does not click Apply and does not reboot devices.
- Real upload requires an explicit **Start Toolbelt upload** click and is enabled only for selected devices whose dry-run is OK.
- **Stop after current device** requests a safe stop before the next device starts; it does not force-kill an active Toolbelt operation.
- CertMon materializes the Extron combined PEM only in a temporary server-side run folder and deletes it after the run.
- Per-device credentials are stored encrypted. CertMon tries saved credentials first, then `admin` / `extron`, then `admin` / the serial number read from Toolbelt discovery during dry-run. If the serial number is not visible, choose **Fields** > **Serial Number** in Toolbelt and retry dry-run; if **Fields** is hidden, open the toolbar overflow menu, and if the serial column is off-screen, scroll right or move the splitter.

First-run Toolbelt checklist:

1. Install Extron Toolbelt and verify it discovers the devices.
2. Run Toolbelt and CertMon at the same privilege level. If Toolbelt is elevated, CertMon/launcher must also be elevated.
3. In Toolbelt's discovered-device list, enable **Fields** > **Serial Number** so CertMon can use it automatically when a device still uses it as the password.
4. Confirm dry-run status in CertMon before starting a real upload.

## Data Directory

Set `CERTMON_DATA_DIR` to choose the server data location:

```powershell
$env:CERTMON_DATA_DIR = 'C:\CertMon\Data'
python launcher.py
```

Development defaults to `data` beside the source. The packaged Windows build defaults to `%PROGRAMDATA%\CertMon`.

## Recovery And Backup

Create and securely store a vault recovery package and its passphrase separately. The package can restore the installation master key after service-account migration; possession of both package and passphrase grants access to all encrypted CertMon secrets.

`BackupService` creates a consistent SQLite online backup plus encrypted certificate artifacts and vault files. Its manifest is hash checked, HMAC authenticated, tied to a backup ID, and bound to the recovery package. Restore always writes to a new directory and verifies it completely. Stop CertMon and perform the final directory swap manually after verification.

When moving CertMon to another Windows service account:

1. Restore the backup into a new directory.
2. Restore the vault master key with the recovery package and passphrase.
3. Rewrap the master key using DPAPI under the new service account.
4. Verify representative certificates and keys before switching `CERTMON_DATA_DIR`.

## Run From Source

```powershell
pip install -r requirements.txt
python launcher.py
```

## Build Windows EXE

```powershell
build.bat
```

The build installs `requirements.txt`, runs PyInstaller, and writes `dist\CertMon.exe`.

## Optional ACME Staging Integration Test

The integration test never uses production. Configure a disposable test domain and provider credentials, then set:

```powershell
$env:CERTMON_ACME_STAGING_TEST = '1'
$env:CERTMON_ACME_TEST_DOMAIN = 'certmon-test.example.com'
$env:CERTMON_CLOUDFLARE_TOKEN = 'scoped-token'
$env:CERTMON_CLOUDFLARE_ZONES = 'example.com'
pytest -m acme_staging -v
```

The normal offline suite excludes this test:

```powershell
pytest -m "not acme_staging" -v
```
