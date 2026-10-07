import time
from threading import Event
from types import SimpleNamespace

import pytest

from tests.test_direct_extron import make_service, approve


def wait_run(service, run):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = service.get_batch(run['id'])
        if result['status'] != 'running':
            return result
        time.sleep(.01)
    pytest.fail('Direct batch did not finish')


def targets():
    return [{'selector': f'10.0.0.{i}', 'certificate_id': 'cert-1', 'nic': 1} for i in (10, 11)]


def test_direct_batch_requires_explicit_trust_before_any_transfer(tmp_path):
    service, _, artifacts, transport = make_service(tmp_path)
    run = wait_run(service, service.start_batch(mode='upload', targets=targets()))
    assert run['status'] == 'needs_attention'
    assert [d['status'] for d in run['devices']] == ['approval_required'] * 2
    assert artifacts.materializations == 0
    assert transport.sftp_writes == []


def test_direct_batch_uploads_sequentially_and_returns_isolated_snapshot(tmp_path):
    service, _, _, transport = make_service(tmp_path)
    for target in targets():
        approve(service, target['selector'])
    run = wait_run(service, service.start_batch(mode='upload', targets=targets()))
    assert run['status'] == 'complete'
    assert [d['status'] for d in run['devices']] == ['verified'] * 2
    assert [identity.selector for identity, _ in transport.sis_commands] == ['10.0.0.10', '10.0.0.11']
    run['devices'].clear()
    assert len(service.get_batch(run['id'])['devices']) == 2


def test_direct_batch_stop_finishes_current_device_and_blocks_other_operations(tmp_path):
    service, _, _, transport = make_service(tmp_path)
    for target in targets():
        approve(service, target['selector'])
    entered, release = Event(), Event()
    activate = service._activate_one
    def blocked(**kwargs):
        entered.set()
        assert release.wait(5)
        return activate(**kwargs)
    service._activate_one = blocked
    run = service.start_batch(mode='upload', targets=targets())
    assert entered.wait(5)
    try:
        with pytest.raises(ValueError, match='already running'):
            service.activate_one(**targets()[0])
        service.stop_batch(run['id'])
    finally:
        release.set()
    result = wait_run(service, run)
    assert result['status'] == 'stopped'
    assert len(transport.sis_commands) == 1


def test_direct_batch_never_retries_ambiguous_import(tmp_path):
    service, _, _, transport = make_service(tmp_path)
    for target in targets():
        approve(service, target['selector'])
    transport.ack = b''
    run = wait_run(service, service.start_batch(mode='upload', targets=targets()))
    assert run['status'] == 'needs_attention'
    assert len(transport.sis_commands) == 1
    rerun = wait_run(service, service.start_batch(mode='upload', targets=targets()))
    assert rerun['status'] == 'needs_attention'
    assert len(transport.sis_commands) == 1


def test_direct_batch_api_resolves_certificates_server_side(tmp_data_dir, monkeypatch):
    import importlib
    import app
    module = importlib.reload(app)
    calls = []
    module.artifact_store = object()
    module.vault = object()
    module.direct_extron_service = SimpleNamespace(start_batch=lambda **kw: (calls.append(kw) or {'id': 'run'}))
    module.toolbelt_service = SimpleNamespace(list_devices=lambda: [
        {'selector': '10.0.0.10', 'certificate_id': 'server-cert', 'extron_ready': True}])
    monkeypatch.setattr(module, 'authorize', lambda permission: None)
    client = module.app.test_client()
    body = {'selectors': ['10.0.0.10'], 'mode': 'upload', 'nic': 1}
    assert client.post('/api/direct-extron/batches', json=body).status_code == 202
    assert calls == [{'mode': 'upload', 'targets': [{'selector': '10.0.0.10', 'certificate_id': 'server-cert', 'nic': 1}]}]
    for invalid in (dict(body, certificate_id='injected'), dict(body, selectors=['unknown']),
                    dict(body, selectors=['10.0.0.10'] * 2), dict(body, nic=True), []):
        assert client.post('/api/direct-extron/batches', json=invalid).status_code == 400
    assert len(calls) == 1


@pytest.mark.parametrize('endpoint,method', [('batches', 'post'), ('batches/run', 'get'), ('batches/run/stop', 'post')])
def test_direct_batch_requires_auth_and_mutations_require_csrf(tmp_data_dir, monkeypatch, endpoint, method):
    from tests.test_auth_api import load_app
    module = load_app(tmp_data_dir, monkeypatch)
    client = module.app.test_client()
    assert getattr(client, method)(f'/api/direct-extron/{endpoint}').status_code == 401
    client.post('/api/auth/setup-first-admin', json={
        'username': 'admin', 'password': 'correct horse', 'password_confirmation': 'correct horse'})
    if method == 'post':
        assert client.post(f'/api/direct-extron/{endpoint}', json={}).status_code == 403
