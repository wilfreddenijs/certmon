"""Capture the real CertMon UI using disposable, fictional documentation data."""

import argparse
import gc
from datetime import datetime, timedelta, timezone
import importlib
import os
from pathlib import Path
import sys
import tempfile
import threading

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def seed(module):
    module.local_ca_service.generate_ca()
    now = datetime.now(timezone.utc)
    devices = [
        ("192.0.2.11", "TLP-Pro-1025M.example.test", "Self-signed", "warning", 34),
        ("192.0.2.12", "IPLP-Pro.example.test", "CertMon Local CA", "ok", 365),
        ("192.0.2.13", "ShareLink-Pro.example.test", "Enterprise Demo CA", "critical", 14),
    ]
    data = module.load_data()
    data["manual_hosts"] = [{"host": host, "port": 443} for host, *_ in devices]
    data["scan_ranges"] = ["192.0.2.0/24"]
    data["certificates"] = {
        f"{host}:443": {
            "host": host, "port": 443, "cn": name, "issuer": issuer,
            "not_before": (now - timedelta(days=100)).isoformat(),
            "not_after": (now + timedelta(days=days)).isoformat(),
            "days_remaining": days, "status": status, "sans": [name, host],
            "self_signed": issuer == "Self-signed",
            "cert_type": "Self-signed" if issuer == "Self-signed" else "CA-signed",
            "last_checked": now.isoformat(),
        } for host, name, issuer, status, days in devices
    }
    module.save_data(data)
    older = module.local_ca_service.issue(
        identifiers=(devices[0][1], devices[0][0]), profile_name="generic-rsa",
        device_name=devices[0][1],
    )
    with module.database.transaction() as connection:
        connection.execute("UPDATE certificates SET created_at=? WHERE id=?",
                           ((now - timedelta(days=1)).isoformat(), older["certificate_id"]))
    certificates = {}
    for host, name, *_ in devices[:2]:
        certificate = module.local_ca_service.issue(
            identifiers=(name, host), profile_name="extron-rsa", device_name=name
        )
        certificates[host] = certificate["certificate_id"]
    module.toolbelt_service.save_credentials(
        "192.0.2.11", username="admin", password="fictional-device-password"
    )
    module.renewal_service.create_job(
        endpoint_host="portal.example.test", endpoint_port=443, issuer_type="acme",
        identifiers=["portal.example.test"], profile="generic-rsa",
        environment="staging", dns_provider="manual",
    )
    module.renewal_service.create_job(
        endpoint_host="192.0.2.13", endpoint_port=443, issuer_type="external_ca",
        identifiers=["ShareLink-Pro.example.test", "192.0.2.13"], profile="generic-rsa",
        metadata={"external_ca_workflow": "csr"},
    )
    for host, success in (("192.0.2.11", True), ("192.0.2.12", False)):
        module.audit_service.record(
            "certificate_upload_succeeded" if success else "certificate_upload_failed",
            user="demo-admin", source_ip="127.0.0.1", target=host, success=success,
            details={"certificate_id": certificates[host], "method": "direct",
                     "result": "verified" if success else "connection_failed", "nic": 1},
        )
    return certificates


def capture(output):
    with tempfile.TemporaryDirectory(prefix="certmon-manual-") as temporary:
        os.environ["CERTMON_DATA_DIR"] = temporary
        os.environ["CERTMON_SERVER_MODE"] = "1"
        os.environ["CERTMON_BIND_HOST"] = "127.0.0.1"
        module = importlib.import_module("app")
        certificates = seed(module)
        server = make_server("127.0.0.1", 0, module.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
                page.set_default_timeout(15000)
                output.mkdir(parents=True, exist_ok=True)

                def screenshot(name):
                    page.evaluate("document.fonts.ready")
                    page.screenshot(path=str(output / name), animations="disabled")
                    print(name, flush=True)

                def tab(name):
                    page.locator(f'[data-tab="{name}"]').click()
                    page.locator(".content").evaluate("element => element.scrollTop = 0")

                # No screenshot operation may scan, upload, install trust, or start renewal.
                def restrict_operations(route):
                    request = route.request
                    url = request.url
                    if any(path in url for path in (
                        "/api/scan/start", "/api/refresh/", "/api/direct-extron/",
                        "/api/toolbelt/dry-run", "/api/toolbelt/upload", "/api/ca/install",
                        "/resume", "/api/deploy",
                    )):
                        route.fulfill(status=409, json={"error": "Disabled in documentation capture"})
                    else:
                        route.continue_()

                page.route("**/api/**", restrict_operations)
                page.goto(f"http://127.0.0.1:{server.server_port}")
                expect(page.locator("#auth-gate")).to_be_visible()
                screenshot("01-first-admin.png")
                page.locator("#auth-username").fill("demo-admin")
                page.locator("#auth-password").fill("manual-demo-only")
                page.locator("#auth-password-confirmation").fill("manual-demo-only")
                with page.expect_response("**/api/auth/setup-first-admin"):
                    page.locator("#auth-submit").click()
                expect(page.locator("#device-filter-count")).to_contain_text("3/3")
                screenshot("02-devices.png")
                page.locator("#device-name-filter").fill("ShareLink")
                page.locator("#device-select-filtered").check()
                expect(page.locator("#device-bulk-create-btn")).to_contain_text("1")
                screenshot("03-device-filters.png")
                page.locator("#device-name-filter").fill("")
                page.locator("#device-select-filtered").uncheck()
                page.evaluate("openDeviceLocalCAModal('192.0.2.13', 'ShareLink-Pro.example.test')")
                expect(page.locator("#device-ca-profile")).to_be_visible()
                screenshot("04-create-certificate.png")
                page.locator("#device-ca-cancel").click()

                tab("ca")
                expect(page.locator("#ca-content")).to_contain_text("Trust bundle")
                screenshot("05-local-ca.png")

                tab("upload")
                page.evaluate("async () => { await loadAvailableCertificates(); await loadToolbeltDevices(false); }")
                expect(page.locator(".upload-device-row")).to_have_count(2)
                page.evaluate("setPreparedUploadMethod('192.0.2.12', 'toolbelt')")
                screenshot("06-upload-list.png")
                page.evaluate("openDeviceCredentials('192.0.2.11')")
                expect(page.locator("#device-credentials-dialog")).to_be_visible()
                screenshot("07-device-credentials.png")
                page.locator("#device-credentials-dialog").evaluate("dialog => dialog.close()")
                page.evaluate("selectDeviceInterface('192.0.2.11', 2)")
                expect(page.locator("#direct-interface-dialog")).to_be_visible()
                page.locator("#direct-interface-host").fill("192.0.2.111")
                screenshot("08-lan-b.png")
                page.locator("#direct-interface-dialog").evaluate("dialog => dialog.close()")
                page.evaluate("selectPreparedDirectDevice('192.0.2.11')")
                expect(page.locator("#direct-extron-upload")).to_be_visible()
                screenshot("09-direct-upload.png")
                page.locator("#direct-extron-upload").evaluate("dialog => dialog.close()")

                page.locator("#manual-upload-fallback").evaluate("element => element.open = true")
                page.locator("#push-target-select").select_option(certificates["192.0.2.11"])
                expect(page.locator("#delete-stored-certificate")).to_be_visible()
                page.set_viewport_size({"width": 1440, "height": 1250})
                page.locator("#delete-stored-certificate").scroll_into_view_if_needed()
                screenshot("10-certificate-downloads.png")
                page.set_viewport_size({"width": 1440, "height": 1100})

                tab("renewals")
                expect(page.locator("#renewal-list")).to_contain_text("portal.example.test")
                screenshot("11-renewals.png")
                page.evaluate("openModal('portal.example.test', 443)")
                page.locator("#renewal-next").click()
                page.locator("#renewal-next").click()
                expect(page.locator("#renewal-profile")).to_be_visible()
                screenshot("12-renewal-wizard.png")
                page.evaluate("closeModal()")

                tab("audit")
                page.get_by_role("button", name="Refresh audit", exact=True).click()
                expect(page.locator("#audit-list")).to_contain_text("192.0.2.11")
                screenshot("13-audit.png")

                from certmon.auth import hash_password
                module.database.create_user(
                    user_id="demo-operator", username="demo-operator",
                    password_hash=hash_password("manual-demo-only"), roles=["operator"],
                )
                tab("admin")
                expect(page.locator("#administration-users")).to_contain_text("demo-operator")
                screenshot("14-administration.png")
                page.locator("#administration-role-info").scroll_into_view_if_needed()
                screenshot("15-users.png")
                page.locator("#administration-role-info").click()
                expect(page.locator("#role-permissions-dialog")).to_be_visible()
                screenshot("16-role-permissions.png")
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            gc.collect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "screenshots")
    capture(parser.parse_args().output.resolve())
