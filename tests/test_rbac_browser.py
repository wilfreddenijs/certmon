import base64
from datetime import datetime, timedelta, timezone
from importlib import import_module
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from certmon.permissions import Permission, ROLE_PERMISSIONS, permissions_for_roles


PASSWORD = "correct horse"
PUBLIC_MARKER = "browser-public-marker"
PRIVATE_MARKER = "browser-private-sentinel"
PUBLIC_ARTIFACTS = (
    "certificate.pem",
    "chain.pem",
    "full-chain.pem",
    "request.csr",
)
PUBLIC_DOWNLOADS = {
    "/api/ca/download-cert": b"-----BEGIN CERTIFICATE-----",
    "/api/ca/trust-bundle": b"PK",
    "/api/export/excel": b"PK",
    "/api/ca/devices-txt": b"browser-device.example.test",
}
ROLE_EXPECTATIONS = {
    role: frozenset(permission.value for permission in permissions)
    for role, permissions in ROLE_PERMISSIONS.items()
}
REPRESENTATIVE_UNIONS = (
    ("viewer-ca", ("viewer", "ca_admin")),
    ("operator-security", ("operator", "security_admin")),
)


def _request_paths(page):
    paths = []
    page.on("request", lambda request: paths.append(request.url))
    return paths


def _requested_paths(requests):
    return [urlparse(url).path for url in requests]


def _status_permissions(page):
    return set(
        page.evaluate(
            """async () => (await (await fetch('/api/auth/status')).json()).permissions"""
        )
    )


def _admin_request(page, method, path, body=None):
    return page.evaluate(
        """async ({method, path, body}) => {
            const status = await (await fetch('/api/auth/status')).json();
            const response = await fetch(path, {
                method,
                headers: {
                    'Content-Type': 'application/json',
                    [status.csrf_header]: status.csrf_token,
                },
                body: body === null ? undefined : JSON.stringify(body),
            });
            return {status: response.status, body: await response.json()};
        }""",
        {"method": method, "path": path, "body": body},
    )


def _create_user(page, username, roles):
    return _admin_request(
        page,
        "POST",
        "/api/users",
        {"username": username, "password": PASSWORD, "roles": list(roles)},
    )


def _replace_roles(page, user_id, roles):
    return _admin_request(page, "PATCH", f"/api/users/{user_id}", {"roles": list(roles)})


def _set_disabled(page, user_id, disabled):
    return _admin_request(page, "PATCH", f"/api/users/{user_id}", {"disabled": disabled})


def _reset_password(page, user_id, password):
    return _admin_request(page, "POST", f"/api/users/{user_id}/password", {"password": password})


def _create_admin(page, live_certmon):
    certmon = live_certmon(server_mode=True)
    page.goto(certmon.base_url)
    expect(page.locator("#auth-gate")).to_be_visible()
    page.locator("#auth-username").fill("browser-admin")
    page.locator("#auth-password").fill(PASSWORD)
    page.locator("#auth-password-confirmation").fill(PASSWORD)
    page.locator("#auth-submit").click()
    expect(page.locator(".main")).to_be_visible()
    return certmon, import_module("app")


def _sign_in(browser, certmon, username, password=PASSWORD, controlled_clock=False):
    context = browser.new_context()
    page = context.new_page()
    if controlled_clock:
        page.clock.install()
    page.goto(certmon.base_url)
    _submit_sign_in(page, username, password)
    expect(page.locator(".main")).to_be_visible()
    # Login reveals the shell before loadData finishes rendering device controls.
    expect(page.locator("#device-filter-count")).to_contain_text(" shown ")
    return context, page


def _submit_sign_in(page, username, password=PASSWORD):
    page.locator("#auth-username").fill(username)
    page.locator("#auth-password").fill(password)
    page.locator("#auth-submit").click()


def _seed_browser_artifacts(module):
    module.artifact_store.create_certificate_set(
        "browser-public-full",
        {name: f"{PUBLIC_MARKER}:{name}".encode() for name in PUBLIC_ARTIFACTS},
        {
            "private-key.pem": f"{PRIVATE_MARKER}:private".encode(),
            "combined.pem": f"{PRIVATE_MARKER}:combined".encode(),
        },
        {},
    )
    module.database.put_certificate(
        "browser-public-full",
        {
            "kind": "leaf",
            "identifiers": ["full.browser.example.test"],
            "profile": "generic-rsa",
        },
    )
    module.artifact_store.create_certificate_set(
        "browser-public-partial",
        {"certificate.pem": f"{PUBLIC_MARKER}:partial".encode()},
        {"private-key.pem": f"{PRIVATE_MARKER}:partial".encode()},
        {},
    )
    module.database.put_certificate(
        "browser-public-partial",
        {
            "kind": "leaf",
            "identifiers": ["partial.browser.example.test"],
            "profile": "generic-rsa",
        },
    )


def _seed_dynamic_browser_state(page, module):
    host = "browser-device.example.test"
    now = datetime.now(timezone.utc)
    data = module.load_data()
    data["certificates"][f"{host}:443"] = {
        "host": host,
        "port": 443,
        "cn": host,
        "issuer": "CertMon Browser Test CA",
        "not_before": (now - timedelta(days=1)).isoformat(),
        "not_after": (now + timedelta(days=14)).isoformat(),
        "days_remaining": 14,
        "status": "warning",
        "sans": [host],
        "self_signed": False,
        "cert_type": "CA-signed",
        "last_checked": now.isoformat(),
    }
    module.save_data(data)
    module.local_ca_service.generate_ca()
    issued = module.local_ca_service.issue(
        identifiers=(host,), profile_name="generic-rsa", device_name=host
    )
    renewal = module.renewal_service.create_job(
        endpoint_host="browser-renewal.example.test",
        endpoint_port=443,
        issuer_type="local_ca",
        identifiers=["browser-renewal.example.test"],
        profile="generic-rsa",
        environment="staging",
        dns_provider="manual",
    )
    return {"host": host, "issued_certificate_id": issued["certificate_id"], "renewal_id": renewal["id"]}


def _browser_fetch_bytes(page, path):
    payload = page.evaluate(
        """async path => {
            const response = await fetch(path);
            const bytes = new Uint8Array(await response.arrayBuffer());
            let binary = '';
            for (const byte of bytes) binary += String.fromCharCode(byte);
            return {status: response.status, body: btoa(binary)};
        }""",
        path,
    )
    assert payload["status"] == 200, path
    return base64.b64decode(payload["body"])


def _assert_dynamic_information_views(page, seeded):
    page.locator('[data-tab="certs"]').click()
    expect(page.locator("#cert-grid")).to_contain_text(seeded["host"])
    actions = page.locator("#cert-grid .cert-actions").inner_text()
    permissions = _status_permissions(page)
    assert ("Refresh" in actions) is (Permission.ISSUE_CERTIFICATE.value in permissions)
    assert ("Renew" in actions) is (Permission.ISSUE_CERTIFICATE.value in permissions)
    assert (
        "Upload" in actions or "Create certificate" in actions
    ) is (Permission.MANAGE_LOCAL_CA.value in permissions)
    page.locator('[data-tab="renewals"]').click()
    expect(page.locator("#renewal-list")).to_contain_text("browser-renewal.example.test")
    for state in (
        "draft", "awaiting_dns", "awaiting_external_ca", "cleanup_required",
        "issued", "deployment_pending", "deployed", "failed", "cancelled",
    ):
        page.evaluate(
            """({id, state}) => renderRenewals([{
                id, state, endpoint_host: 'browser-renewal.example.test',
                endpoint_port: 443, issuer_type: 'external_ca', profile: 'generic-rsa',
                identifiers: [], metadata: {external_ca_workflow: 'existing'},
            }])""",
            {"id": seeded["renewal_id"], "state": state},
        )
        mutation_buttons = page.locator("#renewal-list button[onclick]")
        if Permission.ISSUE_CERTIFICATE.value not in permissions:
            expect(mutation_buttons).to_have_count(0)
        else:
            assert mutation_buttons.count() > 0
        expect(page.locator('#renewal-list button', has_text="Deploy now")).to_have_count(
            int(state == "issued" and Permission.DEPLOY_CERTIFICATE.value in permissions)
        )
        expect(page.locator('#renewal-list button', has_text="Download CSR")).to_have_count(
            int(state == "awaiting_external_ca")
        )
    page.locator('[data-tab="ca"]').click()
    expect(page.locator("#ca-content")).to_contain_text(seeded["host"])
    expect(
        page.locator(
            f'#ca-content a[href="/api/ca/download/{seeded["issued_certificate_id"]}"]'
        )
    ).to_have_count(1)


def _assert_permission_visibility(page, permissions):
    visibility = page.evaluate(
        """() => ({
            required: [...document.querySelectorAll('[data-required-permission]')].map(element => ({
                permission: element.dataset.requiredPermission,
                hidden: element.hidden,
            })),
            any: [...document.querySelectorAll('[data-any-permission]')].map(element => ({
                permissions: element.dataset.anyPermission.split(/\\s+/).filter(Boolean),
                hidden: element.hidden,
            })),
            tabs: [...document.querySelectorAll('.tab[data-tab]')].map(tab => ({
                name: tab.dataset.tab,
                hidden: tab.hidden,
            })),
        })"""
    )
    for item in visibility["required"]:
        assert item["hidden"] is (item["permission"] not in permissions), item
    for item in visibility["any"]:
        assert item["hidden"] is (not bool(set(item["permissions"]) & permissions))
    for element in page.locator("[data-required-permission]").all():
        if element.get_attribute("data-required-permission") not in permissions:
            expect(element).to_be_hidden()
    for element in page.locator("[data-any-permission]").all():
        required = set(element.get_attribute("data-any-permission").split())
        if not required & permissions:
            expect(element).to_be_hidden()
    visible_tabs = {item["name"] for item in visibility["tabs"] if not item["hidden"]}
    expected_tabs = {"certs", "renewals"}
    if Permission.DOWNLOAD_PUBLIC_CERTIFICATE.value in permissions:
        expected_tabs.update({"ca", "upload"})
    if Permission.VIEW_AUDIT.value in permissions:
        expected_tabs.add("audit")
    if permissions & {
        Permission.MANAGE_USERS.value,
        Permission.MANAGE_SERVER_BACKUP.value,
    }:
        expected_tabs.add("admin")
    assert visible_tabs == expected_tabs
    for tab in sorted(visible_tabs):
        page.locator(f'[data-tab="{tab}"]').click()
        expect(page.locator(f"#tab-{tab}")).to_be_visible()


def _assert_no_unauthorized_loaders(requests, permissions):
    paths = _requested_paths(requests)
    restricted_loaders = {
        "/api/certificates": Permission.DEPLOY_CERTIFICATE.value,
        "/api/audit": Permission.VIEW_AUDIT.value,
        "/api/users": Permission.MANAGE_USERS.value,
        "/api/backup/status": Permission.MANAGE_SERVER_BACKUP.value,
        "/api/toolbelt/devices": Permission.DEPLOY_CERTIFICATE.value,
    }
    for path, required_permission in restricted_loaders.items():
        if required_permission not in permissions:
            assert path not in paths, (path, permissions, paths)


def _assert_public_upload_links(page, certificate_id, expected_artifacts):
    page.locator('[data-tab="upload"]').click()
    if not page.locator("#push-target-select").is_visible():
        page.locator("#manual-upload-fallback summary").click()
    expect(page.locator("#push-target-select")).to_be_visible()
    page.locator("#push-target-select").select_option(certificate_id)
    page.locator("#push-btn").click()
    links = page.locator("#push-public-artifact-links a")
    expect(links).to_have_count(len(expected_artifacts))
    assert {link.get_attribute("href") for link in links.all()} == {
        f"/api/certificates/{certificate_id}/public/{artifact}"
        for artifact in expected_artifacts
    }
    missing_artifacts = set(PUBLIC_ARTIFACTS) - set(expected_artifacts)
    assert all(
        page.locator(
            f'#push-public-artifact-links a[href="/api/certificates/{certificate_id}/public/{artifact}"]'
        ).count()
        == 0
        for artifact in missing_artifacts
    )


def _assert_private_sentinel_never_reaches_browser(page):
    assert PRIVATE_MARKER not in page.content()
    assert PRIVATE_MARKER not in page.evaluate("() => document.documentElement.innerText")


@pytest.mark.parametrize("role", tuple(ROLE_EXPECTATIONS))
def test_standalone_roles_match_effective_permissions_and_rendered_controls(
    page, live_certmon, role
):
    certmon, module = _create_admin(page, live_certmon)
    seeded = _seed_dynamic_browser_state(page, module)
    created = _create_user(page, f"matrix-{role}", [role])
    assert created["status"] == 201

    context, role_page = _sign_in(page.context.browser, certmon, f"matrix-{role}")
    requests = _request_paths(role_page)
    try:
        role_page.reload()
        expect(role_page.locator(".main")).to_be_visible()
        permissions = _status_permissions(role_page)
        assert permissions == ROLE_EXPECTATIONS[role]
        _assert_permission_visibility(role_page, permissions)
        _assert_dynamic_information_views(role_page, seeded)
        _assert_no_unauthorized_loaders(requests, permissions)
    finally:
        context.close()


def test_administration_role_information_matches_authoritative_permissions(page, live_certmon, tmp_path):
    _create_admin(page, live_certmon)
    page.locator('[data-tab="admin"]').click()
    info = page.get_by_role("button", name="Roles and permissions", exact=True)
    info.click()
    dialog = page.get_by_role("dialog", name="Roles and permissions", exact=True)
    expect(dialog).to_be_visible()
    for permission in Permission:
        row = dialog.locator(f'tr[data-permission="{permission.value}"]')
        expect(row).to_have_count(1)
        for role, granted in ROLE_PERMISSIONS.items():
            expect(row.locator(f'td[data-role="{role}"]')).to_have_text(
                "Yes" if permission in granted else "No"
            )
    for width in (1440, 390):
        page.set_viewport_size({"width": width, "height": 900})
        box = dialog.bounding_box()
        assert box["x"] >= 0
        assert box["x"] + box["width"] <= width
        page.screenshot(path=str(tmp_path / f"role-permissions-{width}.png"))
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    info.click()
    dialog.get_by_role("button", name="Close", exact=True).click()
    expect(dialog).not_to_be_visible()


def test_administration_enable_disable_controls_stay_adjacent(page, live_certmon):
    _create_admin(page, live_certmon)
    assert _create_user(page, "toggle-viewer", ["viewer"])["status"] == 201
    page.locator('[data-tab="admin"]').click()
    row = page.locator(".admin-user-row").filter(has_text="toggle-viewer")
    enable = row.get_by_role("button", name="Enable", exact=True)
    disable = row.get_by_role("button", name="Disable", exact=True)
    expect(enable).to_be_disabled()
    expect(disable).to_be_enabled()
    for width in (1440, 390):
        page.set_viewport_size({"width": width, "height": 900})
        enable_box = enable.bounding_box()
        disable_box = disable.bounding_box()
        assert abs(enable_box["y"] - disable_box["y"]) < 1
        assert enable_box["x"] + enable_box["width"] <= disable_box["x"]
    page.on("dialog", lambda dialog: dialog.accept())
    disable.click()
    expect(enable).to_be_enabled()
    expect(disable).to_be_disabled()
    enable.click()
    expect(enable).to_be_disabled()
    expect(disable).to_be_enabled()


@pytest.mark.parametrize(("username", "roles"), REPRESENTATIVE_UNIONS)
def test_additive_roles_render_exact_status_permission_union(
    page, live_certmon, username, roles
):
    certmon, module = _create_admin(page, live_certmon)
    seeded = _seed_dynamic_browser_state(page, module)
    created = _create_user(page, username, roles)
    assert created["status"] == 201

    context, role_page = _sign_in(page.context.browser, certmon, username)
    requests = _request_paths(role_page)
    try:
        permissions = _status_permissions(role_page)
        expected = {permission.value for permission in permissions_for_roles(roles)}
        assert permissions == expected
        _assert_permission_visibility(role_page, permissions)
        _assert_dynamic_information_views(role_page, seeded)
        _assert_no_unauthorized_loaders(requests, permissions)
    finally:
        context.close()


def test_viewer_sees_only_existing_public_artifacts_and_never_private_data(
    page, live_certmon
):
    certmon, module = _create_admin(page, live_certmon)
    _seed_browser_artifacts(module)
    _seed_dynamic_browser_state(page, module)
    created = _create_user(page, "browser-viewer", ["viewer"])
    assert created["status"] == 201

    context, viewer_page = _sign_in(page.context.browser, certmon, "browser-viewer")
    requests = _request_paths(viewer_page)
    try:
        viewer_page.reload()
        expect(viewer_page.locator(".main")).to_be_visible()
        _assert_public_upload_links(viewer_page, "browser-public-full", PUBLIC_ARTIFACTS)
        _assert_public_upload_links(viewer_page, "browser-public-partial", ("certificate.pem",))
        public_responses = {
            f"/api/certificates/browser-public-full/public/{artifact}": _browser_fetch_bytes(
                viewer_page, f"/api/certificates/browser-public-full/public/{artifact}"
            )
            for artifact in PUBLIC_ARTIFACTS
        }
        public_responses.update(
            {path: _browser_fetch_bytes(viewer_page, path) for path in PUBLIC_DOWNLOADS}
        )
        for path, expected_bytes in PUBLIC_DOWNLOADS.items():
            assert expected_bytes in public_responses[path], path
        assert all(
            f"{PUBLIC_MARKER}:{artifact}".encode() in public_responses[
                f"/api/certificates/browser-public-full/public/{artifact}"
            ]
            for artifact in PUBLIC_ARTIFACTS
        )
        assert all(PRIVATE_MARKER.encode() not in body for body in public_responses.values())
        expect(viewer_page.locator("#push-private-artifacts")).to_be_hidden()
        expect(viewer_page.locator("#toolbelt-batch")).to_be_hidden()
        _assert_private_sentinel_never_reaches_browser(viewer_page)
        assert any("/api/certificates/public" in url for url in requests)
        assert not any("/api/certificates/" in url and "/private/" in url for url in requests)
        _assert_no_unauthorized_loaders(requests, ROLE_EXPECTATIONS["viewer"])
    finally:
        context.close()


def _assert_no_live_permission_refresh(page, protected_snapshot, requests):
    page.clock.fast_forward(15000)
    page.evaluate(
        """() => new Promise(resolve => requestAnimationFrame(
            () => requestAnimationFrame(resolve)
        ))"""
    )
    assert page.locator(".main").inner_text() == protected_snapshot
    assert not any("/api/auth/status" in url or "/api/permissions" in url for url in requests)


def _assert_next_protected_request_clears_session(page, requests):
    page.locator('[data-tab="audit"]').click()
    page.get_by_role("button", name="Refresh audit").click()
    expect(page.locator("#auth-gate")).to_be_visible(timeout=5000)
    expect(page.locator(".main")).to_be_hidden()
    assert sum("/api/audit?limit=100" in url for url in requests) == 1
    assert sum("/api/auth/status" in url for url in requests) == 1
    assert PRIVATE_MARKER not in page.content()
    assert page.locator('[data-tab="audit"]').is_hidden()


@pytest.mark.parametrize("mutation", ("roles", "disabled", "password", "expired"))
def test_next_protected_request_clears_revoked_or_expired_session(
    page, live_certmon, mutation
):
    certmon, module = _create_admin(page, live_certmon)
    created = _create_user(page, f"browser-{mutation}", ["security_admin"])
    assert created["status"] == 201
    user = created["body"]["user"]

    context, target_page = _sign_in(
        page.context.browser, certmon, f"browser-{mutation}", controlled_clock=True
    )
    requests = _request_paths(target_page)
    try:
        expect(target_page.locator('[data-tab="audit"]')).to_be_visible()
        protected_snapshot = target_page.locator(".main").inner_text()
        if mutation == "roles":
            assert _replace_roles(page, user["id"], ["viewer"])["status"] == 200
        elif mutation == "disabled":
            assert _set_disabled(page, user["id"], True)["status"] == 200
        elif mutation == "password":
            assert _reset_password(page, user["id"], "replacement horse")["status"] == 200
        else:
            with module.database.transaction() as connection:
                connection.execute(
                    "UPDATE sessions SET expires_at=? WHERE user_id=?",
                    (
                        (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                        user["id"],
                    ),
                )
        _assert_no_live_permission_refresh(target_page, protected_snapshot, requests)
        _assert_next_protected_request_clears_session(target_page, requests)
        if mutation == "disabled":
            _submit_sign_in(target_page, f"browser-{mutation}")
            expect(target_page.locator("#auth-error")).to_contain_text("Invalid")
            assert _set_disabled(page, user["id"], False)["status"] == 200
            _submit_sign_in(target_page, f"browser-{mutation}")
            expect(target_page.locator(".main")).to_be_visible()
        elif mutation == "password":
            _submit_sign_in(target_page, f"browser-{mutation}")
            expect(target_page.locator("#auth-error")).to_contain_text("Invalid")
            _submit_sign_in(target_page, f"browser-{mutation}", "replacement horse")
            expect(target_page.locator(".main")).to_be_visible()
    finally:
        context.close()


def test_desktop_mode_keeps_full_local_controls_without_authentication_gate(
    page, live_certmon
):
    certmon = live_certmon(server_mode=False)
    page.goto(certmon.base_url)

    expect(page.locator(".main")).to_be_visible()
    expect(page.locator("#auth-gate")).to_be_hidden()
    permissions = _status_permissions(page)
    assert permissions == {permission.value for permission in Permission}
    _assert_permission_visibility(page, permissions)
