from pathlib import Path

from certmon.config import resolve_data_dir


def test_explicit_data_dir_wins(tmp_path, monkeypatch):
    configured = tmp_path / "server-data"
    monkeypatch.setenv("CERTMON_DATA_DIR", str(configured))

    result = resolve_data_dir(
        frozen=False,
        executable=Path("ignored"),
        source_dir=Path("ignored"),
    )

    assert result == configured


def test_development_defaults_to_source_data_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("CERTMON_DATA_DIR", raising=False)

    result = resolve_data_dir(
        frozen=False,
        executable=Path("ignored"),
        source_dir=tmp_path,
    )

    assert result == tmp_path / "data"


def test_frozen_defaults_to_program_data(tmp_path, monkeypatch):
    monkeypatch.delenv("CERTMON_DATA_DIR", raising=False)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "program-data"))

    result = resolve_data_dir(
        frozen=True,
        executable=tmp_path / "app" / "CertMon.exe",
        source_dir=Path("ignored"),
    )

    assert result == tmp_path / "program-data" / "CertMon"


def test_frozen_falls_back_to_executable_parent(tmp_path, monkeypatch):
    monkeypatch.delenv("CERTMON_DATA_DIR", raising=False)
    monkeypatch.delenv("PROGRAMDATA", raising=False)

    result = resolve_data_dir(
        frozen=True,
        executable=tmp_path / "app" / "CertMon.exe",
        source_dir=Path("ignored"),
    )

    assert result == tmp_path / "app" / "CertMon"
