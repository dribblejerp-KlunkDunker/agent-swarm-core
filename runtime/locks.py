from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Set

from .storage import SQLiteStateStore, utc_now


DEFAULT_LEASE_SECONDS = 1800
MAX_LEASE_SECONDS = 604800


def _is_production() -> bool:
    return os.environ.get("SWARM_ENV", "").strip().lower() in {"prod", "production"}


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class Lock:
    resource: str
    task_id: str
    owner: str
    reason: str
    acquired_at: str = ""
    lease_expires_at: Optional[str] = None


class LockRegistry:
    """Cross-process resource locks backed by transactional SQLite storage.

    Locks are leased for DEFAULT_LEASE_SECONDS unless the caller asks otherwise, so a crashed
    agent cannot hold a resource forever; long work renews its lease. lease_seconds=None
    reserves a lock that never expires and is refused in production.
    """

    def __init__(
        self,
        state_store: Optional[SQLiteStateStore] = None,
        *,
        db_path: Optional[str] = None,
    ) -> None:
        if state_store is not None and db_path is not None:
            raise ValueError("Pass state_store or db_path, not both")
        self.store = state_store or SQLiteStateStore(db_path)
        if _is_production() and not self.store.persistent:
            raise RuntimeError("A durable SWARM_STATE_DB is required for production resource locks")

    @staticmethod
    def _normalize(resource: str) -> str:
        normalized = (resource or "").strip().replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        normalized = normalized.rstrip("/")
        if not normalized:
            raise ValueError("resource must be a non-empty path or identifier")
        return normalized

    @staticmethod
    def _overlaps(left: str, right: str) -> bool:
        return left == right or left.startswith(right + "/") or right.startswith(left + "/")

    @staticmethod
    def _row_to_lock(row: object) -> Lock:
        return Lock(
            resource=row["resource"],
            task_id=row["task_id"],
            owner=row["owner"],
            reason=row["reason"],
            acquired_at=row["acquired_at"],
            lease_expires_at=row["lease_expires_at"],
        )

    def _expire_in_transaction(self, connection: object, now: str) -> int:
        rows = connection.execute(
            "SELECT resource, task_id, owner, lease_expires_at FROM resource_locks "
            "WHERE lease_expires_at IS NOT NULL AND lease_expires_at <= ?",
            (now,),
        ).fetchall()
        for row in rows:
            connection.execute("DELETE FROM resource_locks WHERE resource = ?", (row["resource"],))
            self.store.append_event_in_transaction(
                connection,
                "lock.lease_expired",
                task_id=row["task_id"],
                actor=row["owner"],
                payload={"resource": row["resource"], "lease_expires_at": row["lease_expires_at"]},
            )
        return len(rows)

    def reserve(
        self,
        resource: str,
        task_id: str,
        owner: str,
        reason: str,
        *,
        lease_seconds: Optional[int] = DEFAULT_LEASE_SECONDS,
    ) -> bool:
        normalized = self._normalize(resource)
        task_id = (task_id or "").strip()
        owner = (owner or "").strip()
        if not task_id or not owner or not reason.strip():
            raise ValueError("task_id, owner, and reason must be non-empty")
        if lease_seconds is None and _is_production():
            raise ValueError("Locks without a lease are not allowed in production; pass lease_seconds and renew it")
        if lease_seconds is not None and (lease_seconds < 1 or lease_seconds > MAX_LEASE_SECONDS):
            raise ValueError("lease_seconds must be between 1 second and 7 days")

        now = datetime.now(timezone.utc)
        acquired_at = now.isoformat(timespec="microseconds")
        expires_at = (
            (now + timedelta(seconds=lease_seconds)).isoformat(timespec="microseconds")
            if lease_seconds is not None else None
        )

        with self.store.transaction() as connection:
            self._expire_in_transaction(connection, acquired_at)
            rows = connection.execute("SELECT * FROM resource_locks").fetchall()
            for row in rows:
                existing = self._row_to_lock(row)
                if not self._overlaps(normalized, existing.resource):
                    continue
                if existing.task_id != task_id or existing.owner != owner:
                    self.store.append_event_in_transaction(
                        connection, "lock.reserve_denied", task_id=task_id, actor=owner,
                        payload={
                            "resource": normalized,
                            "conflicting_resource": existing.resource,
                            "conflicting_task": existing.task_id,
                            "conflicting_owner": existing.owner,
                        },
                    )
                    return False
                if existing.resource == normalized:
                    connection.execute(
                        "UPDATE resource_locks SET reason=?, lease_expires_at=? WHERE resource=? AND task_id=? AND owner=?",
                        (reason, expires_at, normalized, task_id, owner),
                    )
                    self.store.append_event_in_transaction(
                        connection, "lock.renewed", task_id=task_id, actor=owner,
                        payload={"resource": normalized, "lease_expires_at": expires_at},
                    )
                    return True

            connection.execute(
                """
                INSERT INTO resource_locks(resource, task_id, owner, reason, acquired_at, lease_expires_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (normalized, task_id, owner, reason, acquired_at, expires_at),
            )
            self.store.append_event_in_transaction(
                connection, "lock.reserved", task_id=task_id, actor=owner,
                payload={"resource": normalized, "reason": reason, "lease_expires_at": expires_at},
            )
            return True

    def renew(
        self,
        resource: str,
        task_id: str,
        owner: str,
        *,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> bool:
        normalized = self._normalize(resource)
        if lease_seconds < 1 or lease_seconds > MAX_LEASE_SECONDS:
            raise ValueError("lease_seconds must be between 1 second and 7 days")
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(seconds=lease_seconds)).isoformat(timespec="microseconds")
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT lease_expires_at FROM resource_locks WHERE resource=? AND task_id=? AND owner=?",
                (normalized, task_id, owner),
            ).fetchone()
            if row is None:
                self.store.append_event_in_transaction(
                    connection, "lock.renew_denied", task_id=task_id, actor=owner,
                    payload={"resource": normalized, "reason": "ownership_mismatch_or_missing_lock"},
                )
                return False
            if row["lease_expires_at"] and _parse_time(row["lease_expires_at"]) <= now:
                connection.execute("DELETE FROM resource_locks WHERE resource=?", (normalized,))
                self.store.append_event_in_transaction(
                    connection, "lock.renew_denied", task_id=task_id, actor=owner,
                    payload={"resource": normalized, "reason": "lease_expired"},
                )
                return False
            connection.execute(
                "UPDATE resource_locks SET lease_expires_at=? WHERE resource=? AND task_id=? AND owner=?",
                (expires_at, normalized, task_id, owner),
            )
            self.store.append_event_in_transaction(
                connection, "lock.renewed", task_id=task_id, actor=owner,
                payload={"resource": normalized, "lease_expires_at": expires_at},
            )
            return True

    def release(
        self,
        resource: str,
        task_id: Optional[str] = None,
        owner: Optional[str] = None,
    ) -> bool:
        normalized = self._normalize(resource)
        if not task_id or not owner:
            return False
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM resource_locks WHERE resource=? AND task_id=? AND owner=?",
                (normalized, task_id, owner),
            ).fetchone()
            if row is None:
                self.store.append_event_in_transaction(
                    connection, "lock.release_denied", task_id=task_id, actor=owner,
                    payload={"resource": normalized, "reason": "ownership_mismatch_or_missing_lock"},
                )
                return False
            connection.execute(
                "DELETE FROM resource_locks WHERE resource=? AND task_id=? AND owner=?",
                (normalized, task_id, owner),
            )
            self.store.append_event_in_transaction(
                connection, "lock.released", task_id=task_id, actor=owner,
                payload={"resource": normalized},
            )
            return True

    def release_expired(self) -> int:
        with self.store.transaction() as connection:
            return self._expire_in_transaction(connection, utc_now())

    def check(self, resource: str) -> Optional[Lock]:
        normalized = self._normalize(resource)
        with self.store.transaction() as connection:
            self._expire_in_transaction(connection, utc_now())
            rows = connection.execute("SELECT * FROM resource_locks").fetchall()
            matches = [
                self._row_to_lock(row)
                for row in rows
                if self._overlaps(normalized, row["resource"])
            ]
            return max(matches, key=lambda lock: len(lock.resource), default=None)

    def list_lock_records(self) -> List[Lock]:
        with self.store.transaction() as connection:
            self._expire_in_transaction(connection, utc_now())
            rows = connection.execute("SELECT * FROM resource_locks ORDER BY resource").fetchall()
            return [self._row_to_lock(row) for row in rows]

    def list_locks(self) -> Set[str]:
        with self.store.transaction() as connection:
            self._expire_in_transaction(connection, utc_now())
            rows = connection.execute("SELECT resource FROM resource_locks").fetchall()
            return {row["resource"] for row in rows}
