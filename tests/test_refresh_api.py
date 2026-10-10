from tests.test_ca_api import load_app
from contextlib import contextmanager
from types import SimpleNamespace
import ssl


def test_refresh_records_connection_timeout_and_preserves_last_certificate(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir)
    state = module.database.load_legacy_state()
    previous = {'host': '192.0.2.1', 'port': 443, 'cn': 'Panel', 'serial': 'old',
                'last_checked': '2026-10-01T10:00:00+00:00', 'status': 'ok', 'issuer': 'CertMon'}
    state['certificates'] = {'192.0.2.1:443': previous}
    module.database.save_legacy_state(state)
    calls = []
    def timeout(address, timeout):
        calls.append((address, timeout))
        raise TimeoutError()
    monkeypatch.setattr(module.socket, 'create_connection', timeout)
    result = module.app.test_client().post('/api/refresh/192.0.2.1:443').get_json()
    assert result['ok'] is False
    assert result['cert']['availability'] == 'offline'
    stored = module.database.load_legacy_state()['certificates']['192.0.2.1:443']
    assert all(stored[key] == value for key, value in previous.items())
    assert stored['availability'] == 'offline'
    assert calls == [(('192.0.2.1', 443), 3)]


def test_tls_failure_is_online_and_closes_tcp_without_replacing_certificate(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir)
    state = module.database.load_legacy_state()
    state['certificates'] = {'192.0.2.1:8443': {'serial': 'old', 'last_checked': 'original'}}
    module.database.save_legacy_state(state)
    closed = []
    @contextmanager
    def connection(address, timeout):
        try:
            yield object()
        finally:
            closed.append(address)
    def handshake(*args, **kwargs):
        raise ssl.SSLError('handshake failed')
    monkeypatch.setattr(module.socket, 'create_connection', connection)
    monkeypatch.setattr(module.ssl, 'create_default_context', lambda: SimpleNamespace(wrap_socket=handshake))
    result = module.app.test_client().post('/api/refresh/192.0.2.1:8443').get_json()
    assert result['ok'] is False
    assert result['cert']['availability'] == 'online'
    stored = module.database.load_legacy_state()['certificates']['192.0.2.1:8443']
    assert stored['serial'] == 'old'
    assert stored['last_checked'] == 'original'
    assert stored['error'] == 'HTTPS certificate could not be read'
    assert closed == [('192.0.2.1', 8443)]
    assert module.get_cert_info('192.0.2.1', 8443) is None


def test_refresh_replaces_monitor_data_and_reports_offline_failure(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir)
    state = module.database.load_legacy_state()
    state['certificates'] = {'192.0.2.1:443': {'serial': 'old'}}
    module.database.save_legacy_state(state)
    client = module.app.test_client()
    monkeypatch.setattr(module, 'get_cert_info', lambda host, port, **kwargs: None)
    assert client.post('/api/refresh/192.0.2.1:443').get_json()['ok'] is False
    assert module.database.load_legacy_state()['certificates']['192.0.2.1:443']['serial'] == 'old'
    offline = module.database.load_legacy_state()['certificates']['192.0.2.1:443']
    assert offline['availability'] == 'offline'
    assert offline['availability_checked']
    assert offline['error'] == 'HTTPS endpoint unreachable'
    monkeypatch.setattr(module, 'get_cert_info', lambda host, port, **kwargs: {
        'host': host, 'port': port, 'serial': 'new', 'error': None, 'availability': 'online'})
    assert client.post('/api/refresh/192.0.2.1:443').get_json()['ok'] is True
    assert module.database.load_legacy_state()['certificates']['192.0.2.1:443']['serial'] == 'new'
    assert module.database.load_legacy_state()['certificates']['192.0.2.1:443']['availability'] == 'online'
