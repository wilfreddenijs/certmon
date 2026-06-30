# -*- coding: utf-8 -*-
"""
CertMon — Toolbelt UI Uploader
==============================

Automates Extron Toolbelt's "SSL Certificate" upload (Utilities tab) via Windows
UI Automation (pywinauto), so a CertMon-issued .pem can be pushed to many UCS 303
(and similar Extron) devices without manual clicking.

WHY THIS EXISTS
---------------
Toolbelt uploads certs over SFTP (SSH port 4503) using a runtime-generated key
enrolled with admin credentials over Extron's proprietary protocol — there is no
embedded key to reuse and no documented API. The only robust automation is to
drive Toolbelt's own GUI, which is what this does.

WHAT IT DOES (per device)
-------------------------
1. Select the device by IP in Toolbelt's discovery list and click Manage.
2. Open the Utilities tab.
3. SSL Certificate section: click "..." -> pick the .pem in the file dialog.
4. Type the passphrase (blank for a combined .pem with an unencrypted key).
5. Click Apply and confirm the reboot prompt.
6. Wait for success/failure and log the result.

SAFETY
------
- DRY_RUN = True by default: it navigates and fills fields but DOES NOT click
  Apply (so nothing uploads and no device reboots). Validate targeting first,
  then pass --commit to actually apply.
- Per-device try/except: one failure doesn't abort the batch.
- Everything is logged to toolbelt_upload.log next to this script.

REQUIREMENTS
------------
  pip install pywinauto comtypes
Toolbelt must be installed and able to reach the devices (discovery working).

USAGE
-----
  # Dry run against a single device (safe — fills fields, no Apply):
  py toolbelt_uploader.py --device 192.168.0.114

  # Really upload to one device:
  py toolbelt_uploader.py --device 192.168.0.114 --commit

  # Batch from a file of IPs (one per line), dry run:
  py toolbelt_uploader.py --list devices.txt

  # Batch, really upload:
  py toolbelt_uploader.py --list devices.txt --commit

  # Full pipeline: issue each cert via CertMon, then upload (CertMon running):
  py toolbelt_uploader.py --list devices.txt --issue --commit

The .pem for an IP is taken from %ProgramData%\\CertMon\\CA\\<ip_with_underscores>.pem
(what CertMon's Local CA tab writes). Override with --pem for single-device mode.
"""

import os
import sys
import time
import ctypes
import argparse
import logging
import json

try:
    from pywinauto import Application, Desktop
    from pywinauto.timings import wait_until
except ImportError:
    print("pywinauto is required:  pip install pywinauto comtypes")
    sys.exit(2)

# ---------------------------------------------------------------------------
# CA cert/key/.pem storage — %ProgramData%\CertMon\CA (matches app.py).
# The old C:\CertMon\CA path is deprecated.
CA_DIR = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "CertMon", "CA")
TOOLBELT_EXE = r"C:\Program Files (x86)\Extron\Toolbelt\Toolbelt.exe"
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolbelt_upload.log")


def _toolbelt_candidate_paths():
    """Likely locations of Toolbelt.exe — both Program Files trees + registry."""
    paths = [TOOLBELT_EXE]
    for base in (os.environ.get("ProgramFiles(x86)"),
                 os.environ.get("ProgramFiles"),
                 os.environ.get("ProgramW6432")):
        if base:
            paths.append(os.path.join(base, "Extron", "Toolbelt", "Toolbelt.exe"))
    # Registry App Paths (set by the installer), 64- and 32-bit views
    try:
        import winreg
        for hive, key in (
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Toolbelt.exe"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\Toolbelt.exe"),
        ):
            try:
                with winreg.OpenKey(hive, key) as k:
                    val, _ = winreg.QueryValueEx(k, None)  # default value = exe path
                    if val:
                        paths.append(val.strip('"'))
            except OSError:
                pass
    except Exception:
        pass
    # de-dupe preserving order
    seen, out = set(), []
    for p in paths:
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


def find_toolbelt_exe():
    """Return the first existing Toolbelt.exe path, or None if not installed."""
    for p in _toolbelt_candidate_paths():
        if os.path.exists(p):
            return p
    return None

# Generous waits — device manage + reboot are slow.
T_MANAGE = 25      # seconds to wait for a device's config panels after Manage
T_DIALOG = 15      # file-open dialog appear
T_APPLY = 120      # apply + reboot to report success
POLL = 0.5

log = logging.getLogger("tb")
_JSONL = False


def emit(event, **fields):
    if not _JSONL:
        return
    payload = {"event": event, **fields}
    for key in ("password", "private_key", "private_key_pem"):
        payload.pop(key, None)
    print(json.dumps(payload, sort_keys=True), flush=True)


def setup_logging():
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8"); fh.setFormatter(fmt); log.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt); log.addHandler(sh)


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
def _win32_toolbelt_present():
    """True if a top-level window titled 'Toolbelt' exists at the Win32 level
    (even when UIA can't attach — e.g. an elevation/integrity mismatch)."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = [False]
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, lparam):
        n = user32.GetWindowTextLengthW(hwnd)
        if n > 0:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value.strip().lower() == "toolbelt":
                found[0] = True
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    return found[0]


def _is_elevated():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def connect_toolbelt(launch_if_needed=True, timeout=60):
    app = Application(backend="uia")
    # Fast preflight: if Toolbelt is neither running nor installed, fail now with
    # a clear message instead of burning ~28s retrying to attach to nothing.
    exe = find_toolbelt_exe()
    if not _win32_toolbelt_present() and not exe:
        raise RuntimeError(
            "Extron Toolbelt is not installed and not running. Install Toolbelt "
            "(or open it) and re-run.\nSearched:\n  - "
            + "\n  - ".join(_toolbelt_candidate_paths()))
    # Retry UIA connect: the window can be transiently UIA-unreachable while
    # Toolbelt is busy (e.g. opening a heavy device page). Only conclude an
    # elevation mismatch if it stays unreachable across all retries.
    connected = False
    for _ in range(8):
        try:
            app.connect(title_re=".*Toolbelt.*", timeout=2)
            connected = True
            break
        except Exception:
            time.sleep(1.5)
    if not connected:
        # Persistent UIA failure with a Win32 window present => integrity mismatch
        # (Toolbelt elevated, this script not).
        if _win32_toolbelt_present():
            raise RuntimeError(
                "Toolbelt is running but cannot be automated. This almost always "
                "means Toolbelt is running as Administrator while this script is "
                "not (Windows blocks lower-integrity automation of an elevated "
                "app). Fix: run this script from an elevated PowerShell "
                "(right-click > Run as administrator), OR start Toolbelt without "
                "admin. [this script elevated=%s]" % _is_elevated())
        if not launch_if_needed:
            raise RuntimeError("Could not attach to Toolbelt.")
        if not exe:
            raise RuntimeError(
                "Extron Toolbelt is not installed. Searched:\n  - "
                + "\n  - ".join(_toolbelt_candidate_paths()))
        log.info("Toolbelt not running — launching %s (this is slow; "
                 "for reliability open Toolbelt yourself before running)...", exe)
        Application(backend="uia").start(exe)
        # Toolbelt loads slowly and shows a splash first — poll patiently.
        deadline = time.time() + max(timeout, 90)
        connected = False
        while time.time() < deadline:
            try:
                app.connect(title_re=".*Toolbelt.*", timeout=3)
                connected = True
                break
            except Exception:
                time.sleep(2)
        if not connected:
            raise RuntimeError(
                "Could not attach to Toolbelt after launch. Open Toolbelt manually "
                "(wait for the device list), then re-run.")
    win = app.window(title_re=".*Toolbelt.*", top_level_only=True)
    win.wait("visible", timeout=timeout)
    bring_to_front(win)
    return app, win


def bring_to_front(win):
    """Toolbelt must be restored + foreground or real-mouse clicks land off-screen
    (a minimized window sits at ~ -32000,-32000)."""
    try:
        if win.is_minimized():
            win.restore()
    except Exception:
        pass
    try:
        win.maximize()
    except Exception:
        pass
    try:
        win.set_focus()
    except Exception:
        pass
    time.sleep(0.6)


def cy(rect):
    return (rect.top + rect.bottom) // 2


_DEVICE_PASSWORD = None  # optional override; set from --device-password
_DEVICE_CREDENTIALS = {}


def _credentials_modal_present(win):
    return any("provide credentials" in (c.window_text() or "").lower()
               for c in win.descendants(control_type="Text"))



def dismiss_credentials_prompt(win):
    """Close Toolbelt's in-app credentials modal so one failed device does not
    block selection/navigation for the next device."""
    try:
        if not _credentials_modal_present(win):
            return False
    except Exception:
        return False
    for b in win.descendants(control_type="Button"):
        text = (b.window_text() or "").strip().lower()
        if text in {"cancel", "close"} and b.is_visible():
            try:
                b.click_input()
                time.sleep(0.5)
                return not _credentials_modal_present(win)
            except Exception:
                pass
    try:
        win.type_keys("{ESC}", set_foreground=True)
        time.sleep(0.5)
        return not _credentials_modal_present(win)
    except Exception:
        return False

def accept_credentials_prompt(win, ip, timeout=8):
    """Managing an unauthenticated device pops an in-app 'Please provide
    credentials for <ip>' modal. Username is 'admin'; the password is prefilled
    with the factory default ('extron' on older units, the SERIAL NUMBER on new
    units). We accept the prefilled value unless --device-password is given,
    then verify the modal actually closed. Raises if credentials are rejected
    so the device fails cleanly instead of hanging.

    Returns False if no prompt appeared (already authenticated)."""
    # Wait briefly for the modal to appear.
    deadline = time.time() + timeout
    while time.time() < deadline and not _credentials_modal_present(win):
        time.sleep(POLL)
    if not _credentials_modal_present(win):
        return False  # device already authenticated this session

    # Optionally override the prefilled password.
    credential = _DEVICE_CREDENTIALS.get(ip) or {}
    candidates = []
    if _DEVICE_PASSWORD:
        candidates.append(_DEVICE_PASSWORD)
    if credential.get("password"):
        candidates.append(credential["password"])
    candidates.extend(credential.get("password_candidates") or [])
    candidate_password = next(
        (
            candidate
            for candidate in candidates
            if candidate and candidate not in {"__SERIAL__", "__PREFILLED__"}
        ),
        None,
    )
    if "__SERIAL__" in candidates and not credential.get("serial"):
        emit(
            "serial_column_missing",
            selector=ip,
            message="Serial-number password fallback needs the serial number from Toolbelt",
        )
    if candidate_password:
        try:
            import pywinauto.mouse as mouse
            plabel = next(c.rectangle() for c in win.descendants(control_type="Text")
                          if (c.window_text() or "").strip() == "Password")
            mouse.click(coords=(plabel.left + 40, plabel.bottom + 18))
            time.sleep(0.2)
            win.type_keys("^a{BACKSPACE}", set_foreground=True)
            win.type_keys(candidate_password, with_spaces=True, set_foreground=True)
        except Exception:
            pass

    # Click Enter ONCE (never hammer it — risk of lockout).
    for b in win.descendants(control_type="Button"):
        if (b.window_text() or "").strip() == "Enter" and b.is_visible():
            b.click_input()
            break
    time.sleep(2.5)

    if _credentials_modal_present(win):
        emit("credentials_needed", selector=ip, message="Credentials were rejected or are required")
        dismiss_credentials_prompt(win)
        raise RuntimeError(
            "credentials rejected for %s — the prefilled password is wrong. "
            "Authenticate it once in Toolbelt (new units: password = serial "
            "number), or pass --device-password." % ip)
    log.info("[%s] accepted credentials prompt", ip)
    return True


# ---------------------------------------------------------------------------
# Device selection + navigation  (task #2)
# ---------------------------------------------------------------------------
def select_device(win, ip, timeout=T_MANAGE):
    """Find the device row for `ip`, click Manage, then open the Utilities tab."""
    log.info("[%s] selecting device", ip)

    # Locate the IP cell in the discovery list
    ip_cell = None
    for c in win.descendants(control_type="Text"):
        if (c.window_text() or "").strip() == ip:
            ip_cell = c
            break
    if ip_cell is None:
        # try hyperlink
        for c in win.descendants(control_type="Hyperlink"):
            if (c.window_text() or "").strip() == ip:
                ip_cell = c
                break
    if ip_cell is None:
        raise RuntimeError("device %s not found in discovery list (is it discovered?)" % ip)

    row_y = cy(ip_cell.rectangle())
    # Click the row to select it
    ip_cell.click_input()
    time.sleep(0.5)

    # Manage button on the same row
    manage = None
    for b in win.descendants(control_type="Button"):
        try:
            aid = b.element_info.automation_id or ""
        except Exception:
            aid = ""
        if aid == "DeviceDiscoveryUserControl_ManageButton" and abs(cy(b.rectangle()) - row_y) < 30:
            manage = b
            break
    if manage is None:
        raise RuntimeError("Manage button not found for %s" % ip)
    manage.click_input()

    # An unauthenticated device shows a credentials modal that blocks the page —
    # accept it (prefilled admin/extron) before anything else.
    accept_credentials_prompt(win, ip)

    # Wait for the Utilities tab to be available, then click it
    def utilities_tab():
        for c in win.descendants(control_type="Text"):
            if (c.window_text() or "").strip() == "Utilities":
                return c
        return None
    wait_until(timeout, POLL, lambda: utilities_tab() is not None, value=True)
    tab = utilities_tab()
    tab.click_input()
    time.sleep(1.0)
    # Confirm the SSL section rendered
    wait_until(timeout, POLL,
               lambda: any((c.window_text() or "").strip() == "View and upload SSL certificates"
                           for c in win.descendants(control_type="Text")),
               value=True)
    log.info("[%s] Utilities tab open, SSL section visible", ip)


# ---------------------------------------------------------------------------
# SSL upload  (task #3)
# ---------------------------------------------------------------------------
def find_ssl_controls(win):
    """Locate SSL controls by geometric anchoring to the Browse/Passphrase labels."""
    labels = {}
    for c in win.descendants(control_type="Text"):
        t = (c.window_text() or "").strip()
        if t in ("Browse", "Passphrase"):
            labels.setdefault(t, c.rectangle())
    if "Browse" not in labels or "Passphrase" not in labels:
        raise RuntimeError("SSL section not visible (Browse/Passphrase labels missing)")

    browse_y, pass_y = cy(labels["Browse"]), cy(labels["Passphrase"])

    def edit_on_row(y):
        best = None
        for c in win.descendants(control_type="Edit"):
            r = c.rectangle()
            if r.left >= labels["Browse"].left and abs(cy(r) - y) < 20:
                if best is None or abs(cy(r) - y) < abs(cy(best.rectangle()) - y):
                    best = c
        return best

    def button_on_row(text, y):
        for b in win.descendants(control_type="Button"):
            if (b.window_text() or "").strip() == text and abs(cy(b.rectangle()) - y) < 25:
                return b
        return None

    ctrls = {
        "browse_edit": edit_on_row(browse_y),
        "pass_edit": edit_on_row(pass_y),
        "dots_btn": button_on_row("...", browse_y),
        "apply_btn": button_on_row("Apply", browse_y),
    }
    missing = [k for k, v in ctrls.items() if v is None]
    if missing:
        raise RuntimeError("could not locate SSL controls: %s" % ", ".join(missing))
    return ctrls


def _find_open_dialog(timeout):
    """The picker is a classic Win32 #32770 common dialog. Find its handle."""
    from pywinauto import findwindows
    deadline = time.time() + timeout
    while time.time() < deadline:
        handles = findwindows.find_windows(class_name="#32770")
        if handles:
            return handles[0]
        time.sleep(POLL)
    return None


def set_cert_path(app, win, dots_btn, pem_path):
    """Click '...' and drive the Win32 file-open dialog to populate the
    (read-only) Browse path field."""
    if not os.path.exists(pem_path):
        raise RuntimeError("PEM not found: %s" % pem_path)

    # Toolbelt must be the foreground window or the '...' click won't spawn the
    # file dialog (after the previous device's dialog, focus can be elsewhere).
    # Click, wait briefly, and retry once if no dialog appears.
    handle = None
    for attempt in range(2):
        bring_to_front(win)
        time.sleep(0.3)
        dots_btn.click_input()
        handle = _find_open_dialog(8 if attempt == 0 else T_DIALOG)
        if handle is not None:
            break
        log.info("file dialog didn't open (attempt %d) — retrying", attempt + 1)
    if handle is None:
        raise RuntimeError("file-open dialog (#32770) did not appear")

    # Drive the classic dialog with the win32 backend (purpose-built for it).
    app32 = Application(backend="win32").connect(handle=handle)
    dlg = app32.window(handle=handle)
    # Filename edit (inside a ComboBoxEx -> Edit). Type the full path + Enter.
    fn = None
    try:
        fn = dlg.child_window(class_name="Edit")
        if not fn.exists():
            fn = None
    except Exception:
        fn = None
    if fn is None:
        # fallback: the Edit may be nested; grab any Edit descendant
        eds = [c for c in dlg.descendants() if c.friendly_class_name() == "Edit"]
        fn = eds[0] if eds else None
    if fn is None:
        raise RuntimeError("filename field not found in open dialog")
    fn.set_edit_text(pem_path)
    time.sleep(0.3)
    # Submit the dialog with a REAL mouse click on Open (win32 BM_CLICK messages
    # don't reliably dismiss the shell dialog); fall back to Enter.
    submitted = False
    try:
        ob = dlg.child_window(title="&Open", class_name="Button")
        if ob.exists():
            try:
                ob.set_focus()
            except Exception:
                pass
            ob.click_input()
            submitted = True
    except Exception:
        submitted = False
    if not submitted:
        try:
            dlg.set_focus()
        except Exception:
            pass
        fn.type_keys("{ENTER}")

    # Wait for the dialog to close — if it doesn't, the path wasn't accepted.
    deadline = time.time() + 10
    from pywinauto import findwindows
    while time.time() < deadline:
        if not findwindows.find_windows(class_name="#32770"):
            break
        time.sleep(POLL)
    else:
        raise RuntimeError("file dialog did not close after selecting the .pem (Open not accepted)")
    time.sleep(0.6)


def set_passphrase(pass_edit, passphrase):
    """Passphrase is a WPF PasswordBox — focus and type via keyboard."""
    pass_edit.click_input()
    # clear anything present
    pass_edit.type_keys("^a{BACKSPACE}", set_foreground=True)
    if passphrase:
        # escape pywinauto special chars
        safe = passphrase.replace("{", "{{").replace("}", "}}").replace("+", "{+}") \
                          .replace("^", "{^}").replace("%", "{%}").replace("~", "{~}") \
                          .replace("(", "{(}").replace(")", "{)}")
        pass_edit.type_keys(safe, with_spaces=True, set_foreground=True)


FAIL_HINTS = ("not correct", "do not match", "not valid", "does not follow security",
              "invalid passphrase", "application failed")


def _msgbox(handle):
    """Return (full_text, yes_or_ok_button_or_None) for a #32770 dialog."""
    dlg = Application(backend="win32").connect(handle=handle).window(handle=handle)
    txt = dlg.window_text() or ""
    for c in dlg.descendants():
        try:
            txt += " " + (c.window_text() or "")
        except Exception:
            pass
    btn = None
    for title in ("&Yes", "Yes", "&OK", "OK"):
        b = dlg.child_window(title=title, class_name="Button")
        if b.exists():
            btn = b
            break
    return txt, btn


def click_apply_and_confirm(win, apply_btn, timeout=T_APPLY):
    """Click Apply, then decide the outcome:

    Toolbelt validates the cert/key/passphrase FIRST. If invalid it shows an
    error; if valid it shows a reboot confirmation. So:
      * an error message (#32770 or inline)  -> FAILURE
      * a reboot confirmation                -> SUCCESS (cert accepted) -> click Yes
    """
    from pywinauto import findwindows
    apply_btn.click_input()

    deadline = time.time() + min(timeout, 60)
    while time.time() < deadline:
        # (1) a #32770 dialog appeared — error or reboot-confirm?
        handles = findwindows.find_windows(class_name="#32770")
        for h in handles:
            try:
                txt, btn = _msgbox(h)
            except Exception:
                continue
            low = txt.lower()
            if any(fh in low for fh in FAIL_HINTS):
                # dismiss and report the error
                if btn:
                    try: btn.click_input()
                    except Exception: pass
                return False, txt.strip()[:120] or "upload rejected"
            if btn is not None:
                # no error text + a Yes/OK => reboot confirmation => accepted
                try: btn.click_input()
                except Exception: pass
                log.info("cert accepted; confirmed reboot")
                return True, "uploaded; device rebooting"

        # (2) inline (non-dialog) messages
        inline = " ".join((c.window_text() or "") for c in win.descendants(control_type="Text"))
        low = inline.lower()
        if "uploaded successfully" in low or "certificate was uploaded successfully" in low:
            return True, "uploaded successfully"
        for fh in ("do not match", "not correct", "not valid anymore", "does not follow security", "invalid passphrase"):
            if fh in low:
                return False, fh
        time.sleep(POLL)

    return False, "no confirmation/error detected (timeout)"


def reachable(ip, port=4503, timeout=3):
    """Fast TCP check of the management/SFTP port — skip offline/unroutable
    devices instead of waiting ~25s for Manage to fail."""
    import socket
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def _pem_cert_serial(pem_path):
    """Serial number of the certificate inside a .pem (cert block is first)."""
    from cryptography import x509
    with open(pem_path, "rb") as f:
        return x509.load_pem_x509_certificate(f.read()).serial_number


def device_cert_serial(ip, port=443, timeout=4):
    """Serial of the cert the device currently serves on its web port (443),
    or None if unreachable / unreadable."""
    import ssl
    import socket
    from cryptography import x509
    try:
        ctx = ssl._create_unverified_context()
        raw = socket.create_connection((ip, port), timeout=timeout)
        tls = ctx.wrap_socket(raw, server_hostname=ip)
        der = tls.getpeercert(True)
        tls.close()
        return x509.load_der_x509_certificate(der).serial_number
    except Exception:
        return None


def already_current(ip, pem_path):
    """True only if we can confirm the device already serves this exact cert."""
    try:
        want = _pem_cert_serial(pem_path)
    except Exception:
        return False
    have = device_cert_serial(ip)
    return have is not None and have == want


def upload_to_device(app, win, ip, pem_path, passphrase, commit, force=False):
    """Full per-device flow (assumes device is in the discovery list)."""
    if not reachable(ip):
        return False, "unreachable (port 4503 closed — offline or not routable)"
    if not os.path.exists(pem_path):
        return False, "no .pem at %s (issue it first or use --issue)" % pem_path
    # Skip devices that already serve this exact cert (avoids needless reboots
    # when re-running the full list). --force overrides.
    if commit and not force and already_current(ip, pem_path):
        return True, "already current — skipped (use --force to re-upload)"
    bring_to_front(win)
    select_device(win, ip)
    ctrls = find_ssl_controls(win)
    log.info("[%s] setting cert path: %s", ip, pem_path)
    set_cert_path(app, win, ctrls["dots_btn"], pem_path)
    log.info("[%s] setting passphrase (%s)", ip, "blank" if not passphrase else "provided")
    set_passphrase(ctrls["pass_edit"], passphrase)

    if not commit:
        log.info("[%s] DRY RUN — fields populated, Apply NOT clicked", ip)
        return True, "dry-run (not applied)"

    log.info("[%s] clicking Apply + confirming reboot...", ip)
    ok, msg = click_apply_and_confirm(win, ctrls["apply_btn"])
    log.info("[%s] result: %s (%s)", ip, "OK" if ok else "FAIL", msg)
    return ok, msg


def pem_for_ip(ip):
    return os.path.join(CA_DIR, ip.replace(".", "_").replace(":", "_") + ".pem")


def certmon_issue(ip, certmon_url, passphrase=""):
    """Ask a running CertMon to issue (or re-issue) the device cert and write its
    .pem. Returns the pem path. Requires the CertMon CA to already exist."""
    import json
    import urllib.request
    body = json.dumps({"ip": ip, "passphrase": passphrase}).encode()
    req = urllib.request.Request(certmon_url.rstrip("/") + "/api/ca/issue",
                                 data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    if not data.get("ok"):
        raise RuntimeError("CertMon issue failed: %s" % data.get("error"))
    return data.get("pem_path") or pem_for_ip(ip)


def _close_stray_dialogs(win=None):
    """Dismiss leftover dialogs before the next device."""
    from pywinauto import findwindows
    if win is not None:
        dismiss_credentials_prompt(win)
    for h in findwindows.find_windows(class_name="#32770"):
        try:
            Application(backend="win32").connect(handle=h).window(handle=h).type_keys("{ESC}")
        except Exception:
            pass


def ensure_connection(app, win):
    """Reconnect if Toolbelt was closed/restarted between devices."""
    try:
        _ = win.window_text()
        return app, win
    except Exception:
        log.info("Toolbelt connection lost — reconnecting...")
        return connect_toolbelt()


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Drive Toolbelt to upload CertMon .pem certs to Extron devices.")
    ap.add_argument("--device", help="single device IP")
    ap.add_argument("--list", help="file with one device IP per line")
    ap.add_argument("--pem", help="explicit .pem path (single-device mode)")
    ap.add_argument("--passphrase", default="", help="key passphrase (blank for combined .pem)")
    ap.add_argument("--commit", action="store_true", help="actually click Apply (otherwise dry-run)")
    ap.add_argument("--issue", action="store_true",
                    help="issue each cert via a running CertMon before uploading")
    ap.add_argument("--certmon-url", default="http://localhost:5000",
                    help="CertMon base URL for --issue (default http://localhost:5000)")
    ap.add_argument("--settle", type=float, default=2.0,
                    help="seconds to pause between devices (default 2)")
    ap.add_argument("--force", action="store_true",
                    help="re-upload even if the device already serves this cert")
    ap.add_argument("--device-password", default=None,
                    help="device admin password for the credentials prompt "
                         "(default: accept Toolbelt's prefilled value)")
    ap.add_argument("--device-password-file", default=None,
                    help="JSON credential file keyed by device selector; avoids secrets on the command line")
    ap.add_argument("--jsonl", action="store_true",
                    help="emit machine-readable JSONL progress events to stdout")
    ap.add_argument("--stop-file", default=None,
                    help="if this file appears, stop safely before starting the next device")
    args = ap.parse_args()

    global _DEVICE_PASSWORD, _DEVICE_CREDENTIALS, _JSONL
    _DEVICE_PASSWORD = args.device_password
    _JSONL = args.jsonl
    if args.device_password_file:
        with open(args.device_password_file, encoding="utf-8") as f:
            _DEVICE_CREDENTIALS = json.load(f)

    setup_logging()
    if not args.device and not args.list:
        ap.error("provide --device or --list")

    # Each device is (selector, pem_override). devices.txt lines are either
    # "ip" or "ip,pemfile" (CertMon's CA tab exports the 2-column form so a
    # hostname-named cert still maps to the right device).
    devices = []
    if args.device:
        devices.append((args.device.strip(), args.pem))
    if args.list:
        with open(args.list) as f:
            for ln in f:
                ln = ln.strip()
                if not ln or ln.startswith("#"):
                    continue
                if "," in ln:
                    sel, pemname = ln.split(",", 1)
                    sel, pemname = sel.strip(), pemname.strip()
                    pem_path = pemname if os.path.isabs(pemname) else os.path.join(CA_DIR, pemname)
                    devices.append((sel, pem_path))
                else:
                    devices.append((ln, None))

    log.info("=== Toolbelt uploader: %d device(s), commit=%s, issue=%s ===",
             len(devices), args.commit, args.issue)
    emit("run_started", mode="upload" if args.commit else "dry-run", count=len(devices))
    app, win = connect_toolbelt()

    results = []
    for idx, (ip, pem_override) in enumerate(devices, 1):
        if args.stop_file and os.path.exists(args.stop_file):
            emit("device_cancelled", selector=ip, message="Stop requested before device started")
            results.append((ip, False, "cancelled before start"))
            break
        log.info("--- (%d/%d) %s ---", idx, len(devices), ip)
        emit("device_started", selector=ip, index=idx, total=len(devices))
        app, win = ensure_connection(app, win)
        _close_stray_dialogs(win)

        # Resolve / issue the .pem for this device
        if args.issue:
            try:
                pem = certmon_issue(ip, args.certmon_url, args.passphrase)
                log.info("[%s] issued cert -> %s", ip, pem)
            except Exception as e:
                results.append((ip, False, "issue failed: %s" % e))
                log.error("[%s] issue failed: %s", ip, e)
                continue
        else:
            pem = pem_override or pem_for_ip(ip)

        try:
            ok, msg = upload_to_device(app, win, ip, pem, args.passphrase, args.commit, args.force)
        except Exception as e:
            # Transient UI/window errors happen at scale — reconnect and retry once.
            log.info("[%s] error (%s) — reconnecting and retrying once", ip, e)
            try:
                _close_stray_dialogs(win)
                app, win = connect_toolbelt()
                ok, msg = upload_to_device(app, win, ip, pem, args.passphrase, args.commit, args.force)
            except Exception as e2:
                ok, msg = False, "ERROR: %s" % e2
                log.error("[%s] %s", ip, msg)
        results.append((ip, ok, msg))
        if ok:
            emit("upload_ok" if args.commit else "dry_run_ok", selector=ip, message=msg)
        else:
            emit("upload_failed" if args.commit else "dry_run_failed", selector=ip, message=msg)
        time.sleep(args.settle)

    log.info("=== SUMMARY ===")
    for ip, ok, msg in results:
        log.info("  %-16s %s  %s", ip, "OK  " if ok else "FAIL", msg)
    n_ok = sum(1 for _, ok, _ in results if ok)
    log.info("Done: %d/%d ok", n_ok, len(results))
    emit("run_finished", ok=n_ok, total=len(results), status="complete")


if __name__ == "__main__":
    main()
