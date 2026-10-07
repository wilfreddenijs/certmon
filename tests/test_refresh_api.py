from tests.test_ca_api import load_app


def test_refresh_replaces_monitor_data_and_reports_offline_failure(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir)
    state = module.database.load_legacy_state()
    state['certificates'] = {'192.0.2.1:443': {'serial': 'old'}}
    module.database.save_legacy_state(state)
    client = module.app.test_client()
    monkeypatch.setattr(module, 'get_cert_info', lambda host, port: None)
    assert client.post('/api/refresh/192.0.2.1:443').get_json()['ok'] is False
    assert module.database.load_legacy_state()['certificates']['192.0.2.1:443']['serial'] == 'old'
    monkeypatch.setattr(module, 'get_cert_info', lambda host, port: {'host': host, 'port': port, 'serial': 'new', 'error': None})
    assert client.post('/api/refresh/192.0.2.1:443').get_json()['ok'] is True
    assert module.database.load_legacy_state()['certificates']['192.0.2.1:443']['serial'] == 'new'
