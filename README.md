# CertMon — TLS Certificate Monitor

Scans your local network for devices with TLS certificates and monitors expiry dates.
Generates ACME renewal commands for expiring certificates.

## Download standalone EXE (no Python needed)

1. Go to the **Actions** tab on GitHub
2. Click the latest **Build CertMon Windows EXE** run
3. Download **CertMon-Windows** artifact
4. Extract and run `CertMon.exe` — browser opens automatically

## Or build locally

```powershell
build.bat
```

## Run from source

```bash
pip install -r requirements.txt
python launcher.py
```

## Features

- **Network scan**: CIDR range scan, finds all devices with TLS
- **Manual hosts**: add specific hostnames/IPs with custom ports
- **Self-signed vs CA detection**: badge on every certificate card
- **Dashboard**: color-coded status (OK / Warning / Critical / Expired)
- **Renewals**: generates certbot or acme.sh commands
- **Excel export**: formatted .xlsx with all certificates and renewals
- **System tray**: runs in background, right-click to quit
- **Auto browser launch**: opens automatically on startup
- **Persistent**: data saved to certmon_data.json next to the .exe
