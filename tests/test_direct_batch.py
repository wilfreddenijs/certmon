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


def test_direct_batch_test_automatically_pins_first_use_keys_without_transfer(tmp_path):
    service, database, artifacts, transport = make_service(tmp_path)
    run = wait_run(service, service.start_batch(mode='test', targets=targets()))
    assert run['status'] == 'complete'
    assert [d['status'] for d in run['devices']] == ['ready'] * 2
    assert len(database.get_setting(service.HOST_KEYS_KEY)) == 4
    assert all(key['approval'] == 'first_use' for key in database.get_setting(service.HOST_KEYS_KEY).values())
    assert artifacts.materializations == 0
    assert transport.sftp_writes == []


def test_direct_batch_uploads_sequentially_and_returns_isolated_snapshot(tmp_path):
    service, _, _, transport = make_service(tmp_path)
    run = wait_run(service, service.start_batch(mode='upload', targets=targets()))
    assert run['status'] == 'complete'
    assert [d['status'] for d in run['devices']] == ['verified'] * 2
    assert [identity.selector for identity, _ in transport.sis_commands] == ['10.0.0.10', '10.0.0.11']
    run['devices'].clear()
    assert len(service.get_batch(run['id'])['devices']) == 2


def test_direct_batch_never_replaces_changed_host_key(tmp_path):
    service, database, artifacts, transport = make_service(tmp_path)
    wait_run(service, service.start_batch(mode='test', targets=targets()))
    old_keys = database.get_setting(service.HOST_KEYS_KEY).copy()
    transport.key = 'SHA256:changed'
    transport.auth_attempts.clear()
    run = wait_run(service, service.start_batch(mode='upload', targets=targets()))
    assert run['status'] == 'needs_attention'
    assert all(d['status'] == 'host_key_changed' for d in run['devices'])
    assert database.get_setting(service.HOST_KEYS_KEY) == old_keys
    assert transport.auth_attempts == []
    assert artifacts.materializations == 0


def test_direct_batch_uses_each_devices_own_interface_and_endpoint(tmp_path):
    from tests.test_direct_extron import FakeTransport
    class PerInterfaceAck(FakeTransport):
        def ingest(self, identity, credentials, command, **kwargs):
            super().ingest(identity, credentials, command, **kwargs)
            return f'CertI{identity.nic}\r'.encode()
    service, _, _, transport = make_service(tmp_path, transport=PerInterfaceAck())
    service.save_device_interface('10.0.0.11', nic=2, host='10.0.1.11', port=8443)
    mixed = targets()
    mixed[1]['nic'] = 2
    run = wait_run(service, service.start_batch(mode='upload', targets=mixed))
    assert run['status'] == 'complete'
    assert [(identity.host, identity.nic) for identity, _ in transport.sis_commands] == [('10.0.0.10', 1), ('10.0.1.11', 2)]


def test_device_interface_is_persisted_and_validated(tmp_path):
    from certmon.toolbelt import DIRECT_NIC_KEY, ToolbeltBatchService
    service, database, _, _ = make_service(tmp_path)
    with pytest.raises(ValueError, match='configured'):
        service.save_device_interface('10.0.0.10', nic=2)
    assert database.get_setting(DIRECT_NIC_KEY, {}) == {}
    with pytest.raises(ValueError, match='NIC'):
        service.save_device_interface('10.0.0.10', nic=True)
    result = service.save_device_interface('10.0.0.10', nic=2, host='10.0.1.10', port=8443)
    assert result == {'nic': 2, 'lan_b': {'host': '10.0.1.10', 'port': 8443}}
    assert database.get_setting(DIRECT_NIC_KEY) == {'10.0.0.10': 2}
    prepared = ToolbeltBatchService(database, service.artifacts, service.vault).list_devices()[0]
    assert prepared['direct_nic'] == 2
    assert prepared['direct_lan_b'] == {'host': '10.0.1.10', 'port': 8443}
    service.save_device_interface('10.0.0.10', nic=1)
    assert database.get_setting(DIRECT_NIC_KEY) == {'10.0.0.10': 1}
    assert service.target_for('10.0.0.10', 2).https.host == '10.0.1.10'


def test_probe_pins_distinct_port_keys_and_detects_changes_before_auth(tmp_path):
    from tests.test_direct_extron import FakeTransport
    class DifferentKeys(FakeTransport):
        def host_key_fingerprint(self, identity):
            return ('ssh-ed25519', 'SHA256:' + identity.connection)
    service, database, _, transport = make_service(tmp_path, transport=DifferentKeys())
    assert service.probe_one(selector='10.0.0.10', auto_first_use=True)['status'] == 'ready'
    assert {value['fingerprint'] for value in database.get_setting(service.HOST_KEYS_KEY).values()} == {'SHA256:sftp', 'SHA256:sis'}
    assert transport.expected_fingerprints == ['SHA256:sftp', 'SHA256:sis']
    transport.host_key_fingerprint = lambda identity: ('ssh-ed25519', 'SHA256:changed')
    transport.auth_attempts.clear()
    assert service.probe_one(selector='10.0.0.10', auto_first_use=True)['status'] == 'host_key_changed'
    assert transport.auth_attempts == []


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
        {'selector': '10.0.0.10', 'certificate_id': 'server-cert', 'extron_ready': True, 'direct_nic': 2}])
    monkeypatch.setattr(module, 'authorize', lambda permission: None)
    client = module.app.test_client()
    body = {'selectors': ['10.0.0.10'], 'mode': 'upload'}
    assert client.post('/api/direct-extron/batches', json=body).status_code == 202
    assert calls == [{'mode': 'upload', 'targets': [{'selector': '10.0.0.10', 'certificate_id': 'server-cert', 'nic': 2}]}]
    for invalid in (dict(body, certificate_id='injected'), dict(body, selectors=['unknown']),
                    dict(body, selectors=['10.0.0.10'] * 2), dict(body, nic=True), []):
        assert client.post('/api/direct-extron/batches', json=invalid).status_code == 400
    assert len(calls) == 1


@pytest.mark.parametrize('endpoint,method', [('batches', 'post'), ('batches/run', 'get'), ('batches/run/stop', 'post'), ('devices/10.0.0.10/interface', 'patch')])
def test_direct_batch_requires_auth_and_mutations_require_csrf(tmp_data_dir, monkeypatch, endpoint, method):
    from tests.test_auth_api import load_app
    module = load_app(tmp_data_dir, monkeypatch)
    client = module.app.test_client()
    assert getattr(client, method)(f'/api/direct-extron/{endpoint}').status_code == 401
    client.post('/api/auth/setup-first-admin', json={
        'username': 'admin', 'password': 'correct horse', 'password_confirmation': 'correct horse'})
    if method in ('post', 'patch'):
        assert getattr(client, method)(f'/api/direct-extron/{endpoint}', json={}).status_code == 403
