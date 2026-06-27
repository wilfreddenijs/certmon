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
    with db.connect() as conn:
        renewal_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(renewal_jobs)")
        }
    assert "metadata_json" in renewal_columns


def test_initialize_migrates_existing_renewal_jobs_metadata_column(tmp_path):
    path = tmp_path / "certmon.db"
    db = Database(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with db.connect() as conn:
        conn.executescript(
            """
            CREATE TABLE renewal_jobs (
                id TEXT PRIMARY KEY,
                endpoint_host TEXT NOT NULL,
                endpoint_port INTEGER NOT NULL,
                issuer_type TEXT NOT NULL,
                state TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 0,
                identifiers_json TEXT NOT NULL,
                profile TEXT NOT NULL,
                environment TEXT,
                dns_provider TEXT,
                certificate_id TEXT,
                error_code TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

    db.initialize()

    with db.connect() as conn:
        renewal_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(renewal_jobs)")
        }
    assert "metadata_json" in renewal_columns


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
