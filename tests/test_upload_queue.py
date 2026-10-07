import pytest

from certmon.upload_queue import AUTO_REMOVE_KEY, COMPLETED_KEY, UploadQueueService
from certmon.toolbelt import ToolbeltBatchService
from tests.test_toolbelt_service import FakeDatabase, FakeArtifacts, FakeVault


def outcomes():
    return [
        {'selector': '192.168.0.10', 'certificate_id': 'cert-1', 'ok': True, 'status': 'verified'},
        {'selector': '192.168.0.11', 'certificate_id': 'cert-2', 'ok': False, 'status': 'authentication_failed'},
    ]


def test_queue_option_defaults_off_and_audits_both_results():
    database = FakeDatabase()
    queue = UploadQueueService(database)
    assert not queue.auto_remove()
    queue.finish(method='direct', run_id='run-1', outcomes=outcomes())
    assert queue.completed() == set()
    assert [(event['target'], event['success']) for event in database.audit_events] == [
        ('192.168.0.10', True), ('192.168.0.11', False)]


def test_success_cleanup_is_persistent_idempotent_and_keeps_certificates(tmp_path):
    database = FakeDatabase()
    database.certificates.insert(0, {**database.certificates[0], 'id': 'older-cert'})
    database.certificates.append({**database.certificates[-1], 'id': 'cert-2', 'identifiers': ['192.168.0.11']})
    queue = UploadQueueService(database)
    service = ToolbeltBatchService(database, FakeArtifacts(tmp_path), FakeVault())
    queue.finish(method='toolbelt', run_id='run-1', outcomes=outcomes(), remove_successful=True)
    queue.finish(method='toolbelt', run_id='run-1', outcomes=outcomes(), remove_successful=True)
    assert queue.completed() == {'cert-1'}
    assert len(database.audit_events) == 2
    assert len(database.certificates) == 3
    assert [row['selector'] for row in service.list_devices()] == ['192.168.0.11']
    recreated = ToolbeltBatchService(database, FakeArtifacts(tmp_path), FakeVault())
    assert [row['selector'] for row in recreated.list_devices()] == ['192.168.0.11']
    database.certificates.append({**database.certificates[1], 'id': 'new-cert'})
    assert {row['certificate_id'] for row in recreated.list_devices()} == {'cert-2', 'new-cert'}


def test_failed_audit_never_hides_successes(monkeypatch):
    database = FakeDatabase()
    monkeypatch.setattr(database, 'record_audit_event', lambda **kwargs: (_ for _ in ()).throw(OSError('disk full')))
    queue = UploadQueueService(database)
    with pytest.raises(OSError):
        queue.finish(method='direct', run_id='run-1', outcomes=outcomes(), remove_successful=True)
    assert database.get_setting(COMPLETED_KEY, []) == []


def test_upload_preference_requires_boolean_and_persists(tmp_data_dir):
    from tests.test_ca_api import load_app
    module = load_app(tmp_data_dir)
    client = module.app.test_client()
    assert client.get('/api/upload/preferences').get_json() == {'auto_remove_successful': False}
    assert client.post('/api/upload/preferences', json={'auto_remove_successful': 'true'}).status_code == 400
    assert client.post('/api/upload/preferences', json={'auto_remove_successful': True}).status_code == 200
    assert module.database.get_setting(AUTO_REMOVE_KEY) is True
    assert client.get('/api/upload/preferences').get_json() == {'auto_remove_successful': True}


def test_audit_api_keeps_ip_results_after_upload_rows_are_removed(tmp_data_dir):
    from tests.test_ca_api import load_app
    module = load_app(tmp_data_dir)
    for index, ip in [(1, 10), (2, 11)]:
        module.database.put_certificate(f'cert-{index}', {
            'kind': 'leaf', 'issuer_type': 'local_ca', 'profile': 'extron-rsa', 'identifiers': [f'192.168.0.{ip}']})
    UploadQueueService(module.database).finish(method='direct', run_id='run-1', outcomes=outcomes(), remove_successful=True)
    client = module.app.test_client()
    assert [row['selector'] for row in client.get('/api/toolbelt/devices').get_json()['devices']] == ['192.168.0.11']
    events = client.get('/api/audit').get_json()
    results = {event['target']: event['success'] for event in events if event['event_type'].startswith('certificate_upload_')}
    assert results == {'192.168.0.10': True, '192.168.0.11': False}
