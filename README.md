# CertMon

CertMon scans TLS endpoints, tracks certificate expiry, issues replacement certificates, and deploys stored certificates to supported devices such as Extron products.

This guide describes the current source implementation. The **v1.0 build 48** baseline (2026-10-08) uses
source `61e6b94b729c232d5f6fefe73c84dabe349a80c6`.
[Build 48](https://github.com/wilfreddenijs/certmon/actions/runs/37696698593)
contains the Windows executable. Download the `CertMon-Windows` artifact while
it is retained by GitHub Actions.

## Security Status

CertMon starts in desktop mode by default and binds to `127.0.0.1`. LAN binding is refused unless explicit server mode is enabled.

Certificate private keys, ACME account keys, device credentials, and Cloudflare tokens are encrypted at rest. Manual private-key export is intentionally separate, permission checked, and audited. Exported keys must be handled as secrets.

## Shared Server Mode

Server mode is for a trusted LAN or a protected reverse-proxy deployment. Do not expose CertMon directly to the public internet.

### Start The Windows EXE For Role Testing

Quit any running CertMon instance using the system-tray **Quit** command; closing
the browser does not stop it. Open PowerShell in the folder containing the extracted
`CertMon.exe`, then start it from that same PowerShell window:

```powershell
$env:CERTMON_SERVER_MODE = '1'
$env:CERTMON_BIND_HOST = '127.0.0.1'
$env:CERTMON_PORT = '5000'
.\CertMon.exe
```

Open `http://127.0.0.1:5000`. This enables authenticated server behavior locally
without exposing the service to the LAN. Create the first administrator if prompted;
otherwise sign in with an existing account. Use **Administration** to create test
users and a separate private browser window to test their roles independently.
The information button beside **Add user** shows the authoritative role/permission
table. Multiple roles combine their permissions.

For access from another computer, set `CERTMON_BIND_HOST` to `0.0.0.0` before
starting the EXE. Open `http://<server-IP>:5000` on that computer, not `0.0.0.0`.
Allow inbound TCP 5000 through Windows Firewall only for the intended trusted
network. Direct HTTP does not encrypt credentials or traffic; use HTTPS through a
protected reverse proxy for ongoing shared use. Server mode uses the configured
port exactly; if it is occupied, stop the old instance or choose another port.

Environment variables above apply to processes started from that PowerShell window.
They are not permanent Windows settings. To return to desktop mode, quit CertMon
fully and start it with:

```powershell
$env:CERTMON_SERVER_MODE = '0'
$env:CERTMON_BIND_HOST = '127.0.0.1'
.\CertMon.exe
```

Do not change `CERTMON_DATA_DIR` for the role test: packaged builds keep the existing
data in `%PROGRAMDATA%\CertMon` unless that variable is explicitly set. Changing it
selects a different installation state, including users and CA material.

### Run Server Mode From Source

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
- **Security Admin:** download private-key material, manage DNS credentials, view audit-sensitive operations, and manage full server backups.
- **Admin:** all permissions, including user and audit administration.

Signed-in Admin and Security Admin users can open the **Administration** tab for full server backup and recovery. Only Admin users see its Users section, where they can add local users, edit usernames and roles, enable or disable accounts, and reset passwords. CertMon accepts only the five roles above. At least one enabled administrator must always remain, so the final enabled administrator cannot be disabled or lose the Admin role.

Viewer can download existing public certificates, chains, CSRs and trust files,
but cannot issue/deploy certificates, delete renewal entries, or export private
keys, combined PEM/ZIP files and backups. A Viewer account that also has CA Admin
inherits issuance and renewal-management rights, so **Delete entry** is then valid.

Disabling an account, changing its roles, or resetting its password revokes all active sessions for that user. The user must sign in again after a role or password change; disabled users cannot sign in until an administrator enables them. User-management audit events record the acting administrator, source IP, target account, and changed fields without recording passwords or password hashes.

The UI shows the current signed-in user and exposes an Audit tab. Sensitive actions such as login/logout, Local CA backup import/export, DNS credential changes, private artifact downloads, Toolbelt upload runs, and deployment attempts are recorded with username and source IP. Secrets are redacted from audit details.

For team trust distribution, use **Local CA** > **Trust bundle**. The bundle contains only the public CertMon Local CA certificate and installation notes; it does not contain the Local CA private key. Use encrypted CA backup export/import only between trusted CertMon installations that must share the same signing CA.

## Issuer Workflows

- **Let's Encrypt / ACME:** Public DNS names using DNS-01. Manual DNS and Cloudflare automation are supported. The exact normalized identifier set must succeed against Let's Encrypt staging before production is enabled.
- **CertMon Local CA:** Offline issuance for private IP addresses and internal DNS names. Install the public CertMon CA certificate on operator computers. Never distribute the CA private key.
- **External CA:** Generate a CSR, pause the job, obtain a signed certificate from an enterprise or public CA, then resume by importing the validated chain. Existing certificate/key pairs can also be imported after cryptographic validation.

For Cloudflare automation, create an API token limited to `Zone:DNS:Edit` and `Zone:Zone:Read` for only the zones CertMon manages. Do not use the Global API Key.

## Devices And Certificate Preparation

The **Devices** tab shows scanned TLS endpoints and their current certificates.
The filter and selection toolbar stays visible while scrolling.

- Filter by certificate validity and whether a Local CA certificate has been created.
- The **Certificate issuer** filter lists the issuers found in the inventory,
  including self-signed certificates. Enable **Exclude** to hide the selected issuer.
- **Product / device name** matches part of the displayed device name, for example
  `TLP`, `IPLP`, or `ShareLink`; it is a text filter, not a model-discovery guarantee.
- Select devices and choose **Create certificates** to prepare their Local CA certificates.
- **Refresh all devices** rereads every known endpoint, including devices hidden
  by filters. Up to four checks run concurrently; progress and failed checks are shown.
  Individual device refresh remains available. Unreachable endpoints are not reported
  as successfully refreshed and may retain their previous certificate data.

The prepared Upload list has one row per device address. Creating another certificate
for a device already in the list asks whether to cancel or replace its upload
certificate. Replacing the selection does not erase the older stored certificate.

The **Local CA** tab manages the root CA, trust installation/distribution, encrypted
CA backups and certificate issuance. Individual certificate downloads are centralized
under **Upload** > **Certificate downloads**, not duplicated in Local CA.

## Upload Workspace

The **Upload** tab uses one prepared-device list. Choose **Direct** or **Toolbelt**
as the upload method for each device, then select the devices for that method's
batch controls. **Device Credentials** configures one device; **Shared Device
Credentials** configures the shared credentials. Passwords are stored encrypted.
Each device row shows **Individual password: set** or **not set**, based on whether
a non-empty individual password is saved. The browser receives only this boolean
status, never the password or its length.

Both upload methods use the same credential order: a non-empty individual password
with its configured username, then a non-empty shared password with its configured
username, then the factory default `admin` / `extron`. Empty entries are skipped;
duplicate username/password pairs are tried only once. A rejected password advances
to the next candidate; connection failures and changed host keys do not trigger
password fallback. This standardized fallback was added after build 48.

Only Toolbelt adds a final `admin` / serial-number attempt when the serial number
is available. Direct upload does not retrieve or use a serial-number password.

For Direct devices, select **LAN A** or **LAN B** per device, not for the whole batch.
LAN B also requires its reachable HTTPS host and port. A connection test is not
an upload and does not activate a certificate.

After an actual Direct or Toolbelt batch finishes, CertMon's browser workspace
automatically rereads the involved monitored devices and updates the Devices view.
Dry-runs and connection tests do not trigger this refresh. A device that is still
restarting or unreachable may need a later refresh.

### Successful Upload Cleanup And Audit

The **Remove successful uploads from this list after batch completion** checkbox
is off by default and its setting is saved. When enabled, a finished upload batch
removes only successful entries from the prepared list; failed or unconfirmed
uploads remain for review. Tests do not clear the list. Stopped or failed batches
retain their entries. A verified individual Direct upload can also remove its entry
when the option is enabled.

This cleanup hides upload-list entries; it does **not** delete stored certificates,
private keys, device credentials or scanned devices. Downloads remain available,
and issuing a new certificate for the same device makes it available for upload again.

Before entries are hidden, **Audit** records each successful and unsuccessful upload
with the device address, certificate ID, upload method, run ID, result and interface
where available. These records remain after cleanup. If results cannot be saved to
Audit, automatic list cleanup is not performed. Upload result records do not contain
passwords, private keys or PEM contents.

### Direct Extron Upload (SFTP + SIS)

1. Prepare an Extron-compatible Local CA certificate and select **Direct** beside the device.
2. Save the device or shared credentials and review its LAN interface/HTTPS endpoint.
3. Select **Test selected Direct devices**. Batch testing stores previously unseen
   SSH host keys automatically on first use; a changed saved key blocks the device
   for review. First-use acceptance is not an independent identity check, so use a
   trusted network and the intended device addresses.
4. Select **Upload selected Direct devices** and confirm the batch. Devices are
   processed sequentially; **Stop after current device** stops before the next device.

Direct upload stages the combined certificate/private-key PEM over SFTP on TCP
22022 and sends the SIS import command over SSH on TCP 22023. Success requires
the import acknowledgement and verification that the selected HTTPS endpoint
presents the expected certificate. SFTP transfer alone is not upload success.
Normal Direct import does not request a reboot.

Confirmed imports clean up the temporary staged PEM. An unconfirmed import or
cleanup failure remains visible for review; do not repeatedly upload or delete
staged files while the device may still be processing. Use the offered cleanup
confirmation only after confirming that processing has finished.

**Open upload** provides individual connection, host-key approval, upload and
certificate-removal controls. Removing the device certificate targets the chosen
LAN interface and keeps the certificate stored in CertMon.

Direct upload has been exercised on SW4 USB Pro, UCS SW 313 and UCS 303 devices.
This is not a compatibility guarantee for every Extron model, firmware or LAN B setup.

### Extron Toolbelt Batch Upload

Toolbelt uses the same prepared-device list as Direct upload. It requires Extron
Toolbelt on the Windows computer running CertMon.

- The device list comes from stored Extron-compatible Local CA certificates.
- Select **Test Toolbelt upload** to run a dry-run first. Dry-run prepares Toolbelt targeting and fields, but does not click Apply and does not reboot devices.
- Each device is entered through Toolbelt's **Add** dialog using its address and credentials. CertMon opens management by clicking the exact matching IP row once, then continues to the certificate controls in **Utilities**. It does not start Discovery or make a redundant second Manage click. Existing devices stay in place and are located by address, not row position.
- Real upload requires an explicit **Start Toolbelt upload** click and is enabled only for selected devices whose dry-run is OK.
- **Stop after current device** requests a safe stop before the next device starts; it does not force-kill an active Toolbelt operation.
- CertMon materializes the Extron combined PEM only in a temporary server-side run folder and deletes it after the run.
- Toolbelt tries individual credentials, shared credentials, `admin` / `extron`, then `admin` / the serial number available from its device list. If the serial number is not visible, choose **Fields** > **Serial Number** in Toolbelt and retry dry-run; if **Fields** is hidden, open the toolbar overflow menu, and if the serial column is off-screen, scroll right or move the splitter. Toolbelt may lock the username field to `admin`; a candidate requiring an unavailable username is skipped rather than paired with the wrong password.
- An explicit **Authentication Failed** response advances to the next credential candidate without waiting for the full connection timeout. **Device Unreachable** ends that device's attempt without password retries and lets the batch continue to the next device.

First-run Toolbelt checklist:

1. Install Extron Toolbelt and verify **Add** can connect to a device by its address and password.
2. Run Toolbelt and CertMon at the same privilege level. If Toolbelt is elevated, CertMon/launcher must also be elevated.
3. Save the device password in CertMon. Serial-number fallback can use an existing device row; it cannot read the serial number of a device that has not yet been added successfully.
4. Confirm dry-run status in CertMon before starting a real upload.

### Certificate Downloads And Manual Installation

Expand **Upload** > **Certificate downloads** and choose a certificate/device pair.
The selected identity and download filenames change with the selection.

- Public certificate and chain downloads are separate from private-key export.
- Extron-compatible certificates offer a combined PEM containing the certificate
  and private key. **Download all Extron PEMs (.zip)** exports all stored Extron
  combined PEMs, including certificates whose successful upload entries were hidden.
- Generic devices can use the separate certificate, chain and private-key files
  according to their own import requirements.
- **Upload Guide** describes Direct, Toolbelt and manual installation. Device-specific
  manual instructions appear with the selected downloads.

This section downloads files; it does not upload them to a device. Combined PEMs,
private-key files and ZIP exports contain secrets and require private-export permission.
Protect them and remove local copies when they are no longer needed. The obsolete
`devices.txt` download button is no longer part of the UI.

## Data Directory

Set `CERTMON_DATA_DIR` to choose the server data location:

```powershell
$env:CERTMON_DATA_DIR = 'C:\CertMon\Data'
python launcher.py
```

Development defaults to `data` beside the source. The packaged Windows build defaults to `%PROGRAMDATA%\CertMon`.

## Recovery And Backup

Use **Administration** > **Server backup and recovery** to download a full server backup. This operation requires the Admin or Security Admin role and a new passphrase entered twice. The ZIP contains a consistent SQLite online backup, encrypted certificate artifacts, encrypted vault files, a passphrase-encrypted recovery package, a versioned authenticated manifest, and recovery notes. The database includes users, applicable sessions, roles, settings, certificate metadata, and audit records. Plaintext private keys and decrypted secrets are never added to the package.

The full server backup is different from **Local CA** > **Export CA backup** and **Import CA backup**. Local CA backup moves only Local CA signing state between trusted installations. Full server backup preserves the complete CertMon installation state.

Treat the backup ZIP and its passphrase as highly sensitive: together they grant access to encrypted CertMon material. Store them securely, preferably in separate controlled locations, and do not include either one in tickets, logs, or ordinary file shares. `CERTMON_MAX_BACKUP_UPLOAD_MB` controls the restore upload limit and defaults to 512 MiB.

**Stage restore** verifies the archive layout, package authentication, manifest, file hashes, backup ID, and representative vault key before writing. It restores into a new sibling directory and re-protects the vault master key for the Windows account running the current CertMon process. It never overwrites, renames, deletes, or activates the current `CERTMON_DATA_DIR` while CertMon is running.

Activate a staged restore on Windows only after the web request has completed:

1. Stop CertMon completely.
2. Retain or rename the current data directory so it remains available for rollback.
3. Rename the staged directory to the expected location, or configure `CERTMON_DATA_DIR` to point to the exact staged directory.
4. Start CertMon and sign in.
5. Verify the Local CA, representative certificates, encrypted artifacts, users, and audit history.
6. Remove the old data directory only after the restored installation has been accepted.

## Run From Source

```powershell
pip install -r requirements.txt
python launcher.py
```

## Build Windows EXE

### Current Application And Historical Acceptance

Build 48 includes Direct and Toolbelt batches, per-device interface selection,
device filters, optional successful-upload list cleanup, durable per-device upload
audit results, and post-upload device refresh. The release implementation and UI
were checked with 77 regression tests and 14 browser tests. These automated tests
do not replace live device/firmware testing or an antivirus assessment of an EXE.

The acceptance reference below is historical, not the current feature list.

Shared server mode was accepted on 2026-10-04 using **v1.0 build 23**, source
`5da496d1501feafbb6d881d89e82aab587c4d5e8`. Human UAT is 10/10 passed, including
Viewer restrictions, additive roles, account/password/session controls and desktop
safety. [Build 23](https://github.com/wilfreddenijs/certmon/actions/runs/37218527033)
and its [full test run](https://github.com/wilfreddenijs/certmon/actions/runs/37218519929)
(288 passed; one optional external ACME staging case deselected) are the acceptance
reference. New builds from main receive their own run/build numbers.

Direct Extron upload was not included in that build-23 acceptance baseline. It is
implemented in current builds alongside Toolbelt; Toolbelt has not been retired.
Documents under `docs/superpowers/` and the original Direct-upload proposal are
historical design/planning references rather than the current operator guide.

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
