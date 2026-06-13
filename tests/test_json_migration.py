import json

from certmon.db import Database


def test_legacy_nonsecret_migration_is_idempotent(tmp_path):
    source = tmp_path / "certmon_data.json"
    source.write_text(
        json.dumps(
            {
                "manual_hosts": [{"host": "device.local", "port": 443}],
                "scan_ranges": ["192.168.1.0/24"],
                "certificates": {"device.local:443": {"cn": "device.local"}},
                "renewals": [{"id": 1, "host": "device.local", "port": 443}],
                "upload_devices": [
                    {
                        "id": "dev-1",
                        "name": "Extron",
                        "host": "192.168.1.20",
                        "device_type": "extron",
                        "password": "must-not-be-imported-yet",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    db = Database(tmp_path / "certmon.db")
    db.initialize()

    assert db.migrate_legacy_nonsecrets(source) is True
    assert db.migrate_legacy_nonsecrets(source) is False

    state = db.load_legacy_state()
    assert state["manual_hosts"] == [{"host": "device.local", "port": 443}]
    assert state["scan_ranges"] == ["192.168.1.0/24"]
    assert "password" not in state["upload_devices"][0]
    assert source.exists()
