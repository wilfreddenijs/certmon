from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.test_audit_export_cleanup import seed_events


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_audit_export_and_confirmed_cleanup(page, live_certmon, width, height):
    server = live_certmon(server_mode=False)
    import app

    seed_events(app)
    page.set_viewport_size({"width": width, "height": height})
    page.goto(server.base_url)
    page.locator('[data-tab="audit"]').click()
    page.get_by_role("button", name="Refresh audit").click()
    expect(page.locator("#audit-list")).to_contain_text("10.0.0.1")
    with page.expect_download() as download:
        page.get_by_role("button", name="Export audit Excel").click()
    assert download.value.suggested_filename.endswith(".xlsx")
    expect(page.locator("#audit-action-result")).to_have_text("Audit Excel exported.")
    page.locator("#audit-delete-before").fill("2026-01-02")
    screenshot = Path(".tmp/audit-ui") / f"audit-{width}.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(screenshot), full_page=True)
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.get_by_role("button", name="Delete old events").click()
    assert len(app.database.list_audit_events()) == 3
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Delete old events").click()
    expect(page.locator("#audit-action-result")).to_contain_text("1 audit events deleted")
    expect(page.locator("#audit-list")).to_contain_text("audit_history_deleted")
    expect(page.locator("#audit-list")).not_to_contain_text("10.0.0.1")
    expect(page.locator("#audit-list")).to_contain_text("10.0.0.2")
