from pathlib import Path

import pytest
from playwright.sync_api import expect


@pytest.fixture
def device_filter_page(page, live_certmon):
    devices = {
        '192.168.0.1:443': {'host': '192.168.0.1', 'cn': 'TLP-1', 'self_signed': True,
                          'issuer': 'TLP-1', 'status': 'ok'},
        '192.168.0.2:443': {'host': '192.168.0.2', 'cn': 'TLP-2', 'self_signed': False,
                          'issuer': 'CertMon CA', 'status': 'ok'},
        '192.168.0.3:443': {'host': '192.168.0.3', 'cn': 'IPLP-1', 'self_signed': False,
                          'issuer': 'Other CA', 'status': 'warning'},
        '192.168.0.4:443': {'host': '192.168.0.4', 'cn': 'ShareLink-1', 'self_signed': True,
                          'issuer': 'ShareLink-1', 'status': 'warning'},
        '192.168.0.5:443': {'host': '192.168.0.5', 'status': 'error'},
    }
    for device in devices.values():
        device['port'] = 443
        device['days_remaining'] = 100
    server = live_certmon(server_mode=False)
    page.route('**/api/data', lambda route: route.fulfill(json={
        'certificates': devices, 'hosts': [], 'ranges': [],
    }))
    page.goto(server.base_url, wait_until='domcontentloaded')
    expect(page.locator('.cert-card')).to_have_count(5)
    return devices


def test_issuer_options_include_all_cas_and_group_self_signed(page, device_filter_page):
    issuer = page.locator('#device-issuer-filter')
    assert set(issuer.locator('option').all_text_contents()) == {
        'Show all', 'Self-signed', 'CertMon CA', 'Other CA', 'Unknown',
    }
    issuer.select_option('self-signed')
    expect(page.locator('.cert-card')).to_have_count(2)
    expect(page.locator('#device-filter-count')).to_have_text('2/5 shown · 0 selected')
    assert issuer.locator('option').count() == 5
    issuer.select_option('issuer:CertMon CA')
    expect(page.locator('.cert-host')).to_have_text('TLP-2')
    page.locator('#device-issuer-exclude').check()
    expect(page.locator('.cert-card')).to_have_count(4)
    expect(page.locator('.cert-grid')).not_to_contain_text('TLP-2')
    issuer.select_option('all')
    expect(page.locator('#device-issuer-exclude')).not_to_be_checked()
    expect(page.locator('#device-issuer-exclude')).to_be_disabled()
    expect(page.locator('.cert-card')).to_have_count(5)


def test_name_filter_combines_with_issuer_status_and_bulk_selection(page, device_filter_page):
    name = page.locator('#device-name-filter')
    name.fill('  tlp  ')
    expect(page.locator('.cert-card')).to_have_count(2)
    page.locator('#device-issuer-filter').select_option('self-signed')
    expect(page.locator('.cert-host')).to_have_text('TLP-1')
    page.locator('#device-select-filtered').check()
    expect(page.locator('#device-bulk-create-btn')).to_have_text('Create certificates (1)')
    page.locator('#device-issuer-filter').select_option('all')
    name.fill('ipLP')
    expect(page.locator('.cert-host')).to_have_text('IPLP-1')
    expect(page.locator('#device-filter-count')).to_have_text('1/5 shown · 0 selected')
    expect(page.locator('#device-bulk-create-btn')).to_be_disabled()
    page.locator('#device-status-filter').select_option('ok')
    expect(page.locator('.cert-card')).to_have_count(0)
    page.locator('#device-status-filter').select_option('all')
    name.fill('SHARElink')
    expect(page.locator('.cert-host')).to_have_text('ShareLink-1')
    name.fill('192.168.0.5')
    expect(page.locator('.cert-host')).to_have_text('192.168.0.5')
    name.fill('tlp')
    expect(page.locator('#device-filter-count')).to_have_text('2/5 shown · 1 selected')
    expect(page.locator('#device-name-filter')).to_be_focused()


def test_filter_selection_survives_refresh_and_options_are_safe_text(page, device_filter_page):
    page.locator('#device-issuer-filter').select_option('issuer:Other CA')
    page.locator('#device-name-filter').fill('IPLP')
    page.evaluate('loadData()')
    expect(page.locator('.cert-host')).to_have_text('IPLP-1')
    expect(page.locator('#device-issuer-filter')).to_have_value('issuer:Other CA')
    updated = dict(device_filter_page)
    updated['new:443'] = {'host': 'new', 'issuer': '<img src=x onerror=alert(1)>', 'port': 443}
    page.evaluate('certs => renderCerts(certs)', updated)
    expect(page.locator('#device-issuer-filter option').last).not_to_be_empty()
    assert '<img src=x onerror=alert(1)>' in page.locator('#device-issuer-filter option').all_text_contents()
    expect(page.locator('#device-issuer-filter img')).to_have_count(0)


@pytest.mark.parametrize('width', [1440, 800, 390])
def test_filters_fit_toolbar_and_remain_visible_when_scrolling(page, device_filter_page, width):
    page.set_viewport_size({'width': width, 'height': 900})
    page.locator('#cert-grid').evaluate("element => element.style.minHeight = '4000px'")
    page.evaluate('''() => {
        document.querySelector('.content').scrollTop = 700;
        if (window.innerWidth <= 600) window.scrollTo(0, 700);
    }''')
    page.wait_for_timeout(100)
    for selector in ['#device-issuer-filter', '#device-name-filter', '#device-bulk-create-btn']:
        expect(page.locator(selector)).to_be_in_viewport()
        bounds = page.locator(selector).bounding_box()
        assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width
    toolbar = page.locator('.device-filter-bar').bounding_box()
    tabs = page.locator('.tabs').bounding_box()
    assert abs(toolbar['y'] - tabs['y'] - tabs['height']) < 2
    directory = Path(__file__).parents[1] / '.tmp'
    directory.mkdir(exist_ok=True)
    page.screenshot(path=str(directory / f'device-filters-{width}.png'))
