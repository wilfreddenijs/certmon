import importlib


def test_app_data_file_uses_configured_data_directory(tmp_data_dir):
    import app

    reloaded = importlib.reload(app)

    assert reloaded.DATA_FILE == str(tmp_data_dir / "certmon_data.json")
    assert tmp_data_dir.is_dir()
