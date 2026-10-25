from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class SQLiteStateStore:
    """Transactional SQLite persistence and a tamper-evident append-only audit chain.

    In production, SWARM_STATE_DB must name a durable SQLite file. Development/test
    instances without a path are isolated in-memory stores and are never production-safe.
    """

    SCHEMA_VERSION = 2

    def __init__(self, db_path: Optional[str] = None):
        configured_path = db_path or os.environ.get("SWARM_STATE_DB")
        production = os.environ.get("SWARM_ENV", "").strip().lower() in {"prod", "production"}
        if production and (not configured_path or configured_path == ":memory:"):
            raise RuntimeError("SWARM_STATE_DB must point to a durable SQLite database in production")

        self.path: Optional[Path]
        self._memory_connection: Optional[sqlite3.Connection] = None
        self._memory_lock = threading.RLock()
        if configured_path in {None, "", ":memory:"}:
            self.path = None
            self._memory_connection = sqlite3.connect(
                ":memory:", timeout=15, isolation_level=None, check_same_thread=False
            )
            self._configure_connection(self._memory_connection)
            self._initialize(self._memory_connection)
        else:
            raw_path = Path(configured_path).expanduser()
            if raw_path.is_symlink():
                raise ValueError("SWARM_STATE_DB must not point to a symbolic link")
            self.path = raw_path.resolve()
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            connection = self._connect_file()
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA synchronous=FULL")
                self._initialize(connection)
            finally:
                connection.close()
            try:
                os.chmod(self.path, 0o600)
                for suffix in ("-wal", "-shm"):
                    sidecar = Path(str(self.path) + suffix)
                    if sidecar.exists():
                        os.chmod(sidecar, 0o600)
            except OSError:
                pass

    @property
    def persistent(self) -> bool:
        return self.path is not None

    def _configure_connection(self, connection: sqlite3.Connection) -> None:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=15000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")

    def _connect_file(self) -> sqlite3.Connection:
        if self.path is None:
            raise RuntimeError("File-backed connection requested for an in-memory store")
        connection = sqlite3.connect(str(self.path), timeout=15, isolation_level=None)
        self._configure_connection(connection)
        return connection

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        """Read view with connection lifecycle handled by the store."""
        if self._memory_connection is not None:
            with self._memory_lock:
                yield self._memory_connection
            return
        connection = self._connect_file()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Open a serialized write transaction; SQLite coordinates independent processes."""
        if self._memory_connection is not None:
            with self._memory_lock:
                connection = self._memory_connection
                connection.execute("BEGIN IMMEDIATE")
                try:
                    yield connection
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
            return

        connection = self._connect_file()
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        finally:
            connection.close()

    def _initialize(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS approvals (
                task_id TEXT PRIMARY KEY,
                record_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS approval_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                record_json TEXT NOT NULL,
                archived_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS resource_locks (
                resource TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                owner TEXT NOT NULL,
                reason TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                lease_expires_at TEXT
            );

            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evidence_bundles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                tags_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                task_id TEXT,
                actor TEXT,
                payload_json TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL UNIQUE
            );

            CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_events(task_id, sequence);

            CREATE TRIGGER IF NOT EXISTS audit_events_no_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit_events are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit_events are append-only');
            END;
            CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_events(event_type, sequence);
            CREATE INDEX IF NOT EXISTS idx_lock_task ON resource_locks(task_id);
            CREATE INDEX IF NOT EXISTS idx_approval_history_task ON approval_history(task_id, id);
            CREATE INDEX IF NOT EXISTS idx_evidence_task ON evidence_bundles(task_id, id);
            """
        )
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(self.SCHEMA_VERSION),),
            )
        else:
            version = int(row["value"])
            if version > self.SCHEMA_VERSION:
                raise RuntimeError(
                    f"State database schema {version} is newer than supported schema {self.SCHEMA_VERSION}"
                )
            if version < self.SCHEMA_VERSION:
                connection.execute(
                    "UPDATE metadata SET value=? WHERE key='schema_version'",
                    (str(self.SCHEMA_VERSION),),
                )

    def append_event_in_transaction(
        self,
        connection: sqlite3.Connection,
        event_type: str,
        task_id: Optional[str] = None,
        actor: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not event_type.strip():
            raise ValueError("event_type must be non-empty")
        payload_json = _canonical_json(payload or {})
        previous = connection.execute(
            "SELECT sequence, event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["event_hash"] if previous else "GENESIS"
        sequence = int(previous["sequence"]) + 1 if previous else 1
        timestamp = utc_now()
        signed_fields = {
            "sequence": sequence,
            "timestamp": timestamp,
            "event_type": event_type,
            "task_id": task_id,
            "actor": actor,
            "payload_json": payload_json,
            "previous_hash": previous_hash,
        }
        event_hash = hashlib.sha256(
            (previous_hash + "\n" + _canonical_json(signed_fields)).encode("utf-8")
        ).hexdigest()
        connection.execute(
            """
            INSERT INTO audit_events(
                sequence, timestamp, event_type, task_id, actor,
                payload_json, previous_hash, event_hash
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (sequence, timestamp, event_type, task_id, actor, payload_json, previous_hash, event_hash),
        )
        return {
            **signed_fields,
            "payload": json.loads(payload_json),
            "event_hash": event_hash,
        }

    def append_event(
        self,
        event_type: str,
        task_id: Optional[str] = None,
        actor: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self.transaction() as connection:
            return self.append_event_in_transaction(
                connection, event_type, task_id=task_id, actor=actor, payload=payload
            )

    def list_events(self, after_sequence: int = 0, limit: int = 1000) -> List[Dict[str, Any]]:
        if limit < 1 or limit > 10000:
            raise ValueError("limit must be between 1 and 10000")
        with self.read_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_events WHERE sequence > ? ORDER BY sequence LIMIT ?",
                (after_sequence, limit),
            ).fetchall()
        return [
            {
                "sequence": row["sequence"],
                "timestamp": row["timestamp"],
                "event_type": row["event_type"],
                "task_id": row["task_id"],
                "actor": row["actor"],
                "payload": json.loads(row["payload_json"]),
                "previous_hash": row["previous_hash"],
                "event_hash": row["event_hash"],
            }
            for row in rows
        ]

    def verify_audit_chain(self) -> Dict[str, Any]:
        previous_hash = "GENESIS"
        expected_sequence = 1
        verified_count = 0
        while True:
            page = self.list_events(after_sequence=expected_sequence - 1, limit=10000)
            if not page:
                break
            for event in page:
                if event["sequence"] != expected_sequence:
                    return {"valid": False, "events": verified_count, "error": f"sequence mismatch at {expected_sequence}"}
                if event["previous_hash"] != previous_hash:
                    return {"valid": False, "events": verified_count, "error": f"previous hash mismatch at {expected_sequence}"}
                payload_json = _canonical_json(event["payload"])
                signed_fields = {
                    "sequence": event["sequence"],
                    "timestamp": event["timestamp"],
                    "event_type": event["event_type"],
                    "task_id": event["task_id"],
                    "actor": event["actor"],
                    "payload_json": payload_json,
                    "previous_hash": previous_hash,
                }
                expected_hash = hashlib.sha256(
                    (previous_hash + "\n" + _canonical_json(signed_fields)).encode("utf-8")
                ).hexdigest()
                if event["event_hash"] != expected_hash:
                    return {"valid": False, "events": verified_count, "error": f"event hash mismatch at {expected_sequence}"}
                previous_hash = event["event_hash"]
                expected_sequence += 1
                verified_count += 1
            if len(page) < 10000:
                break
        return {"valid": True, "events": verified_count, "error": None}

    def verify_task_status(self, task_id: str, expected_status: str) -> bool:
        """Reconcile durable task state with its append-only lifecycle history."""
        if not self.verify_audit_chain()["valid"]:
            return False
        serialized = self.get_task_json(task_id)
        if serialized is None:
            return False
        try:
            payload = json.loads(serialized)
        except (TypeError, json.JSONDecodeError):
            return False
        with self.read_connection() as connection:
            rows = connection.execute(
                "SELECT sequence, event_type, payload_json FROM audit_events "
                "WHERE task_id=? AND event_type IN ('task.created', 'task.state_transition') ORDER BY sequence",
                (task_id,),
            ).fetchall()
        if not rows or rows[0]["event_type"] != "task.created":
            return False
        if sum(row["event_type"] == "task.created" for row in rows) != 1:
            return False
        try:
            status = json.loads(rows[0]["payload_json"]).get("status")
            for row in rows[1:]:
                event = json.loads(row["payload_json"])
                if row["event_type"] != "task.state_transition" or event.get("from") != status:
                    return False
                target = event.get("to")
                if not isinstance(target, str):
                    return False
                status = target
        except (TypeError, json.JSONDecodeError):
            return False
        return isinstance(status, str) and status == expected_status == payload.get("status")

    def verify_evidence_state(self, task_id: str, references: Optional[List[str]] = None) -> bool:
        """Verify persisted evidence bytes and status against the audit history."""
        if not self.verify_audit_chain()["valid"]:
            return False
        with self.read_connection() as connection:
            evidence_rows = connection.execute(
                "SELECT id, task_id, title, content, source, status, tags_json "
                "FROM evidence_bundles WHERE task_id=? ORDER BY id",
                (task_id,),
            ).fetchall()
            event_rows = connection.execute(
                "SELECT sequence, event_type, task_id, payload_json FROM audit_events "
                "WHERE task_id=? AND event_type IN ('evidence.added','evidence.verified','evidence.rejected') "
                "ORDER BY sequence",
                (task_id,),
            ).fetchall()
        if not evidence_rows:
            return False
        try:
            events = [{
                "sequence": row["sequence"],
                "event_type": row["event_type"],
                "task_id": row["task_id"],
                "payload": json.loads(row["payload_json"]),
            } for row in event_rows]
        except (TypeError, json.JSONDecodeError):
            return False

        additions: Dict[int, Dict[str, Any]] = {}
        for event in events:
            if event["event_type"] == "evidence.added":
                record_id = event["payload"].get("record_id")
                if not isinstance(record_id, int) or record_id in additions:
                    return False
                additions[record_id] = event

        verified_titles: set[str] = set()
        for row in evidence_rows:
            addition = additions.get(row["id"])
            if addition is None or addition["task_id"] != task_id:
                return False
            try:
                tags = json.loads(row["tags_json"])
            except (TypeError, json.JSONDecodeError):
                return False
            add_payload = addition["payload"]
            digest = hashlib.sha256(row["content"].encode("utf-8")).hexdigest()
            if (
                add_payload.get("title") != row["title"]
                or add_payload.get("source") != row["source"]
                or add_payload.get("content_sha256") != digest
                or add_payload.get("tags") != tags
                or add_payload.get("initial_status") != "PENDING"
            ):
                return False
            status = "PENDING"
            for event in events:
                if event["sequence"] <= addition["sequence"]:
                    continue
                if event["event_type"] not in {"evidence.verified", "evidence.rejected"}:
                    continue
                if row["id"] not in event["payload"].get("record_ids", []):
                    continue
                target = event["payload"].get("target_status")
                if target not in {"VERIFIED", "REJECTED"}:
                    return False
                status = target
            if status != row["status"] or status != "VERIFIED":
                return False
            verified_titles.add(row["title"])
        if references is None:
            return True
        if not references or any(not isinstance(item, str) or not item.strip() for item in references):
            return False
        return set(references).issubset(verified_titles)

    def get_approval_json(self, task_id: str) -> Optional[str]:
        with self.read_connection() as connection:
            row = connection.execute(
                "SELECT record_json FROM approvals WHERE task_id = ?", (task_id,)
            ).fetchone()
        return row["record_json"] if row else None

    def get_approval_history_json(self, task_id: str) -> List[str]:
        with self.read_connection() as connection:
            rows = connection.execute(
                "SELECT record_json FROM approval_history WHERE task_id = ? ORDER BY id",
                (task_id,),
            ).fetchall()
        return [row["record_json"] for row in rows]

    def put_task_json(
        self,
        task_id: str,
        payload_json: str,
        updated_at: str,
        actor: Optional[str] = None,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO tasks(task_id, payload_json, updated_at) VALUES(?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    payload_json=excluded.payload_json, updated_at=excluded.updated_at
                """,
                (task_id, payload_json, updated_at),
            )
            self.append_event_in_transaction(
                connection,
                "task.persisted",
                task_id=task_id,
                actor=actor,
                payload={"updated_at": updated_at},
            )

    def get_task_json(self, task_id: str) -> Optional[str]:
        with self.read_connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        return row["payload_json"] if row else None

    def list_task_json(self) -> Dict[str, str]:
        with self.read_connection() as connection:
            rows = connection.execute(
                "SELECT task_id, payload_json FROM tasks ORDER BY task_id"
            ).fetchall()
        return {row["task_id"]: row["payload_json"] for row in rows}
