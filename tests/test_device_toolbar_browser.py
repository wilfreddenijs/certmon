from pathlib import Path

import pytest
from playwright.sync_api import expect


@pytest.mark.parametrize('width', [1440, 800, 390])
def test_device_toolbar_stays_below_navigation_when_scrolling(page, live_certmon, width):
    page.set_viewport_size({'width': width, 'height': 900})
    server = live_certmon(server_mode=False)
    certificates = {
        f'192.168.0.{i}:443': {'host': f'192.168.0.{i}', 'port': 443,
                              'status': 'ok', 'days_remaining': 100}
        for i in range(1, 61)
    }
    page.route('**/api/data', lambda route: route.fulfill(json={
        'certificates': certificates, 'hosts': [], 'ranges': [],
    }))
    page.goto(server.base_url, wait_until='domcontentloaded')
    expect(page.locator('#device-select-filtered')).to_be_visible()
    expect(page.locator('.cert-card')).to_have_count(60)
    page.evaluate('''() => {
        document.querySelector('.content').scrollTop = 700;
        if (window.innerWidth <= 600) window.scrollTo(0, 700);
    }''')
    page.wait_for_timeout(100)
    geometry = page.evaluate('''() => {
        const tabs = document.querySelector('.tabs').getBoundingClientRect();
        const bar = document.querySelector('.device-filter-bar').getBoundingClientRect();
        return {tabsBottom: tabs.bottom, barTop: bar.top, barBottom: bar.bottom,
                background: getComputedStyle(document.querySelector('.device-filter-bar')).backgroundColor};
    }''')
    assert abs(geometry['barTop'] - geometry['tabsBottom']) < 2
    assert geometry['barBottom'] < 900
    assert geometry['background'] != 'rgba(0, 0, 0, 0)'
    expect(page.locator('#device-bulk-create-btn')).to_be_in_viewport()
    page.locator('#device-select-filtered').click()
    expect(page.locator('#device-bulk-create-btn')).to_have_text('Create certificates (60)')
    expect(page.locator('#device-bulk-create-btn')).to_be_enabled()
    directory = Path(__file__).parents[1] / '.tmp'
    directory.mkdir(exist_ok=True)
    page.screenshot(path=str(directory / f'device-toolbar-scrolled-{width}.png'))
    page.evaluate("switchTab('upload')")
    expect(page.locator('.device-filter-bar')).not_to_be_visible()
