from importlib import import_module

from playwright.sync_api import expect


def _create_user(page, username, roles):
    return page.evaluate(
        """async ({username, roles}) => {
            const status = await (await fetch('/api/auth/status')).json();
            const response = await fetch('/api/users', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    [status.csrf_header]: status.csrf_token,
                },
                body: JSON.stringify({username, password: 'correct horse', roles}),
            });
            return {status: response.status, body: await response.json()};
        }""",
        {"username": username, "roles": roles},
    )


def _replace_roles(page, user_id, roles):
    return page.evaluate(
        """async ({userId, roles}) => {
            const status = await (await fetch('/api/auth/status')).json();
            const response = await fetch(`/api/users/${userId}`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    [status.csrf_header]: status.csrf_token,
                },
                body: JSON.stringify({roles}),
            });
            return response.status;
        }""",
        {"userId": user_id, "roles": roles},
    )


def _sign_in_as_viewer(page, live_certmon):
    certmon = live_certmon(server_mode=True)
    page.goto(certmon.base_url)
    page.locator("#auth-username").fill("browser-admin")
    page.locator("#auth-password").fill("correct horse")
    page.locator("#auth-password-confirmation").fill("correct horse")
    page.locator("#auth-submit").click()
    expect(page.locator(".main")).to_be_visible()
    assert _create_user(page, "browser-viewer", ["viewer"])["status"] == 201
    module = import_module("app")
    module.artifact_store.create_certificate_set(
        "browser-public-cert",
        {"certificate.pem": b"browser public certificate"},
        {},
        {},
    )
    module.database.put_certificate(
        "browser-public-cert",
        {
            "kind": "leaf",
            "identifiers": ["browser.example.test"],
            "profile": "generic-rsa",
        },
    )

    viewer = page.context.browser.new_context()
    viewer_page = viewer.new_page()
    viewer_page.goto(certmon.base_url)
    viewer_page.locator("#auth-username").fill("browser-viewer")
    viewer_page.locator("#auth-password").fill("correct horse")
    viewer_page.locator("#auth-submit").click()
    expect(viewer_page.locator(".main")).to_be_visible()
    return viewer, viewer_page


def test_browser_harness_executes_certmon_javascript(page, live_certmon):
    certmon = live_certmon(server_mode=True)

    page.goto(certmon.base_url)

    expect(page.locator("#auth-gate")).to_be_visible()
    expect(page.locator("#auth-title")).to_have_text("Create first admin")
    page.locator("#auth-username").fill("browser-admin")
    page.locator("#auth-password").fill("correct horse")
    page.locator("#auth-password-confirmation").fill("correct horse")
    page.locator("#auth-submit").click()

    expect(page.locator(".main")).to_be_visible()
    expect(page.locator("#auth-gate")).to_be_hidden()
    expect(page.locator("#auth-user-label")).to_contain_text("browser-admin")


def test_desktop_mode_renders_main_ui_without_an_authentication_gate(page, live_certmon):
    certmon = live_certmon(server_mode=False)

    page.goto(certmon.base_url)

    expect(page.locator(".main")).to_be_visible()
    expect(page.locator("#auth-gate")).to_be_hidden()


def test_viewer_hides_restricted_controls_and_uses_only_public_catalog(page, live_certmon):
    viewer, viewer_page = _sign_in_as_viewer(page, live_certmon)
    requests = []
    viewer_page.on("request", lambda request: requests.append(request.url))
    try:
        viewer_page.reload()
        expect(viewer_page.locator(".main")).to_be_visible()
        expect(viewer_page.locator('[data-tab="audit"]')).to_be_hidden()
        expect(viewer_page.locator("#administration-tab")).to_be_hidden()
        expect(viewer_page.locator("#toolbelt-batch")).to_be_hidden()
        expect(viewer_page.locator("#device-bulk-create-btn")).to_be_hidden()
        viewer_page.locator('[data-tab="upload"]').click()
        expect(viewer_page.locator("#manual-upload-fallback")).to_be_visible()
        expect(viewer_page.locator("#push-private-artifacts")).to_be_hidden()
        assert any("/api/certificates/public" in url for url in requests)
        assert not any("/api/certificates" in url and "/public" not in url for url in requests)
        assert not any("/api/toolbelt/" in url or "/api/audit" in url or "/api/users" in url for url in requests)
    finally:
        viewer.close()


def test_revoked_security_admin_audit_next_401_clears_to_sign_in(page, live_certmon):
    certmon = live_certmon(server_mode=True)
    page.goto(certmon.base_url)
    page.locator("#auth-username").fill("browser-admin")
    page.locator("#auth-password").fill("correct horse")
    page.locator("#auth-password-confirmation").fill("correct horse")
    page.locator("#auth-submit").click()
    expect(page.locator(".main")).to_be_visible()
    created = _create_user(page, "browser-security", ["security_admin"])
    assert created["status"] == 201

    security = page.context.browser.new_context()
    security_page = security.new_page()
    security_page.goto(certmon.base_url)
    security_page.locator("#auth-username").fill("browser-security")
    security_page.locator("#auth-password").fill("correct horse")
    security_page.locator("#auth-submit").click()
    expect(security_page.locator('[data-tab="audit"]')).to_be_visible()
    assert _replace_roles(page, created["body"]["user"]["id"], ["viewer"]) == 200

    requests = []
    security_page.on("request", lambda request: requests.append(request.url))
    try:
        security_page.locator('[data-tab="audit"]').click()
        security_page.get_by_role("button", name="Refresh audit").click()
        expect(security_page.locator("#auth-gate")).to_be_visible(timeout=5000)
        expect(security_page.locator(".main")).to_be_hidden()
        assert sum("/api/audit?limit=100" in url for url in requests) == 1
    finally:
        security.close()
