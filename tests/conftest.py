import importlib
import threading
import time
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from werkzeug.serving import make_server


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    path = tmp_path / "certmon-data"
    monkeypatch.setenv("CERTMON_DATA_DIR", str(path))
    return path


@dataclass(frozen=True)
class LiveCertmon:
    base_url: str


def _wait_for_certmon(base_url):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            with urlopen(base_url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except URLError:
            time.sleep(0.05)
    raise RuntimeError(f"CertMon did not become ready at {base_url}")


@pytest.fixture
def live_certmon(tmp_data_dir, monkeypatch):
    servers = []

    def start(*, server_mode):
        monkeypatch.setenv("CERTMON_DATA_DIR", str(tmp_data_dir))
        if server_mode:
            monkeypatch.setenv("CERTMON_SERVER_MODE", "1")
            monkeypatch.setenv("CERTMON_BIND_HOST", "127.0.0.1")
        else:
            monkeypatch.delenv("CERTMON_SERVER_MODE", raising=False)
            monkeypatch.delenv("CERTMON_BIND_HOST", raising=False)

        import app

        module = importlib.reload(app)
        server = make_server("127.0.0.1", 0, module.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            _wait_for_certmon(base_url)
        except Exception:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            raise
        servers.append((server, thread))
        return LiveCertmon(base_url=base_url)

    yield start

    for server, thread in reversed(servers):
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        if thread.is_alive():
            pytest.fail("CertMon live server thread did not stop")
