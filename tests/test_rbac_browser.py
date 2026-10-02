from playwright.sync_api import expect


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
