import json
import shutil
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

    def transition_job(
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
                f"UPDATE renewal_jobs SET {', '.join(assignments)} "
                "WHERE id = ? AND state = ? AND version = ?",
                values,
            )
            if cursor.rowcount != 1:
                raise ConcurrentUpdateError(
                    f"Job {job_id} was changed by another request"
                )
            conn.execute(
                "INSERT INTO events(job_id, event_type, details_json, created_at) "
                "VALUES (?, 'state_changed', ?, ?)",
                (
                    job_id,
                    json.dumps({"from": expected_state, "to": new_state}),
                    _utc_now(),
                ),
            )
        return self.get_job(job_id)

    def get_job(self, job_id):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM renewal_jobs WHERE id=?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["identifiers"] = json.loads(result.pop("identifiers_json"))
        return result

    def list_jobs(self):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM renewal_jobs ORDER BY created_at, id"
            ).fetchall()
        return [self.get_job(row["id"]) for row in rows]

    def list_events(self, job_id):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT event_type, details_json, created_at FROM events "
                "WHERE job_id=? ORDER BY id",
                (job_id,),
            ).fetchall()
        return [
            {
                "event_type": row["event_type"],
                "details": json.loads(row["details_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def put_certificate(self, certificate_id, metadata):
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO certificates(id, metadata_json, created_at) VALUES (?, ?, ?)",
                (certificate_id, json.dumps(metadata), _utc_now()),
            )

    def get_certificate(self, certificate_id):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT metadata_json, created_at FROM certificates WHERE id=?",
                (certificate_id,),
            ).fetchone()
        if row is None:
            return None
        result = json.loads(row["metadata_json"])
        result["id"] = certificate_id
        result["created_at"] = row["created_at"]
        return result

    def delete_certificate(self, certificate_id):
        with self.transaction() as conn:
            conn.execute("DELETE FROM certificates WHERE id=?", (certificate_id,))

    def complete_job_with_certificate(
        self,
        *,
        job_id,
        expected_state,
        expected_version,
        certificate_id,
        metadata,
    ):
        now = _utc_now()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO certificates(id, metadata_json, created_at) VALUES (?, ?, ?)",
                (certificate_id, json.dumps(metadata), now),
            )
            cursor = conn.execute(
                """
                UPDATE renewal_jobs
                SET state='issued', version=version + 1, certificate_id=?, updated_at=?
                WHERE id=? AND state=? AND version=?
                """,
                (
                    certificate_id,
                    now,
                    job_id,
                    expected_state,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise ConcurrentUpdateError(
                    f"Job {job_id} was changed by another request"
                )
            conn.execute(
                "INSERT INTO events(job_id, event_type, details_json, created_at) "
                "VALUES (?, 'state_changed', ?, ?)",
                (
                    job_id,
                    json.dumps({"from": expected_state, "to": "issued"}),
                    now,
                ),
            )
        return self.get_job(job_id)

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

    def put_secret(self, secret_id, blob, metadata=None):
        now = _utc_now()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO secrets(
                    id, key_id, nonce, ciphertext, purpose, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    key_id=excluded.key_id,
                    nonce=excluded.nonce,
                    ciphertext=excluded.ciphertext,
                    purpose=excluded.purpose,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    secret_id,
                    blob.key_id,
                    blob.nonce,
                    blob.ciphertext,
                    blob.purpose,
                    json.dumps(metadata or {}),
                    now,
                    now,
                ),
            )

    def get_secret(self, secret_id):
        from certmon.vault import EncryptedBlob

        with self.connect() as conn:
            row = conn.execute(
                "SELECT key_id, nonce, ciphertext, purpose FROM secrets WHERE id=?",
                (secret_id,),
            ).fetchone()
        if row is None:
            return None
        return EncryptedBlob(
            row["key_id"], row["nonce"], row["ciphertext"], row["purpose"]
        )

    def delete_secret(self, secret_id):
        with self.transaction() as conn:
            conn.execute("DELETE FROM secrets WHERE id=?", (secret_id,))

    def list_secret_metadata(self):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, key_id, purpose, metadata_json, created_at, updated_at FROM secrets"
            ).fetchall()
        return [
            {
                "id": row["id"],
                "key_id": row["key_id"],
                "purpose": row["purpose"],
                "metadata": json.loads(row["metadata_json"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def rotate_secrets(self, vault, *, interrupt_after=None):
        pending_key_id = vault.begin_rotation()
        with self.connect() as conn:
            secret_ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM secrets WHERE key_id != ? ORDER BY id",
                    (pending_key_id,),
                )
            ]

        converted = 0
        for secret_id in secret_ids:
            blob = self.get_secret(secret_id)
            plaintext = vault.decrypt(blob, purpose=blob.purpose)
            replacement = vault.encrypt_for_rotation(
                plaintext, purpose=blob.purpose
            )
            with self.transaction() as conn:
                conn.execute(
                    """
                    UPDATE secrets
                    SET key_id=?, nonce=?, ciphertext=?, updated_at=?
                    WHERE id=? AND key_id=?
                    """,
                    (
                        replacement.key_id,
                        replacement.nonce,
                        replacement.ciphertext,
                        _utc_now(),
                        secret_id,
                        blob.key_id,
                    ),
                )
            converted += 1
            if interrupt_after is not None and converted >= interrupt_after:
                raise RuntimeError("Simulated rotation interruption")

        vault.activate_pending_key()
        return converted

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

    def complete_legacy_secret_migration(self, source: Path, vault):
        source = Path(source)
        if not source.exists():
            return False
        with self.connect() as conn:
            done = conn.execute(
                "SELECT 1 FROM settings WHERE key='legacy_json_migrated_at'"
            ).fetchone()
        if done:
            return False

        raw = json.loads(source.read_text(encoding="utf-8"))
        encrypted = []
        for device in raw.get("upload_devices", []):
            password = device.get("password")
            if not password:
                continue
            device_id = device.get("id") or f"legacy:{device.get('host')}"
            secret_id = f"device-password:{device_id}"
            encrypted.append(
                (
                    device_id,
                    secret_id,
                    vault.encrypt(password.encode("utf-8"), purpose="device-password"),
                )
            )

        now = _utc_now()
        with self.transaction() as conn:
            for device_id, secret_id, blob in encrypted:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO secrets(
                        id, key_id, nonce, ciphertext, purpose, metadata_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, '{}', ?, ?)
                    """,
                    (
                        secret_id,
                        blob.key_id,
                        blob.nonce,
                        blob.ciphertext,
                        blob.purpose,
                        now,
                        now,
                    ),
                )
                conn.execute(
                    "UPDATE devices SET secret_id=? WHERE id=? AND secret_id IS NULL",
                    (secret_id, device_id),
                )
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?)",
                ("legacy_json_migrated_at", now),
            )

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = source.with_name(f"certmon_data.{timestamp}.bak.json")
        shutil.copy2(source, backup)
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
