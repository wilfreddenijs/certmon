import pytest

from certmon.db import ConcurrentUpdateError, Database


def test_database_enables_wal_foreign_keys_and_schema(tmp_path):
    db = Database(tmp_path / "certmon.db")
    db.initialize()

    with db.connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    assert {
        "schema_version",
        "settings",
        "devices",
        "renewal_jobs",
        "certificates",
        "secrets",
        "events",
    } <= tables


def test_transaction_rolls_back_all_changes(tmp_path):
    db = Database(tmp_path / "certmon.db")
    db.initialize()

    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?)",
                ("x", "1"),
            )
            raise RuntimeError("stop")

    with db.connect() as conn:
        assert conn.execute(
            "SELECT value FROM settings WHERE key='x'"
        ).fetchone() is None


def test_compare_and_set_rejects_stale_job_version(tmp_path):
    db = Database(tmp_path / "certmon.db")
    db.initialize()
    db.create_job(
        job_id="job-1",
        endpoint_host="device.local",
        endpoint_port=443,
        issuer_type="local_ca",
        state="draft",
        identifiers=["device.local"],
        profile="generic-rsa",
    )

    db.compare_and_set_job("job-1", "draft", 0, "issuing", {})

    with pytest.raises(ConcurrentUpdateError):
        db.compare_and_set_job("job-1", "draft", 0, "issuing", {})
