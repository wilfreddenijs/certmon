from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.test_stored_certificate_delete import seed_certificate


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844)])
def test_download_selection_shows_dates_and_deletes_only_selected_certificate(page, live_certmon, width, height):
    server = live_certmon(server_mode=False)
    import app

    seed_certificate(app, certificate_id="old-leaf")
    seed_certificate(app, certificate_id="new-leaf")
    with app.database.transaction() as connection:
        connection.execute("UPDATE certificates SET created_at=? WHERE id=?", ("2026-01-01T10:00:00+00:00", "old-leaf"))
        connection.execute("UPDATE certificates SET created_at=? WHERE id=?", ("2026-01-02T11:00:00+00:00", "new-leaf"))
    page.set_viewport_size({"width": width, "height": height})
    page.goto(server.base_url)
    page.locator('[data-tab="upload"]').click()
    page.locator("#manual-upload-fallback").evaluate("element => element.open = true")
    select = page.locator("#push-target-select")
    expect(select.locator("option")).to_have_count(3)
    assert "new-leaf" in select.locator("option").nth(1).inner_text()
    assert "Created 2026-01-02 11:00:00 UTC" in select.locator("option").nth(1).inner_text()
    select.select_option("old-leaf")
    expect(page.locator("#push-log")).to_contain_text("Created 2026-01-01 10:00:00 UTC")
    select.select_option("new-leaf")
    button = page.get_by_role("button", name="Delete certificate from server", exact=True)
    expect(button).to_be_visible()
    button.scroll_into_view_if_needed()
    screenshot = Path(".tmp/certificate-delete-ui") / f"downloads-{width}.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(screenshot), full_page=True)
    page.once("dialog", lambda dialog: dialog.dismiss())
    button.click()
    assert app.database.get_certificate("new-leaf") is not None
    page.once("dialog", lambda dialog: dialog.accept())
    button.click()
    expect(page.locator("#stored-certificate-delete-result")).to_contain_text("new-leaf deleted from the server")
    expect(select.locator("option")).to_have_count(2)
    expect(page.locator("#push-result")).to_be_hidden()
    assert app.database.get_certificate("new-leaf") is None
    assert app.artifact_store.has_certificate("old-leaf")
