from datetime import datetime, timedelta, timezone
from importlib import import_module

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


def _sign_in(browser, certmon, username, password=PASSWORD):
    context = browser.new_context()
    page = context.new_page()
    page.goto(certmon.base_url)
    page.locator("#auth-username").fill(username)
    page.locator("#auth-password").fill(password)
    page.locator("#auth-submit").click()
    expect(page.locator(".main")).to_be_visible()
    return context, page


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
        assert item["hidden"] is (item["permission"] not in permissions)
    for item in visibility["any"]:
        assert item["hidden"] is (not bool(set(item["permissions"]) & permissions))
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


def _assert_public_upload_links(page, certificate_id, expected_artifacts):
    page.locator('[data-tab="upload"]').click()
    page.locator("#push-target-select").select_option(certificate_id)
    page.locator("#push-btn").click()
    links = page.locator("#push-public-artifact-links a")
    expect(links).to_have_count(len(expected_artifacts))
    assert {link.get_attribute("href") for link in links.all()} == {
        f"/api/certificates/{certificate_id}/public/{artifact}"
        for artifact in expected_artifacts
    }


def _assert_private_sentinel_never_reaches_browser(page):
    assert PRIVATE_MARKER not in page.content()
    assert PRIVATE_MARKER not in page.evaluate("() => document.documentElement.innerText")


@pytest.mark.parametrize("role", tuple(ROLE_EXPECTATIONS))
def test_standalone_roles_match_effective_permissions_and_rendered_controls(
    page, live_certmon, role
):
    certmon, _module = _create_admin(page, live_certmon)
    created = _create_user(page, f"browser-{role}", [role])
    assert created["status"] == 201

    context, role_page = _sign_in(page.context.browser, certmon, f"browser-{role}")
    requests = _request_paths(role_page)
    try:
        role_page.reload()
        expect(role_page.locator(".main")).to_be_visible()
        permissions = _status_permissions(role_page)
        assert permissions == ROLE_EXPECTATIONS[role]
        _assert_permission_visibility(role_page, permissions)
        assert not any("/api/users" in url for url in requests if role != "admin")
        assert not any("/api/audit" in url for url in requests if role != "security_admin")
    finally:
        context.close()


@pytest.mark.parametrize(("username", "roles"), REPRESENTATIVE_UNIONS)
def test_additive_roles_render_exact_status_permission_union(
    page, live_certmon, username, roles
):
    certmon, _module = _create_admin(page, live_certmon)
    created = _create_user(page, username, roles)
    assert created["status"] == 201

    context, role_page = _sign_in(page.context.browser, certmon, username)
    try:
        permissions = _status_permissions(role_page)
        expected = {permission.value for permission in permissions_for_roles(roles)}
        assert permissions == expected
        _assert_permission_visibility(role_page, permissions)
    finally:
        context.close()


def test_viewer_sees_only_existing_public_artifacts_and_never_private_data(
    page, live_certmon
):
    certmon, module = _create_admin(page, live_certmon)
    _seed_browser_artifacts(module)
    created = _create_user(page, "browser-viewer", ["viewer"])
    assert created["status"] == 201

    context, viewer_page = _sign_in(page.context.browser, certmon, "browser-viewer")
    requests = _request_paths(viewer_page)
    try:
        viewer_page.reload()
        expect(viewer_page.locator(".main")).to_be_visible()
        _assert_public_upload_links(viewer_page, "browser-public-full", PUBLIC_ARTIFACTS)
        _assert_public_upload_links(viewer_page, "browser-public-partial", ("certificate.pem",))
        expect(viewer_page.locator("#push-private-artifacts")).to_be_hidden()
        expect(viewer_page.locator("#toolbelt-batch")).to_be_hidden()
        _assert_private_sentinel_never_reaches_browser(viewer_page)
        assert any("/api/certificates/public" in url for url in requests)
        assert not any(
            "/api/certificates/" in url and "/private/" in url for url in requests
        )
        assert not any(
            "/api/toolbelt/" in url or "/api/audit" in url or "/api/users" in url
            for url in requests
        )
    finally:
        context.close()


def _assert_next_protected_request_clears_session(page):
    requests = _request_paths(page)
    page.locator('[data-tab="audit"]').click()
    page.get_by_role("button", name="Refresh audit").click()
    expect(page.locator("#auth-gate")).to_be_visible(timeout=5000)
    expect(page.locator(".main")).to_be_hidden()
    assert sum("/api/audit?limit=100" in url for url in requests) == 1
    assert sum("/api/auth/status" in url for url in requests) == 1
    assert PRIVATE_MARKER not in page.content()


@pytest.mark.parametrize("mutation", ("roles", "disabled", "password", "expired"))
def test_next_protected_request_clears_revoked_or_expired_session(
    page, live_certmon, mutation
):
    certmon, module = _create_admin(page, live_certmon)
    created = _create_user(page, f"browser-{mutation}", ["security_admin"])
    assert created["status"] == 201
    user = created["body"]["user"]

    context, target_page = _sign_in(
        page.context.browser, certmon, f"browser-{mutation}"
    )
    try:
        expect(target_page.locator('[data-tab="audit"]')).to_be_visible()
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
        _assert_next_protected_request_clears_session(target_page)
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
