# CertMon

CertMon scans TLS endpoints, tracks certificate expiry, issues replacement certificates, and deploys stored certificates to supported devices such as Extron products.

## Security Status

CertMon starts in desktop mode by default and binds to `127.0.0.1`. LAN binding is refused unless explicit server mode is enabled.

Certificate private keys, ACME account keys, device credentials, and Cloudflare tokens are encrypted at rest. Manual private-key export is intentionally separate, permission checked, and audited. Exported keys must be handled as secrets.

## Shared Server Mode

Server mode is for a trusted LAN or a protected reverse-proxy deployment. Do not expose CertMon directly to the public internet.

Enable server mode explicitly:

```powershell
$env:CERTMON_SERVER_MODE = '1'
$env:CERTMON_BIND_HOST = '0.0.0.0'
$env:CERTMON_PORT = '5000'
python launcher.py
```

On first open, create the first administrator account. After that, users sign in with local CertMon accounts. Server mode uses HttpOnly session cookies and CSRF tokens for state-changing requests.

Roles:

- **Viewer:** view inventory and public certificate/trust artifacts.
- **Operator:** start renewals and deploy certificates.
- **CA Admin:** manage Local CA operations and issue Local CA certificates.
- **Security Admin:** download private-key material, manage DNS credentials, and view audit-sensitive operations.
- **Admin:** all permissions, including user and audit administration.

Signed-in administrators use the **Administration** tab to add local users, edit usernames and roles, enable or disable accounts, and reset passwords. CertMon accepts only the five roles above. At least one enabled administrator must always remain, so the final enabled administrator cannot be disabled or lose the Admin role.

Disabling an account, changing its roles, or resetting its password revokes all active sessions for that user. The user must sign in again after a role or password change; disabled users cannot sign in until an administrator enables them. User-management audit events record the acting administrator, source IP, target account, and changed fields without recording passwords or password hashes.

The UI shows the current signed-in user and exposes an Audit tab. Sensitive actions such as login/logout, Local CA backup import/export, DNS credential changes, private artifact downloads, Toolbelt upload runs, and deployment attempts are recorded with username and source IP. Secrets are redacted from audit details.

For team trust distribution, use **Local CA** > **Trust bundle**. The bundle contains only the public CertMon Local CA certificate and installation notes; it does not contain the Local CA private key. Use encrypted CA backup export/import only between trusted CertMon installations that must share the same signing CA.

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
- Per-device and shared device credentials are stored encrypted. CertMon tries saved per-device credentials first, then the shared device password if configured, then `admin` / `extron`, then `admin` / the serial number read from Toolbelt discovery during dry-run. If the serial number is not visible, choose **Fields** > **Serial Number** in Toolbelt and retry dry-run; if **Fields** is hidden, open the toolbar overflow menu, and if the serial column is off-screen, scroll right or move the splitter.

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

In server mode, the SQLite backup includes users, sessions, roles, settings, certificate metadata, and audit records. Backup and Local CA recovery operations require an authenticated role with the relevant private-key or CA-management permission.

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

### GitHub Actions build

The canonical Windows build is produced by the GitHub Actions workflow **Build CertMon Windows EXE v1**.

- Pushes to `main` start a build automatically.
- Manual builds can be started with **Run workflow** and an optional `build_notes` value.
- The Actions run title includes the supplied build notes when present.
- The uploaded artifact is named `CertMon-Windows`.
- The artifact contains:
  - `CertMon.exe`
  - `BUILD-NOTES.txt`

`BUILD-NOTES.txt` records the branch, commit, Actions run URL, and either the supplied `build_notes` text or the latest five commit messages.

The executable also embeds `build_info.json`. The app header shows this as:

```text
v1.0 build <GitHub Actions run number>
```

Local/source runs use `v1.0 build dev`.

The current build-number line was restarted by replacing the previous workflow with **Build CertMon Windows EXE v1**. GitHub's built-in workflow run numbers cannot be reset for an existing workflow, so a new workflow identity is used when the project intentionally starts a fresh build-number sequence.

### Local build

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
