import pytest


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    path = tmp_path / "certmon-data"
    monkeypatch.setenv("CERTMON_DATA_DIR", str(path))
    return path
