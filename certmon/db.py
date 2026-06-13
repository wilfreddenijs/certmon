import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class ConcurrentUpdateError(RuntimeError):
    pass


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    host TEXT NOT NULL,
                    port INTEGER NOT NULL DEFAULT 443,
                    device_type TEXT NOT NULL DEFAULT 'generic',
                    username TEXT,
                    secret_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS certificates (
                    id TEXT PRIMARY KEY,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS renewal_jobs (
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
                    certificate_id TEXT REFERENCES certificates(id),
                    error_code TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS secrets (
                    id TEXT PRIMARY KEY,
                    key_id TEXT NOT NULL,
                    nonce BLOB NOT NULL,
                    ciphertext BLOB NOT NULL,
                    purpose TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT REFERENCES renewal_jobs(id),
                    event_type TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES (?, ?)",
                (1, _utc_now()),
            )

    @contextmanager
    def transaction(self):
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_job(
        self,
        *,
        job_id,
        endpoint_host,
        endpoint_port,
        issuer_type,
        state,
        identifiers,
        profile,
        environment=None,
        dns_provider=None,
    ):
        now = _utc_now()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO renewal_jobs(
                    id, endpoint_host, endpoint_port, issuer_type, state,
                    identifiers_json, profile, environment, dns_provider,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    endpoint_host,
                    endpoint_port,
                    issuer_type,
                    state,
                    json.dumps(identifiers),
                    profile,
                    environment,
                    dns_provider,
                    now,
                    now,
                ),
            )

    def compare_and_set_job(
        self, job_id, expected_state, expected_version, new_state, updates
    ):
        allowed = {
            "certificate_id",
            "error_code",
            "error_message",
            "environment",
            "dns_provider",
        }
        unknown = set(updates) - allowed
        if unknown:
            raise ValueError(f"Unsupported job updates: {sorted(unknown)}")

        assignments = ["state = ?", "version = version + 1", "updated_at = ?"]
        values = [new_state, _utc_now()]
        for key, value in updates.items():
            assignments.append(f"{key} = ?")
            values.append(value)
        values.extend([job_id, expected_state, expected_version])

        with self.transaction() as conn:
            cursor = conn.execute(
                f"""
                UPDATE renewal_jobs
                SET {', '.join(assignments)}
                WHERE id = ? AND state = ? AND version = ?
                """,
                values,
            )
            if cursor.rowcount != 1:
                raise ConcurrentUpdateError(
                    f"Job {job_id} was changed by another request"
                )

    def load_legacy_state(self):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'legacy_state'"
            ).fetchone()
        if row is None:
            return _empty_state()
        return json.loads(row["value"])

    def save_legacy_state(self, data):
        payload = json.dumps(data)
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO settings(key, value) VALUES ('legacy_state', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (payload,),
            )

    def migrate_legacy_nonsecrets(self, source: Path):
        source = Path(source)
        if not source.exists():
            return False

        with self.connect() as conn:
            done = conn.execute(
                "SELECT 1 FROM settings WHERE key='legacy_nonsecrets_imported_at'"
            ).fetchone()
        if done:
            return False

        raw = json.loads(source.read_text(encoding="utf-8"))
        state = _empty_state()
        for key in ("manual_hosts", "scan_ranges", "certificates", "renewals"):
            state[key] = raw.get(key, state[key])
        state["upload_devices"] = [
            {key: value for key, value in device.items() if key != "password"}
            for device in raw.get("upload_devices", [])
        ]

        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES ('legacy_state', ?)",
                (json.dumps(state),),
            )
            for device in state["upload_devices"]:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO devices(
                        id, name, host, port, device_type, username, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        device.get("id") or f"legacy:{device.get('host')}",
                        device.get("name") or device.get("host") or "Legacy device",
                        device.get("host", ""),
                        int(device.get("port", 443)),
                        device.get("device_type", "generic"),
                        device.get("username", ""),
                        json.dumps({"legacy": True}),
                    ),
                )
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?)",
                ("legacy_nonsecrets_imported_at", _utc_now()),
            )
        return True


def _empty_state():
    return {
        "manual_hosts": [],
        "scan_ranges": [],
        "certificates": {},
        "renewals": [],
        "upload_devices": [],
    }


def _utc_now():
    return datetime.now(timezone.utc).isoformat()
