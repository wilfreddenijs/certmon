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

The .pem for an IP is taken from C:\\CertMon\\CA\\<ip_with_underscores>.pem
(what CertMon's Local CA tab writes). Override with --pem for single-device mode.
"""

import os
import sys
import time
import argparse
import logging

try:
    from pywinauto import Application, Desktop
    from pywinauto.timings import wait_until
except ImportError:
    print("pywinauto is required:  pip install pywinauto comtypes")
    sys.exit(2)

# ---------------------------------------------------------------------------
CA_DIR = r"C:\CertMon\CA"
TOOLBELT_EXE = r"C:\Program Files (x86)\Extron\Toolbelt\Toolbelt.exe"
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolbelt_upload.log")

# Generous waits — device manage + reboot are slow.
T_MANAGE = 25      # seconds to wait for a device's config panels after Manage
T_DIALOG = 15      # file-open dialog appear
T_APPLY = 120      # apply + reboot to report success
POLL = 0.5

log = logging.getLogger("tb")


def setup_logging():
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8"); fh.setFormatter(fmt); log.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt); log.addHandler(sh)


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
def connect_toolbelt(launch_if_needed=True, timeout=60):
    app = Application(backend="uia")
    try:
        app.connect(title_re=".*Toolbelt.*", timeout=5)
    except Exception:
        if not launch_if_needed:
            raise
        if not os.path.exists(TOOLBELT_EXE):
            raise RuntimeError("Toolbelt.exe not found at %s" % TOOLBELT_EXE)
        log.info("Launching Toolbelt...")
        Application(backend="uia").start(TOOLBELT_EXE)
        app.connect(title_re=".*Toolbelt.*", timeout=timeout)
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
    dots_btn.click_input()

    handle = _find_open_dialog(T_DIALOG)
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
    # Click Open (button title is usually "&Open"); fall back to Enter.
    try:
        ob = dlg.child_window(title_re="&?Open", class_name="Button")
        if ob.exists():
            ob.click()
        else:
            fn.type_keys("{ENTER}")
    except Exception:
        fn.type_keys("{ENTER}")

    # Wait for the dialog to close
    deadline = time.time() + 8
    from pywinauto import findwindows
    while time.time() < deadline:
        if not findwindows.find_windows(class_name="#32770"):
            break
        time.sleep(POLL)
    time.sleep(0.5)


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


def click_apply_and_confirm(win, apply_btn, timeout=T_APPLY):
    """Click Apply and confirm the reboot prompt; wait for success/failure text."""
    apply_btn.click_input()
    time.sleep(1.0)
    # Confirm dialog: "Are you sure you want to reboot?" -> Yes/OK
    deadline = time.time() + 10
    while time.time() < deadline:
        for w in Desktop(backend="uia").windows():
            txt = (w.window_text() or "")
            if "reboot" in txt.lower() or "are you sure" in txt.lower():
                for b in w.descendants(control_type="Button"):
                    if (b.window_text() or "").strip() in ("Yes", "OK", "&Yes"):
                        b.click_input()
                        break
                break
        # also check inline confirm buttons inside main window
        time.sleep(POLL)
        break  # confirm dialog handling is best-effort; many builds auto-proceed

    # Wait for a result message
    deadline = time.time() + timeout
    while time.time() < deadline:
        texts = [(c.window_text() or "").strip() for c in win.descendants(control_type="Text")]
        joined = " | ".join(texts)
        low = joined.lower()
        if "successful" in low or "uploaded successfully" in low:
            return True, "success"
        if "failed" in low or "not correct" in low or "do not match" in low or "not valid" in low \
           or "does not follow security" in low:
            # pull the specific message
            for t in texts:
                tl = t.lower()
                if "fail" in tl or "not correct" in tl or "do not match" in tl or "not valid" in tl or "security" in tl:
                    return False, t
            return False, "failed (unspecified)"
        time.sleep(1.0)
    return False, "timeout waiting for result"


def upload_to_device(app, win, ip, pem_path, passphrase, commit):
    """Full per-device flow (assumes device is in the discovery list)."""
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


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Drive Toolbelt to upload CertMon .pem certs to Extron devices.")
    ap.add_argument("--device", help="single device IP")
    ap.add_argument("--list", help="file with one device IP per line")
    ap.add_argument("--pem", help="explicit .pem path (single-device mode)")
    ap.add_argument("--passphrase", default="", help="key passphrase (blank for combined .pem)")
    ap.add_argument("--commit", action="store_true", help="actually click Apply (otherwise dry-run)")
    args = ap.parse_args()

    setup_logging()
    if not args.device and not args.list:
        ap.error("provide --device or --list")

    devices = []
    if args.device:
        devices.append(args.device.strip())
    if args.list:
        with open(args.list) as f:
            devices += [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]

    log.info("=== Toolbelt uploader: %d device(s), commit=%s ===", len(devices), args.commit)
    app, win = connect_toolbelt()

    results = []
    for ip in devices:
        pem = args.pem if (args.pem and args.device) else pem_for_ip(ip)
        try:
            ok, msg = upload_to_device(app, win, ip, pem, args.passphrase, args.commit)
        except Exception as e:
            ok, msg = False, "ERROR: %s" % e
            log.error("[%s] %s", ip, msg)
        results.append((ip, ok, msg))

    log.info("=== SUMMARY ===")
    for ip, ok, msg in results:
        log.info("  %-16s %s  %s", ip, "OK  " if ok else "FAIL", msg)
    n_ok = sum(1 for _, ok, _ in results if ok)
    log.info("Done: %d/%d ok", n_ok, len(results))


if __name__ == "__main__":
    main()
