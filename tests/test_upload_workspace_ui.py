from pathlib import Path
import pytest

from playwright.sync_api import expect


def prepare_upload_workspace(page, live_certmon, count=2):
    certmon = live_certmon(server_mode=False)
    certificates = [{
        "certificate_id": f"cert-{i}", "identifiers": [f"device-{i}.example.com", f"192.168.0.{i}"],
        "profile": "extron-rsa", "public_artifacts": ["certificate.pem", "chain.pem"],
        "download_prefix": f"device-{i}-extron-cert-{i}",
        "download_names": {name: f"device-{i}-extron-cert-{i}-{name}" for name in ["certificate.pem", "chain.pem"]},
    } for i in range(1, count + 1)]
    devices = [{
        "selector": f"192.168.0.{i}", "certificate_id": f"cert-{i}", "label": f"Device {i}",
        "extron_ready": True, "selected": True, "credentials_saved": True,
    } for i in range(1, count + 1)]
    page.route('**/api/certificates/public', lambda route: route.fulfill(json=certificates))
    page.route('**/api/toolbelt/devices', lambda route: route.fulfill(json={"devices": devices}))
    page.route('**/api/toolbelt/reset-upload-tab', lambda route: route.fulfill(json={"devices": devices}))
    page.goto(certmon.base_url, wait_until='domcontentloaded')
    page.wait_for_function("typeof switchTab === 'function'")
    page.evaluate("async () => { switchTab('upload'); await loadAvailableCertificates(); await loadToolbeltDevices(false); }")
    expect(page.locator('.upload-device-row')).to_have_count(count)
    return certificates, devices


@pytest.mark.parametrize('replace', [False, True])
def test_create_certificate_conflict_can_cancel_or_replace_one_upload_row(page, live_certmon, replace):
    certificates, devices = prepare_upload_workspace(page, live_certmon, count=1)
    if not replace:
        page.set_viewport_size({'width': 390, 'height': 844})
    requests = []

    def issue(route):
        body = route.request.post_data_json
        requests.append(body)
        if not body.get('replace_certificate_id'):
            route.fulfill(status=409, json={
                'code': 'upload_certificate_conflict', 'error': 'Existing upload certificate',
                'existing': {key: devices[0][key] for key in ['selector', 'certificate_id', 'label']},
            })
            return
        assert body['replace_certificate_id'] == 'cert-1'
        certificates.append({**certificates[0], 'certificate_id': 'cert-new'})
        devices[0]['certificate_id'] = 'cert-new'
        route.fulfill(json={'ok': True, 'certificate_id': 'cert-new'})

    page.route('**/api/ca/issue', issue)
    page.evaluate("openDeviceLocalCAModal('192.168.0.1', 'renamed.example.com')")
    page.locator('#device-ca-create').click()
    dialog = page.get_by_role('dialog', name='Replace certificate?')
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text('192.168.0.1')
    expect(dialog).to_contain_text('cert-1')
    shots = Path('.tmp/replacement-ui')
    shots.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(shots / ('desktop.png' if replace else 'mobile.png')))
    if replace:
        dialog.get_by_role('button', name='Replace certificate', exact=True).click()
        expect(page.locator('#device-ca-result')).to_contain_text('cert-new')
        expect(page.locator('.upload-device-row')).to_have_count(1)
        expect(page.locator('.upload-device-row')).to_contain_text('cert-new')
        assert len(requests) == 2
    else:
        dialog.get_by_role('button', name='Cancel', exact=True).click()
        expect(page.locator('#device-ca-result')).to_contain_text('unchanged')
        expect(page.locator('.upload-device-row')).to_have_count(1)
        assert devices[0]['certificate_id'] == 'cert-1'
        assert len(requests) == 1


def test_bulk_create_asks_before_replacing_existing_upload_certificate(page, live_certmon):
    certificates, devices = prepare_upload_workspace(page, live_certmon, count=1)
    requests = []
    scanned = {'host': '192.168.0.1', 'port': 443, 'cn': 'renamed.example.com', 'status': 'ok', 'days_remaining': 100}
    page.route('**/api/ca/issue-bulk', lambda route: route.fulfill(json={
        'created': [], 'failed': [{'key': '192.168.0.1|443', 'name': scanned['cn'],
                                 'code': 'upload_certificate_conflict', 'error': 'Existing certificate',
                                 'existing': {key: devices[0][key] for key in ['selector', 'certificate_id', 'label']}}],
    }))

    def issue(route):
        requests.append(route.request.post_data_json)
        devices[0]['certificate_id'] = 'cert-new'
        certificates.append({**certificates[0], 'certificate_id': 'cert-new'})
        route.fulfill(json={'ok': True, 'certificate_id': 'cert-new'})

    page.route('**/api/ca/issue', issue)
    page.on('dialog', lambda dialog: dialog.accept())
    page.evaluate("device => { currentCertificates = [device]; selectedDeviceKeys.add(deviceKey(device)); bulkCreateSelectedDeviceCertificates(); }", scanned)
    dialog = page.get_by_role('dialog', name='Replace certificate?')
    expect(dialog).to_be_visible()
    assert requests == []
    dialog.get_by_role('button', name='Replace certificate', exact=True).click()
    expect(page.locator('.upload-device-row')).to_contain_text('cert-new')
    expect(page.locator('.upload-device-row')).to_have_count(1)
    assert requests[0]['replace_certificate_id'] == 'cert-1'


def test_shared_device_list_opens_direct_and_limits_toolbelt_to_chosen_devices(page, live_certmon):
    prepare_upload_workspace(page, live_certmon)
    mutations = []
    page.on('request', lambda request: mutations.append(request.url) if '/api/direct-extron/' in request.url else None)
    expect(page.locator('#direct-extron-upload')).not_to_be_visible()
    page.locator('.upload-device-row').first.get_by_role('button', name='Open upload', exact=True).click()
    expect(page.locator('#direct-extron-upload')).to_be_visible()
    expect(page.locator('#direct-extron-current-device')).to_have_text('Device 1 (192.168.0.1)')
    page.locator('#direct-extron-upload').get_by_role('button', name='Close', exact=True).click()
    page.get_by_label('Upload method for Device 2', exact=True).select_option('toolbelt')
    expect(page.locator('#toolbelt-selected-count')).to_have_text('1 selected')
    runs = []
    page.route('**/api/toolbelt/dry-run', lambda route: (
        runs.append(route.request.post_data_json),
        route.fulfill(json={"run": {"id": "run-1"}}),
    ))
    page.route('**/api/toolbelt/runs/run-1', lambda route: route.fulfill(json={"status": "completed", "mode": "dry-run", "devices": {}}))
    page.locator('#toolbelt-test-btn').click()
    expect(page.locator('#toolbelt-run-status')).to_contain_text('completed')
    assert runs == [{"selectors": ["192.168.0.2"]}]
    assert mutations == []


def test_download_selection_updates_identity_filenames_and_links_immediately(page, live_certmon):
    prepare_upload_workspace(page, live_certmon)
    page.locator('#manual-upload-fallback summary').click()
    select = page.locator('#push-target-select')
    select.select_option('cert-1')
    expect(page.locator('#push-result-title')).to_contain_text('device-1.example.com')
    expect(page.locator('#push-log')).to_have_text('Certificate: cert-1')
    first = page.locator('#push-public-artifact-links a').first
    expect(first).to_have_attribute('download', 'device-1-extron-cert-1-certificate.pem')
    expect(first).to_contain_text('device-1-extron-cert-1-certificate.pem')
    expect(page.locator('#push-private-artifact-links a')).to_have_attribute('download', 'device-1-extron-cert-1-extron-combined.pem')
    select.select_option('cert-2')
    expect(page.locator('#push-log')).to_have_text('Certificate: cert-2')
    expect(first).to_have_attribute('href', '/api/certificates/cert-2/public/certificate.pem')
    expect(first).to_have_attribute('download', 'device-2-extron-cert-2-certificate.pem')
    expect(page.locator('#push-result')).not_to_contain_text('device-1')
    expect(page.locator('#push-private-artifact-links a')).to_have_attribute('href', '/api/certificates/cert-2/private/combined.pem')
    page.locator('#push-result').scroll_into_view_if_needed()
    page.screenshot(path=str(Path(__file__).parents[1] / '.tmp' / 'upload-workspace-downloads.png'))
    select.select_option('')
    expect(page.locator('#push-result')).not_to_be_visible()
    expect(page.locator('#push-public-artifact-links a')).to_have_count(0)
    expect(page.locator('#push-private-artifact-links a')).to_have_count(0)


def test_upload_workspace_navigation_and_responsive_layout(page, live_certmon):
    page.set_viewport_size({"width": 1440, "height": 900})
    prepare_upload_workspace(page, live_certmon, count=18)
    directory = Path(__file__).parents[1] / '.tmp'
    page.screenshot(path=str(directory / 'upload-workspace-desktop.png'))
    page.locator('.content').evaluate('(element) => element.scrollTop = 600')
    geometry = page.evaluate("""() => {
      const tabs = document.querySelector('.tabs');
      const content = document.querySelector('.content');
      return {top: tabs.getBoundingClientRect().top, contentTop: content.getBoundingClientRect().top,
        background: getComputedStyle(tabs).backgroundColor, height: tabs.getBoundingClientRect().height};
    }""")
    assert abs(geometry['top'] - geometry['contentTop']) < 2
    assert geometry['height'] >= 58
    assert geometry['background'] == 'rgb(10, 13, 18)'
    page.screenshot(path=str(directory / 'upload-workspace-scrolled.png'))
    page.locator('.content').evaluate('(element) => element.scrollTop = 0')
    page.locator('.upload-device-row').first.get_by_role('button', name='Open upload', exact=True).click()
    page.screenshot(path=str(directory / 'upload-workspace-direct.png'))
    page.locator('#direct-extron-upload').get_by_role('button', name='Close', exact=True).click()
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(directory / 'upload-workspace-mobile.png'))
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    bounds = page.locator('.upload-device-row').first.bounding_box()
    assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 390
    page.locator('.upload-device-row').first.get_by_role('button', name='Open upload', exact=True).click()
    dialog = page.locator('#direct-extron-upload').bounding_box()
    assert dialog['x'] >= 0 and dialog['x'] + dialog['width'] <= 390
    page.screenshot(path=str(directory / 'upload-workspace-direct-mobile.png'))


def test_credentials_buttons_open_native_dialog_and_clear_password(page, live_certmon):
    prepare_upload_workspace(page, live_certmon)
    saved = []
    page.route('**/api/toolbelt/default-credentials', lambda route: (
        saved.append(route.request.post_data_json), route.fulfill(json={"ok": True})))
    page.get_by_role('button', name='Shared Device Credentials', exact=True).click()
    dialog = page.locator('#device-credentials-dialog')
    expect(dialog).to_be_visible()
    expect(page.locator('#device-credentials-title')).to_have_text('Shared device credentials')
    page.locator('#device-credentials-password').fill('test-password')
    dialog.get_by_role('button', name='Save credentials').click()
    expect(dialog).not_to_be_visible()
    expect(page.locator('#device-credentials-password')).to_have_value('')
    assert saved == [{"username": "admin", "password": "test-password"}]
    page.locator('.upload-device-row').first.get_by_role('button', name='Device Credentials', exact=True).click()
    expect(dialog).to_be_visible()
    expect(page.locator('#device-credentials-target')).to_have_text('192.168.0.1')
    page.locator('#device-credentials-password').fill('cancelled-secret')
    dialog.get_by_role('button', name='Cancel').click()
    expect(page.locator('#device-credentials-password')).to_have_value('')
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator('.upload-device-row').first.get_by_role('button', name='Device Credentials', exact=True).click()
    page.screenshot(path=str(Path(__file__).parents[1] / '.tmp' / 'upload-credentials-mobile.png'))
    bounds = dialog.bounding_box()
    assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 390


def test_direct_batch_selection_test_confirmation_and_results(page, live_certmon):
    prepare_upload_workspace(page, live_certmon)
    calls = []
    def start(route):
        body = route.request.post_data_json
        calls.append(body)
        route.fulfill(json={"id": body['mode']})
    def status(route):
        mode = route.request.url.rsplit('/', 1)[-1]
        route.fulfill(json={"id": mode, "mode": mode, "status": "complete", "devices": [
            {"selector": f"192.168.0.{i}", "certificate_id": f"cert-{i}", "nic": 1,
             "status": "ready" if mode == 'test' else 'verified'} for i in (1, 2)]})
    page.route('**/api/direct-extron/batches', start)
    page.route('**/api/direct-extron/batches/*', status)
    expect(page.locator('#direct-batch-count')).to_have_text('2 selected')
    expect(page.locator('#direct-batch-upload')).to_be_disabled()
    page.locator('#direct-batch-test').click()
    expect(page.locator('#direct-batch-status')).to_have_text('All selected connections are ready.')
    page.locator('#direct-batch-upload').click()
    expect(page.locator('#direct-batch-confirm')).to_be_visible()
    assert len(calls) == 1
    page.get_by_role('button', name='Start batch upload', exact=True).click()
    expect(page.locator('#direct-batch-status')).to_have_text('2 certificates uploaded and verified.')
    assert calls == [{"mode": mode, "selectors": ['192.168.0.1', '192.168.0.2']} for mode in ('test', 'upload')]
    expect(page.locator('.upload-device-row').first).to_contain_text('Certificate uploaded and verified')
    page.screenshot(path=str(Path(__file__).parents[1] / '.tmp' / 'upload-direct-batch-desktop.png'))
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator('#direct-batch-status').scroll_into_view_if_needed()
    page.screenshot(path=str(Path(__file__).parents[1] / '.tmp' / 'upload-direct-batch-mobile.png'))
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')


def test_interface_choice_is_per_device_and_invalidates_batch_test(page, live_certmon):
    prepare_upload_workspace(page, live_certmon)
    saved = []
    def save_interface(route):
        body = route.request.post_data_json
        saved.append((route.request.url.rsplit('/devices/', 1)[1], body))
        route.fulfill(json={'nic': body['nic'], 'lan_b': {'host': body['host'], 'port': body['port']}})
    page.route('**/api/direct-extron/devices/*/interface', save_interface)
    page.evaluate('directBatchTestSignature = directBatchSignature(); renderDirectBatchControls()')
    expect(page.locator('#direct-batch-upload')).to_be_enabled()
    expect(page.locator('#direct-batch-nic')).to_have_count(0)
    page.get_by_label('Network interface for Device 2', exact=True).select_option('2')
    dialog = page.locator('#direct-interface-dialog')
    expect(dialog).to_be_visible()
    page.locator('#direct-interface-host').fill('192.168.1.2')
    page.locator('#direct-interface-port').fill('8443')
    dialog.get_by_role('button', name='Save', exact=True).click()
    expect(dialog).not_to_be_visible()
    expect(page.get_by_label('Network interface for Device 1', exact=True)).to_have_value('1')
    expect(page.get_by_label('Network interface for Device 2', exact=True)).to_have_value('2')
    expect(page.locator('#direct-batch-upload')).to_be_disabled()
    assert saved == [('192.168.0.2/interface', {'nic': 2, 'host': '192.168.1.2', 'port': 8443})]
    page.locator('.upload-device-row').nth(1).get_by_role('button', name='Open upload', exact=True).click()
    expect(page.locator('#direct-extron-interface')).to_have_text('LAN B (192.168.1.2:8443)')
    expect(page.locator('#direct-extron-nic')).to_have_value('2')
    expect(page.get_by_role('button', name='Save LAN B endpoint', exact=True)).to_have_count(0)
    page.locator('#direct-extron-upload').get_by_role('button', name='Close', exact=True).click()
    page.set_viewport_size({'width': 390, 'height': 844})
    page.get_by_label('Network interface for Device 2', exact=True).scroll_into_view_if_needed()
    page.screenshot(path=str(Path(__file__).parents[1] / '.tmp' / 'upload-per-device-interface-mobile.png'))
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
