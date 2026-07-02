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
def _log_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


LOG_FILE = os.path.join(_log_dir(), "toolbelt_upload.log")


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
T_MANAGE = 180     # seconds to wait for a device's config panels after Manage
T_DIALOG = 15      # file-open dialog appear
T_APPLY = 120      # apply + reboot to report success
T_CREDENTIAL_ACCEPT = 120  # slow Extron units can take a long time after auth
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
    log.handlers.clear()
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
    log.info("connected to Toolbelt window")
    return app, win



def _control_text(control):
    parts = []
    try:
        text = (control.window_text() or "").strip()
        if text:
            parts.append(text)
    except Exception:
        pass
    try:
        name = (control.element_info.name or "").strip()
        if name and name not in parts:
            parts.append(name)
    except Exception:
        pass
    try:
        aid = (control.element_info.automation_id or "").strip()
        if aid:
            parts.append(aid)
    except Exception:
        pass
    return " ".join(parts)


def _device_visible(win, selectors):
    wanted = {str(value).strip() for value in selectors if str(value).strip()}
    if not wanted:
        return True
    for control_type in ("Text", "Hyperlink", "DataItem", "ListItem"):
        for c in win.descendants(control_type=control_type):
            text = (_control_text(c) or "").strip()
            if text in wanted or any(value in text for value in wanted):
                return True
    return False


def _click_discovery_control(win):
    terms = (
        "discover",
        "discovery",
        "refresh",
        "rescan",
        "scan",
        "search",
        "start",
        "device discovery",
        "DeviceDiscoveryUserControl_Discover",
        "DeviceDiscoveryUserControl_Refresh",
        "DeviceDiscoveryUserControl_Search",
        "DeviceDiscoveryUserControl_Start",
    )
    control_types = (
        "Button",
        "Hyperlink",
        "Text",
        "TabItem",
        "ListItem",
        "MenuItem",
        "Custom",
        "Image",
    )
    seen = []
    for control_type in control_types:
        for control in win.descendants(control_type=control_type):
            try:
                if not control.is_visible():
                    continue
            except Exception:
                continue
            label = _control_text(control)
            if not label:
                continue
            lower = label.lower()
            if any(term.lower() in lower for term in terms):
                seen.append(f"{control_type}:{label}")
                try:
                    control.click_input()
                    log.info("started/refreshed Toolbelt discovery via %s '%s'", control_type, label)
                    return True
                except Exception as exc:
                    log.info("could not click Toolbelt discovery candidate %s '%s': %s", control_type, label, exc)
            elif control_type == "Button":
                seen.append(f"{control_type}:{label}")
    if seen:
        log.info("visible Toolbelt discovery candidates/buttons: %s", "; ".join(seen[:40]))
    return False

def _keyboard_discovery_refresh(win):
    for keys in ("{F5}", "^r"):
        try:
            bring_to_front(win)
            win.type_keys(keys, set_foreground=True)
            log.info("requested Toolbelt discovery refresh via %s", keys)
            time.sleep(1.0)
        except Exception:
            pass
    return True


def ensure_discovery_started(win, selectors, timeout=45, require_visible=False):
    """Toolbelt can open without starting discovery. Start/refresh discovery and
    wait until at least one requested selector appears in the active device list."""
    bring_to_front(win)
    if _device_visible(win, selectors):
        return True

    started = _click_discovery_control(win)
    if not started:
        started = _keyboard_discovery_refresh(win)

    deadline = time.time() + timeout
    next_click = time.time() + 3
    while time.time() < deadline:
        if _device_visible(win, selectors):
            return True
        if time.time() >= next_click:
            started = _click_discovery_control(win) or started
            next_click = time.time() + 3
        time.sleep(POLL)
    message = "Toolbelt discovery did not show requested devices before timeout"
    if require_visible:
        raise RuntimeError(message + " (is discovery started?)")
    log.info(message + "; continuing anyway")
    return False

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


def cx(rect):
    return (rect.left + rect.right) // 2


_DEVICE_PASSWORD = None  # optional override; set from --device-password
_DEVICE_CREDENTIALS = {}
_RESOLVED_CREDENTIALS = {}
_RESOLVED_CREDENTIALS_FILE = None
_LAST_FIELDS_BUTTON_POINT = None


def _wants_serial_fallback(ip):
    credential = _DEVICE_CREDENTIALS.get(ip) or {}
    return "__SERIAL__" in (credential.get("password_candidates") or [])


def _looks_like_serial(value):
    text = (value or "").strip()
    if len(text) < 5 or len(text) > 32:
        return False
    lower = text.lower()
    if lower in {"serial", "serial number", "model", "ip address", "device", "name"}:
        return False
    if "." in text or ":" in text or "/" in text or " " in text:
        return False
    return any(ch.isdigit() for ch in text) and any(ch.isalpha() for ch in text)


def _discovery_row_cells(win, row_y):
    row = []
    for control_type in ("Text", "Hyperlink", "DataItem", "ListItem"):
        for c in win.descendants(control_type=control_type):
            try:
                if not c.is_visible():
                    continue
                r = c.rectangle()
                if abs(cy(r) - row_y) > 24:
                    continue
                text = (c.window_text() or "").strip()
                if text:
                    row.append((r.left, text))
            except Exception:
                pass
    return sorted(row, key=lambda item: item[0])


def _discovery_row_texts(win, row_y):
    return [text for _, text in _discovery_row_cells(win, row_y)]


def _grid_header_cells(win, row_y=None):
    headers = []
    for control_type in ("Text", "Header", "HeaderItem", "DataItem"):
        for c in win.descendants(control_type=control_type):
            try:
                if hasattr(c, "is_visible") and not c.is_visible():
                    continue
                text = (_control_text(c) or "").strip()
                lower = text.lower()
                if lower not in {
                    "ip address",
                    "actions",
                    "model name",
                    "mac address",
                    "device type",
                    "hostname",
                    "serial number",
                    "serial",
                }:
                    continue
                rect = c.rectangle()
                if row_y is not None and not (rect.bottom < row_y and row_y - rect.bottom < 180):
                    continue
                headers.append((rect.top, rect.left, rect.right, lower))
            except Exception:
                continue
    return headers


def _serial_column_center(win, row_y=None):
    headers = _grid_header_cells(win, row_y=row_y)
    bands = {}
    for top, left, right, text in headers:
        band = round(top / 10) * 10
        bands.setdefault(band, []).append((left, right, text))
    for cells in bands.values():
        labels = {text for _, _, text in cells}
        if "ip address" not in labels or "model name" not in labels:
            continue
        for left, right, text in cells:
            if text in {"serial", "serial number"}:
                return (left + right) // 2
    return None


def _serial_column_visible(win, row_y=None):
    return _serial_column_center(win, row_y=row_y) is not None


def _toolbelt_search_roots(win):
    roots = [win]
    try:
        roots.extend(Desktop(backend="uia").windows())
    except Exception:
        pass
    return roots


def _iter_toolbelt_controls(win, control_types):
    seen = set()
    for root in _toolbelt_search_roots(win):
        for control_type in control_types:
            try:
                controls = root.descendants(control_type=control_type)
            except Exception:
                continue
            for c in controls:
                try:
                    runtime_id = getattr(c.element_info, "runtime_id", None)
                    key = tuple(runtime_id) if runtime_id else (c.handle, id(c))
                except Exception:
                    key = id(c)
                if key in seen:
                    continue
                seen.add(key)
                yield c


def _control_label(control):
    try:
        return (_control_text(control) or control.window_text() or "").strip()
    except Exception:
        return ""


def _click_toolbar_overflow(win):
    candidates = []
    for b in _iter_toolbelt_controls(win, ("Button", "SplitButton")):
        try:
            if hasattr(b, "is_visible") and not b.is_visible():
                continue
            rect = b.rectangle()
            label = _control_label(b).lower()
            if rect.top > 130 or rect.width() > 38 or rect.height() > 45:
                continue
            if label and not any(marker in label for marker in ("more", "overflow", "toolbar")):
                continue
            candidates.append((rect.right, b))
        except Exception:
            continue
    if not candidates:
        return False
    _, button = sorted(candidates, key=lambda item: item[0])[-1]
    try:
        button.click_input()
        time.sleep(0.5)
        return True
    except Exception:
        return False


def _toolbar_overflow_candidates(win):
    candidates = []
    for b in _iter_toolbelt_controls(win, ("Button", "SplitButton")):
        try:
            if hasattr(b, "is_visible") and not b.is_visible():
                continue
            rect = b.rectangle()
            label = _control_label(b).lower()
            if rect.top > 140 or rect.width() > 42 or rect.height() > 50:
                continue
            if label and not any(marker in label for marker in ("more", "overflow", "toolbar")):
                continue
            candidates.append((rect.right, b))
        except Exception:
            continue
    return [button for _, button in sorted(candidates, key=lambda item: item[0], reverse=True)]


def _click_control(control):
    try:
        control.click_input()
        time.sleep(0.5)
        return True
    except Exception:
        return False


def _click_fields_button(win):
    for b in _iter_toolbelt_controls(win, ("Button", "SplitButton", "MenuItem")):
        try:
            text = _control_label(b).lower()
            if "fields" not in text:
                continue
            if hasattr(b, "is_visible") and not b.is_visible():
                continue
            if _click_control(b):
                return True
        except Exception:
            continue
    return False


def _click_fields_by_toolbar_geometry(win):
    try:
        import pywinauto.mouse as mouse
    except Exception:
        return False
    anchors = []
    for c in _iter_toolbelt_controls(win, ("Button", "SplitButton", "MenuItem", "Text")):
        try:
            label = _control_label(c).lower()
            if label not in {"group", "filter"}:
                continue
            rect = c.rectangle()
            if rect.top > 160:
                continue
            offset = 64 if label == "group" else 128
            anchors.append((rect.right, rect.top, rect.bottom, offset))
        except Exception:
            continue
    for right, top, bottom, offset in sorted(anchors, key=lambda item: item[0], reverse=True):
        try:
            x = right + offset
            y = (top + bottom) // 2
            mouse.click(coords=(x, y))
            time.sleep(0.6)
            return True
        except Exception:
            continue
    return False


def _filter_button_rects(win):
    filter_buttons = []
    for c in _iter_toolbelt_controls(win, ("Button", "SplitButton", "Text")):
        try:
            label = _control_label(c).lower()
            if label != "filter":
                continue
            rect = c.rectangle()
            if rect.top > 160:
                continue
            filter_buttons.append((rect.right, rect.bottom, rect))
        except Exception:
            continue
    return [rect for _, _, rect in sorted(filter_buttons, key=lambda item: item[0], reverse=True)]


def _click_filter_overflow_arrow(win):
    try:
        import pywinauto.mouse as mouse
    except Exception:
        return None
    for rect in _filter_button_rects(win):
        for x, y in (
            (rect.right + 28, rect.bottom - 3),
            (rect.right + 24, rect.bottom - 4),
            (rect.right + 32, rect.bottom - 8),
            (rect.right + 8, rect.bottom - 3),
        ):
            try:
                log.info("clicking Toolbelt toolbar overflow divider near Filter at %s,%s", x, y)
                mouse.click(coords=(x, y))
                time.sleep(0.8)
                return rect
            except Exception:
                continue
    return None


def _click_fields_from_filter_overflow_geometry(filter_rect):
    global _LAST_FIELDS_BUTTON_POINT
    try:
        import pywinauto.mouse as mouse
    except Exception:
        return False
    candidates = (
        (filter_rect.right + 95, filter_rect.bottom + 32),
        (filter_rect.right + 90, filter_rect.bottom + 38),
        (filter_rect.right + 105, filter_rect.bottom + 28),
    )
    for x, y in candidates:
        try:
            log.info("clicking Toolbelt Fields button from overflow geometry at %s,%s", x, y)
            mouse.click(coords=(x, y))
            _LAST_FIELDS_BUTTON_POINT = (x, y)
            time.sleep(0.8)
            return True
        except Exception:
            continue
    return False


def _open_fields_menu(win):
    if _click_fields_button(win):
        return True
    filter_rect = _click_filter_overflow_arrow(win)
    if filter_rect is not None:
        if _click_fields_button(win):
            return True
        if _click_fields_from_filter_overflow_geometry(filter_rect):
            return True
    if _click_fields_by_toolbar_geometry(win) and _click_fields_button(win):
        return True
    for overflow in _toolbar_overflow_candidates(win):
        if not _click_control(overflow):
            continue
        if _click_fields_button(win):
            return True
        if _click_fields_by_toolbar_geometry(win) and _click_fields_button(win):
            return True
    return False


def _enable_serial_number_field(win):
    for c in _iter_toolbelt_controls(win, ("MenuItem", "CheckBox", "Text", "Button")):
        try:
            text = _control_label(c).lower()
            if text != "serial number":
                continue
            if hasattr(c, "is_visible") and not c.is_visible():
                continue
            try:
                if c.get_toggle_state() == 1:
                    return True
            except Exception:
                pass
            c.click_input()
            time.sleep(0.8)
            return True
        except Exception:
            continue
    return False


def _enable_serial_number_field_by_geometry(win):
    try:
        import pywinauto.mouse as mouse
    except Exception:
        return False
    rows = []
    for c in _iter_toolbelt_controls(win, ("Text", "CheckBox", "MenuItem", "Button")):
        try:
            text = _control_label(c).lower()
            if text != "serial number":
                continue
            if hasattr(c, "is_visible") and not c.is_visible():
                continue
            rect = c.rectangle()
            rows.append((rect.left, rect.top, rect.bottom))
        except Exception:
            continue
    for left, top, bottom in sorted(rows, key=lambda item: item[0]):
        y = (top + bottom) // 2
        for x in (left - 12, left - 18, left + 6):
            try:
                log.info("clicking Toolbelt Serial Number checkbox at %s,%s", x, y)
                mouse.click(coords=(x, y))
                time.sleep(0.8)
                return True
            except Exception:
                continue
    if _LAST_FIELDS_BUTTON_POINT is not None:
        fields_x, fields_y = _LAST_FIELDS_BUTTON_POINT
        for x, y in (
            (fields_x - 22, fields_y + 126),
            (fields_x - 28, fields_y + 126),
            (fields_x - 18, fields_y + 118),
            (fields_x - 18, fields_y + 134),
        ):
            try:
                log.info("clicking Toolbelt Serial Number checkbox from Fields geometry at %s,%s", x, y)
                mouse.click(coords=(x, y))
                time.sleep(0.8)
                return True
            except Exception:
                continue
    return False


def ensure_serial_column_visible(win, row_y=None):
    if _serial_column_visible(win, row_y=row_y):
        log.info("Toolbelt Serial Number column is visible")
        return True
    if not _open_fields_menu(win):
        log.warning("could not open Toolbelt Fields menu")
        return False
    _enable_serial_number_field(win)
    visible = _serial_column_visible(win, row_y=row_y)
    if not visible:
        _open_fields_menu(win)
        _enable_serial_number_field_by_geometry(win)
        visible = _serial_column_visible(win, row_y=row_y)
    if not visible:
        log.warning("could not enable Toolbelt Serial Number field")
        return False
    log.info("Toolbelt Serial Number column visible after Fields toggle: %s", visible)
    return visible


def _masked_secret(value):
    text = str(value or "")
    if len(text) <= 4:
        return "*" * len(text)
    return "%s...%s" % (text[:2], text[-2:])


def discover_serial_from_row(win, ip, row_y):
    serial_x = _serial_column_center(win, row_y=row_y)
    if serial_x is None:
        return None
    candidates = []
    for left, text in _discovery_row_cells(win, row_y):
        if text == ip:
            continue
        if _looks_like_serial(text):
            candidates.append((abs(left - serial_x), text))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0])[0][1]


def find_device_cell(win, ip):
    for control_type in ("Text", "Hyperlink"):
        for c in win.descendants(control_type=control_type):
            if (c.window_text() or "").strip() == ip:
                return c
    ensure_discovery_started(win, [ip], timeout=45, require_visible=False)
    for control_type in ("Text", "Hyperlink"):
        for c in win.descendants(control_type=control_type):
            if (c.window_text() or "").strip() == ip:
                return c
    return None


def _record_resolved_credential(ip, username, password):
    if not password:
        return
    _RESOLVED_CREDENTIALS[ip] = {"username": username or "admin", "password": password}
    emit("credentials_resolved", selector=ip, message="Resolved Toolbelt credentials from discovery serial number")
    _write_resolved_credentials()


def _write_resolved_credentials():
    if not _RESOLVED_CREDENTIALS_FILE or not _RESOLVED_CREDENTIALS:
        return
    tmp = _RESOLVED_CREDENTIALS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_RESOLVED_CREDENTIALS, f)
    os.replace(tmp, _RESOLVED_CREDENTIALS_FILE)


def _credentials_modal_present(win):
    joined = _credentials_modal_text(win)
    return any(
        marker in joined
        for marker in (
            "provide credentials",
            "credentials are incorrect",
            "credentials entered are incorrect",
            "failed to connect",
        )
    )


def _credentials_modal_text(win):
    try:
        texts = [win.window_text() or ""]
    except Exception:
        texts = []
    for control_type in ("Text", "Edit", "Button"):
        try:
            controls = win.descendants(control_type=control_type)
        except Exception:
            return True
        for c in controls:
            try:
                texts.append(c.window_text() or "")
            except Exception:
                pass
    return " ".join(texts).lower()


def _credentials_rejected_present(win):
    joined = _credentials_modal_text(win)
    return any(
        marker in joined
        for marker in (
            "credentials are incorrect",
            "credentials entered are incorrect",
            "failed to connect",
        )
    )



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
        if text in {"cancel", "close", "ok"} and b.is_visible():
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

def _accept_credentials_prompt_legacy(win, ip, timeout=8):
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


def _fill_credentials_password(win, password):
    _fill_credentials_fields(win, "admin", password)


def _paste_text(win, text):
    try:
        import pyperclip
        pyperclip.copy(text)
        win.type_keys("^v", set_foreground=True)
        return True
    except Exception:
        try:
            win.type_keys(text, with_spaces=True, set_foreground=True)
            return True
        except Exception:
            return False


def _fill_edit(edit, win, value):
    try:
        import pywinauto.mouse as mouse
        rect = edit.rectangle()
        mouse.click(coords=(cx(rect), cy(rect)))
        time.sleep(0.2)
        try:
            edit.set_edit_text(value)
            log.info("filled Toolbelt password edit via set_edit_text value=%s", _masked_secret(value))
            return True
        except Exception as exc:
            log.info("set_edit_text failed for Toolbelt password edit: %s", exc)
        try:
            edit.type_keys("^a{BACKSPACE}", set_foreground=True)
        except Exception:
            win.type_keys("^a{BACKSPACE}", set_foreground=True)
        if _paste_text(win, value):
            log.info("filled Toolbelt password edit via keyboard/clipboard value=%s", _masked_secret(value))
            return True
    except Exception:
        pass
    return False


def _password_label_rect(win):
    for c in win.descendants(control_type="Text"):
        try:
            if (c.window_text() or "").strip().lower() == "password":
                return c.rectangle()
        except Exception:
            continue
    return None


def _choose_password_edit(win, edits):
    label = _password_label_rect(win)
    if label is not None:
        candidates = []
        for edit in edits:
            try:
                rect = edit.rectangle()
                if rect.top < label.top - 5:
                    continue
                if rect.left < label.left - 10:
                    continue
                vertical_distance = abs(cy(rect) - (label.bottom + 18))
                horizontal_distance = abs(rect.left - label.left)
                candidates.append((vertical_distance, horizontal_distance, edit))
            except Exception:
                continue
        if candidates:
            log.info("selected Toolbelt password edit by Password label geometry")
            return sorted(candidates, key=lambda item: (item[0], item[1]))[0][2]
    return edits[-1] if edits else None


def _fill_credentials_fields(win, username, password):
    edits = []
    for edit in win.descendants(control_type="Edit"):
        try:
            if hasattr(edit, "is_visible") and not edit.is_visible():
                continue
            edits.append(edit)
        except Exception:
            continue
    edits = sorted(edits, key=lambda c: (c.rectangle().top, c.rectangle().left))
    log.info("Toolbelt credentials prompt visible edit count: %d", len(edits))
    if edits:
        edit = _choose_password_edit(win, edits)
        return _fill_edit(edit, win, password)

    try:
        import pywinauto.mouse as mouse
        plabel = next(
            c.rectangle()
            for c in win.descendants(control_type="Text")
            if (c.window_text() or "").strip() == "Password"
        )
        mouse.click(coords=(plabel.left + 40, plabel.bottom + 18))
        time.sleep(0.2)
        win.type_keys("^a{BACKSPACE}", set_foreground=True)
        _paste_text(win, password)
        return True
    except Exception:
        return False


def _click_credentials_enter(win):
    for b in win.descendants(control_type="Button"):
        text = (b.window_text() or "").strip().lower()
        if text in {"enter", "ok", "login", "log in", "connect", "try again"} and b.is_visible():
            log.info("clicking Toolbelt credentials button '%s'", text)
            b.click_input()
            return True
    try:
        log.info("submitting Toolbelt credentials with keyboard Enter")
        win.type_keys("{ENTER}", set_foreground=True)
        return True
    except Exception:
        return False


def _wait_for_credentials_result(win, ip, source):
    timeout = T_CREDENTIAL_ACCEPT
    deadline = time.time() + timeout
    last_busy_log = 0
    reject_grace = time.time() + 2.5
    while time.time() < deadline:
        try:
            if not _credentials_modal_present(win):
                return True
            if time.time() > reject_grace and _credentials_rejected_present(win):
                return False
        except Exception as exc:
            now = time.time()
            if now - last_busy_log > 5:
                log.info("[%s] waiting for Toolbelt credential result; UI busy: %s", ip, exc)
                last_busy_log = now
        time.sleep(POLL)
    return False


def _credential_candidates(credential, serial):
    seen = set()
    candidates = []

    def add(password, source):
        if not password or password == "__PREFILLED__" or password in seen:
            return
        seen.add(password)
        candidates.append((password, source))

    if _DEVICE_PASSWORD:
        add(_DEVICE_PASSWORD, "override")
    if credential.get("password"):
        add(credential["password"], "saved")
    for candidate in credential.get("password_candidates") or []:
        if candidate == "__SERIAL__":
            if serial:
                add(serial, "serial")
            continue
        add(candidate, "candidate")
    if serial:
        add(serial, "serial")
    return candidates


def accept_credentials_prompt(win, ip, timeout=8, serial=None):
    """Accept Toolbelt's credentials modal, retrying serial-number fallback."""
    deadline = time.time() + timeout
    while time.time() < deadline and not _credentials_modal_present(win):
        time.sleep(POLL)
    if not _credentials_modal_present(win):
        return False

    credential = _DEVICE_CREDENTIALS.get(ip) or {}
    raw_candidates = credential.get("password_candidates") or []
    candidates = _credential_candidates(credential, serial)
    log.info(
        "[%s] Toolbelt credential candidate sources: %s",
        ip,
        ", ".join(source for _, source in candidates) or "prefilled",
    )
    if "__SERIAL__" in raw_candidates and not serial:
        emit(
            "serial_column_missing",
            selector=ip,
            message=(
                "Serial-number password fallback needs the Serial Number column "
                "enabled in the Toolbelt discovery list. Choose Fields > Serial "
                "Number; if Fields is hidden, open the toolbar overflow menu, "
                "and if the column is off-screen, scroll right or move the splitter."
            ),
        )

    if not candidates:
        candidates = [(None, "prefilled")]

    for candidate_password, source in candidates:
        if candidate_password:
            log.info(
                "[%s] trying Toolbelt credential candidate source=%s value=%s",
                ip,
                source,
                _masked_secret(candidate_password),
            )
        else:
            log.info("[%s] trying Toolbelt prefilled credential candidate", ip)
        if candidate_password:
            _fill_credentials_password(win, candidate_password)
        if not _click_credentials_enter(win):
            break
        if _wait_for_credentials_result(win, ip, source):
            if source == "serial":
                _record_resolved_credential(
                    ip,
                    credential.get("username") or "admin",
                    candidate_password,
                )
            log.info("[%s] accepted credentials prompt", ip)
            return True
        log.info("[%s] Toolbelt credential candidate source=%s was rejected; trying next candidate if available", ip, source)

    if _credentials_modal_present(win):
        emit("credentials_needed", selector=ip, message="Credentials were rejected or are required")
        dismiss_credentials_prompt(win)
        raise RuntimeError(
            "credentials rejected for %s - all known Toolbelt credential attempts failed. "
            "If the device uses the serial number, choose Fields > Serial Number "
            "in Toolbelt discovery. If Fields is hidden, open the toolbar overflow "
            "menu; if the column is off-screen, scroll right or move the splitter." % ip)
    return True


def _find_text_control(win, text):
    for c in win.descendants(control_type="Text"):
        if (c.window_text() or "").strip() == text:
            return c
    return None


def _text_visible(win, text):
    return _find_text_control(win, text) is not None


def _wait_for_ui(win, ip, label, predicate, timeout=T_MANAGE):
    deadline = time.time() + timeout
    last_busy_log = 0
    while time.time() < deadline:
        try:
            result = predicate()
            if result is not None and result is not False:
                return result
        except Exception as exc:
            now = time.time()
            if now - last_busy_log > 10:
                log.info("[%s] waiting for %s; Toolbelt UI busy: %s", ip, label, exc)
                last_busy_log = now
        time.sleep(POLL)
    raise RuntimeError("timed out waiting for %s after %ss" % (label, timeout))


# ---------------------------------------------------------------------------
# Device selection + navigation  (task #2)
# ---------------------------------------------------------------------------
def select_device(win, ip, timeout=T_MANAGE):
    """Find the device row for `ip`, click Manage, then open the Utilities tab."""
    log.info("[%s] selecting device", ip)

    # Locate the IP cell in the discovery list
    ip_cell = find_device_cell(win, ip)
    if ip_cell is None:
        raise RuntimeError("device %s not found in discovery list (is discovery started?)" % ip)

    row_y = cy(ip_cell.rectangle())
    serial = None
    if _wants_serial_fallback(ip):
        if ensure_serial_column_visible(win, row_y=row_y):
            refreshed_cell = find_device_cell(win, ip)
            if refreshed_cell is not None:
                ip_cell = refreshed_cell
                row_y = cy(ip_cell.rectangle())
            serial = discover_serial_from_row(win, ip, row_y)
            if serial:
                log.info("[%s] prepared Toolbelt serial fallback %s", ip, _masked_secret(serial))
            else:
                log.warning("[%s] Serial Number column is visible but no serial was read from the row", ip)
        else:
            log.warning("[%s] Serial Number column is not visible; skipping serial password fallback", ip)
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
    accept_credentials_prompt(win, ip, serial=serial)

    # Wait for the Utilities tab to be available, then click it. Slow devices
    # can keep Toolbelt's UIA tree busy for over a minute after authentication.
    tab = _wait_for_ui(win, ip, "Utilities tab", lambda: _find_text_control(win, "Utilities"), timeout=timeout)
    tab.click_input()
    time.sleep(1.0)
    # Confirm the SSL section rendered
    _wait_for_ui(
        win,
        ip,
        "SSL certificate section",
        lambda: _text_visible(win, "View and upload SSL certificates"),
        timeout=timeout,
    )
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


def test_serial_column(app, win, ip):
    bring_to_front(win)
    ensure_discovery_started(win, [ip], timeout=45, require_visible=False)
    ip_cell = find_device_cell(win, ip)
    row_y = cy(ip_cell.rectangle()) if ip_cell is not None else None
    ok = ensure_serial_column_visible(win, row_y=row_y)
    serial = None
    if ok:
        ip_cell = find_device_cell(win, ip)
        row_y = cy(ip_cell.rectangle()) if ip_cell is not None else row_y
        serial = discover_serial_from_row(win, ip, row_y) if row_y is not None else None
        if serial:
            log.info("[%s] Serial Number column test read serial %s", ip, _masked_secret(serial))
        else:
            log.warning("[%s] Serial Number column visible but serial could not be read", ip)
    emit(
        "serial_column_test",
        selector=ip,
        ok=ok,
        serial_preview=_masked_secret(serial) if serial else None,
        message="Serial Number column visible" if ok else "Serial Number column not visible",
    )
    log.info("[%s] Serial Number column test result: %s", ip, ok)
    return ok


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
    ap.add_argument("--test-serial-column", action="store_true",
                    help="only test enabling Toolbelt's Serial Number discovery column")
    ap.add_argument("--device-password", default=None,
                    help="device admin password for the credentials prompt "
                         "(default: accept Toolbelt's prefilled value)")
    ap.add_argument("--device-password-file", default=None,
                    help="JSON credential file keyed by device selector; avoids secrets on the command line")
    ap.add_argument("--resolved-credentials-file", default=None,
                    help="JSON output file for credentials resolved during dry-run")
    ap.add_argument("--jsonl", action="store_true",
                    help="emit machine-readable JSONL progress events to stdout")
    ap.add_argument("--stop-file", default=None,
                    help="if this file appears, stop safely before starting the next device")
    args = ap.parse_args()

    global _DEVICE_PASSWORD, _DEVICE_CREDENTIALS, _RESOLVED_CREDENTIALS_FILE, _JSONL
    _DEVICE_PASSWORD = args.device_password
    _RESOLVED_CREDENTIALS_FILE = args.resolved_credentials_file
    _JSONL = args.jsonl
    if args.device_password_file:
        with open(args.device_password_file, encoding="utf-8-sig") as f:
            _DEVICE_CREDENTIALS = json.load(f)

    setup_logging()
    emit("log_file", path=LOG_FILE)
    if args.test_serial_column and not args.device:
        ap.error("--test-serial-column requires --device")
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
    log.info("connecting to Toolbelt...")
    app, win = connect_toolbelt()
    if args.test_serial_column:
        log.info("running Toolbelt Serial Number column test for %s", devices[0][0])
        ok = test_serial_column(app, win, devices[0][0])
        emit("run_finished", ok=1 if ok else 0, total=1, status="complete")
        return
    ensure_discovery_started(win, [ip for ip, _ in devices])

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
            if "credentials rejected" in str(e).lower():
                ok, msg = False, "ERROR: %s" % e
                log.error("[%s] %s", ip, msg)
            else:
                # Transient UI/window errors happen at scale; reconnect and retry once.
                log.info("[%s] error (%s) - reconnecting and retrying once", ip, e)
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
    _write_resolved_credentials()
    emit("run_finished", ok=n_ok, total=len(results), status="complete")


if __name__ == "__main__":
    main()
