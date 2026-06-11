"""
CertMon - TLS Certificate Monitor & ACME Renewal Tool
Scans network devices for TLS certificates and manages renewals via ACME/Let's Encrypt
"""

import sys
import ssl
import socket
import json
import os
import subprocess
import threading
import ipaddress
import io
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, render_template, request, jsonify, send_file


def resource_path(relative):
    """Get absolute path — works for dev and PyInstaller bundle."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def data_dir():
    """Writable directory next to the .exe (or script)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


app = Flask(__name__, template_folder=resource_path("templates"))

# Persistent storage
DATA_FILE = os.path.join(data_dir(), "certmon_data.json")
ACME_STAGING = "https://acme-staging-v02.api.letsencrypt.org/directory"
ACME_PROD = "https://acme-v02.api.letsencrypt.org/directory"

COMMON_TLS_PORTS = [443, 8443, 8080, 4443, 9443, 4523]

scan_progress = {"running": False, "progress": 0, "total": 0, "current": ""}


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"manual_hosts": [], "scan_ranges": [], "certificates": {}, "renewals": []}


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_cert_info(host, port=443, timeout=3):
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        conn = ctx.wrap_socket(
            socket.create_connection((host, port), timeout=timeout),
            server_hostname=host
        )
        cert_der = conn.getpeercert(binary_form=True)
        conn.close()

        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
        cert = x509.load_der_x509_certificate(cert_der, default_backend())

        now = datetime.now(timezone.utc)
        not_after = cert.not_valid_after_utc
        not_before = cert.not_valid_before_utc
        days_remaining = (not_after - now).days

        try:
            cn = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value
        except Exception:
            cn = host

        try:
            san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            sans = san_ext.value.get_values_for_type(x509.DNSName)
        except Exception:
            sans = []

        try:
            issuer = cert.issuer.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value
        except Exception:
            issuer = "Unknown"

        try:
            issuer_org = cert.issuer.get_attributes_for_oid(x509.NameOID.ORGANIZATION_NAME)[0].value
        except Exception:
            issuer_org = None

        # Self-signed: subject DN == issuer DN
        self_signed = cert.subject == cert.issuer
        cert_type = "Self-signed" if self_signed else f"CA: {issuer_org or issuer}"

        if days_remaining < 0:
            status = "expired"
        elif days_remaining <= 20:
            status = "critical"
        elif days_remaining <= 47:
            status = "warning"
        else:
            status = "ok"

        return {
            "host": host, "port": port, "cn": cn, "issuer": issuer,
            "issuer_org": issuer_org, "self_signed": self_signed,
            "cert_type": cert_type, "sans": sans,
            "not_before": not_before.isoformat(), "not_after": not_after.isoformat(),
            "days_remaining": days_remaining, "status": status,
            "serial": str(cert.serial_number),
            "last_checked": now.isoformat(), "error": None
        }
    except (socket.timeout, ConnectionRefusedError, OSError):
        return None
    except Exception as e:
        return {
            "host": host, "port": port, "cn": host, "issuer": "N/A", "sans": [],
            "not_before": None, "not_after": None, "days_remaining": None,
            "status": "error", "serial": None,
            "last_checked": datetime.now(timezone.utc).isoformat(), "error": str(e)
        }


def scan_host(host):
    results = []
    for port in COMMON_TLS_PORTS:
        info = get_cert_info(host, port)
        if info and info.get("error") is None:
            results.append(info)
    return results


def scan_range_worker(ip_range):
    global scan_progress
    try:
        network = ipaddress.ip_network(ip_range, strict=False)
        hosts = list(network.hosts())
        scan_progress["total"] = len(hosts)
        scan_progress["progress"] = 0
        found = []
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = {executor.submit(scan_host, str(ip)): str(ip) for ip in hosts}
            for future in as_completed(futures):
                ip = futures[future]
                scan_progress["current"] = ip
                scan_progress["progress"] += 1
                try:
                    results = future.result()
                    found.extend(results)
                except Exception:
                    pass
        return found
    except Exception:
        return []


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def api_data():
    return jsonify(load_data())


@app.route("/api/hosts", methods=["POST"])
def add_host():
    data = load_data()
    body = request.json
    host = body.get("host", "").strip()
    port = int(body.get("port", 443))
    if not host:
        return jsonify({"error": "No host provided"}), 400
    entry = {"host": host, "port": port}
    if entry not in data["manual_hosts"]:
        data["manual_hosts"].append(entry)
    info = get_cert_info(host, port)
    if info:
        data["certificates"][f"{host}:{port}"] = info
    save_data(data)
    return jsonify({"ok": True, "cert": info})


@app.route("/api/hosts/<path:host_port>", methods=["DELETE"])
def remove_host(host_port):
    data = load_data()
    parts = host_port.rsplit(":", 1)
    host = parts[0]
    port = int(parts[1]) if len(parts) > 1 else 443
    data["manual_hosts"] = [h for h in data["manual_hosts"]
                             if not (h["host"] == host and h["port"] == port)]
    data["certificates"].pop(f"{host}:{port}", None)
    save_data(data)
    return jsonify({"ok": True})


@app.route("/api/refresh/<path:host_port>", methods=["POST"])
def refresh_host(host_port):
    data = load_data()
    parts = host_port.rsplit(":", 1)
    host = parts[0]
    port = int(parts[1]) if len(parts) > 1 else 443
    info = get_cert_info(host, port)
    if info:
        data["certificates"][f"{host}:{port}"] = info
        save_data(data)
    return jsonify({"ok": True, "cert": info})


@app.route("/api/scan/ranges", methods=["POST"])
def add_range():
    data = load_data()
    body = request.json
    ip_range = body.get("range", "").strip()
    if not ip_range:
        return jsonify({"error": "No range provided"}), 400
    try:
        ipaddress.ip_network(ip_range, strict=False)
    except ValueError:
        return jsonify({"error": "Invalid CIDR range"}), 400
    if ip_range not in data["scan_ranges"]:
        data["scan_ranges"].append(ip_range)
        save_data(data)
    return jsonify({"ok": True})


@app.route("/api/scan/ranges/<path:ip_range>", methods=["DELETE"])
def remove_range(ip_range):
    data = load_data()
    data["scan_ranges"] = [r for r in data["scan_ranges"] if r != ip_range]
    save_data(data)
    return jsonify({"ok": True})


@app.route("/api/scan/start", methods=["POST"])
def start_scan():
    global scan_progress
    if scan_progress["running"]:
        return jsonify({"error": "Scan already running"}), 400
    data = load_data()
    ranges = data.get("scan_ranges", [])
    if not ranges:
        return jsonify({"error": "No scan ranges configured"}), 400

    def run_scan():
        global scan_progress
        scan_progress["running"] = True
        d = load_data()
        for ip_range in ranges:
            scan_progress["current"] = f"Scanning {ip_range}..."
            results = scan_range_worker(ip_range)
            for cert in results:
                key = f"{cert['host']}:{cert['port']}"
                d["certificates"][key] = cert
                entry = {"host": cert["host"], "port": cert["port"]}
                if entry not in d["manual_hosts"]:
                    d["manual_hosts"].append(entry)
            save_data(d)
        scan_progress["running"] = False
        scan_progress["current"] = "Done"

    threading.Thread(target=run_scan, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/scan/progress")
def scan_progress_api():
    return jsonify(scan_progress)


@app.route("/api/renew", methods=["POST"])
def create_renewal():
    data = load_data()
    body = request.json
    host = body.get("host")
    port = body.get("port", 443)
    method = body.get("method", "manual")
    staging = body.get("staging", False)
    acme_server = ACME_STAGING if staging else ACME_PROD

    renewal = {
        "id": len(data["renewals"]) + 1,
        "host": host, "port": port, "method": method, "staging": staging,
        "created": datetime.now(timezone.utc).isoformat(), "log": []
    }

    if method == "certbot":
        renewal["command"] = f"certbot certonly --standalone -d {host} --server {acme_server} --non-interactive --agree-tos -m admin@{host}"
        renewal["status"] = "ready"
    elif method == "acme.sh":
        renewal["command"] = f"acme.sh --issue -d {host} --standalone --server {acme_server}"
        renewal["status"] = "ready"
    else:
        renewal["status"] = "manual"
        renewal["command"] = None
        renewal["log"].append("Manual renewal — use your CA's renewal process")

    data["renewals"].append(renewal)
    save_data(data)
    return jsonify({"ok": True, "renewal": renewal})


@app.route("/api/renewals")
def list_renewals():
    return jsonify(load_data().get("renewals", []))


@app.route("/api/renewals/<int:renewal_id>", methods=["DELETE"])
def delete_renewal(renewal_id):
    data = load_data()
    data["renewals"] = [r for r in data["renewals"] if r.get("id") != renewal_id]
    save_data(data)
    return jsonify({"ok": True})


@app.route("/api/export/excel")
def export_excel():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    data = load_data()
    certs = list(data.get("certificates", {}).values())

    wb = Workbook()
    ws = wb.active
    ws.title = "Certificates"

    thin = Side(style="thin", color="CCCCCC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws.merge_cells("A1:I1")
    title_cell = ws["A1"]
    title_cell.value = f"CertMon — TLS Certificate Report  |  Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    title_cell.font = Font(name="Arial", bold=True, size=13, color="00E5FF")
    title_cell.fill = PatternFill("solid", fgColor="0D1220")
    title_cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 28

    counts = {s: sum(1 for c in certs if c.get("status") == s)
              for s in ("ok", "warning", "critical", "expired", "error")}
    ws.merge_cells("A2:I2")
    ws["A2"].value = (f"Total: {len(certs)}   OK: {counts['ok']}   "
                      f"Warning: {counts['warning']}   Critical: {counts['critical']}   "
                      f"Expired: {counts['expired']}")
    ws["A2"].font = Font(name="Arial", size=10, color="444444")
    ws["A2"].fill = PatternFill("solid", fgColor="EEF2FF")
    ws["A2"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[2].height = 20

    headers = ["Host", "Port", "Common Name", "Issuer", "Type", "Status",
               "Days Left", "Issued", "Expires", "Last Checked"]
    ws.row_dimensions[3].height = 22
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=3, column=col, value=h)
        cell.font = Font(name="Arial", bold=True, size=10, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2D3A5A")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    order = {"critical": 0, "expired": 1, "warning": 2, "error": 3, "ok": 4}
    certs.sort(key=lambda c: order.get(c.get("status", "error"), 5))

    status_colors = {
        "ok":       ("C8F7DC", "1A7A3D"),
        "warning":  ("FFF3CC", "7A5200"),
        "critical": ("FFD6D6", "7A0000"),
        "expired":  ("EEEEEE", "555555"),
        "error":    ("F5F5F5", "888888"),
    }

    def fmt_date(iso):
        if not iso:
            return ""
        try:
            return datetime.fromisoformat(iso).strftime("%Y-%m-%d")
        except Exception:
            return iso

    for i, cert in enumerate(certs):
        row = i + 4
        status = cert.get("status", "error")
        bg, fg = status_colors.get(status, ("F5F5F5", "888888"))
        alt_bg = "FFFFFF" if i % 2 == 0 else "F8FAFC"
        days = cert.get("days_remaining")
        values = [cert.get("host", ""), cert.get("port", ""), cert.get("cn", ""),
                  cert.get("issuer", ""), cert.get("cert_type", "Unknown"), status.upper(),
                  str(days) if days is not None else "N/A",
                  fmt_date(cert.get("not_before")), fmt_date(cert.get("not_after")),
                  fmt_date(cert.get("last_checked"))]
        ws.row_dimensions[row].height = 18
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=val)
            cell.font = Font(name="Arial", size=10,
                             color=fg if col == 5 else "222222", bold=(col == 5))
            cell.fill = PatternFill("solid", fgColor=bg if col == 5 else alt_bg)
            cell.alignment = Alignment(
                horizontal="center" if col in (2, 5, 6, 7, 8, 9) else "left",
                vertical="center")
            cell.border = border

    col_widths = [20, 8, 28, 30, 18, 12, 10, 14, 14, 16]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:J{3 + len(certs)}"

    ws2 = wb.create_sheet("Renewals")
    r_headers = ["Host", "Port", "Method", "Environment", "Status", "Created", "Command"]
    for col, h in enumerate(r_headers, 1):
        cell = ws2.cell(row=1, column=col, value=h)
        cell.font = Font(name="Arial", bold=True, size=10, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2D3A5A")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    for i, r in enumerate(data.get("renewals", []), 2):
        vals = [r.get("host"), r.get("port"), r.get("method"),
                "Staging" if r.get("staging") else "Production",
                r.get("status", "").upper(), fmt_date(r.get("created")), r.get("command", "")]
        for col, val in enumerate(vals, 1):
            cell = ws2.cell(row=i, column=col, value=val)
            cell.font = Font(name="Arial", size=10)
            cell.alignment = Alignment(horizontal="left", vertical="center",
                                       wrap_text=(col == 7))
            cell.border = border
    for i, w in enumerate([20, 8, 12, 14, 12, 14, 60], 1):
        ws2.column_dimensions[get_column_letter(i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"certmon_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    from flask import Response
    response = Response(
        buf.getvalue(),
        status=200,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


if __name__ == "__main__":
    os.makedirs(data_dir(), exist_ok=True)
    print("CertMon running at http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
