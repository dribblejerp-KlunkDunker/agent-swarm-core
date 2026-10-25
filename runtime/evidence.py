from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .storage import SQLiteStateStore


class EvidenceStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


@dataclass
class EvidenceBundle:
    task_id: str
    title: str
    content: str
    source: str = "runtime"
    status: EvidenceStatus = EvidenceStatus.PENDING
    tags: List[str] = field(default_factory=list)


class EvidenceRegistry:
    """SQLite-backed evidence records with immutable retrieval and audited verification."""

    def __init__(
        self,
        state_store: Optional[SQLiteStateStore] = None,
        *,
        db_path: Optional[str] = None,
    ) -> None:
        if state_store is not None and db_path is not None:
            raise ValueError("Pass state_store or db_path, not both")
        self.store = state_store or SQLiteStateStore(db_path)
        production = os.environ.get("SWARM_ENV", "").strip().lower() in {"prod", "production"}
        if production and not self.store.persistent:
            raise RuntimeError("A durable SWARM_STATE_DB is required for production evidence storage")

    def add(self, bundle: EvidenceBundle) -> None:
        if not bundle.task_id.strip() or not bundle.title.strip() or not bundle.content.strip():
            raise ValueError("Evidence requires a task_id, title, and non-empty content")
        if bundle.status != EvidenceStatus.PENDING:
            raise ValueError("New evidence must start as PENDING and be verified by the registry")
        tags = list(bundle.tags)
        if any(not isinstance(tag, str) or not tag.strip() for tag in tags):
            raise ValueError("Evidence tags must be non-empty strings")
        content_hash = hashlib.sha256(bundle.content.encode("utf-8")).hexdigest()
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO evidence_bundles(task_id, title, content, source, status, tags_json)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    bundle.task_id,
                    bundle.title,
                    bundle.content,
                    bundle.source,
                    EvidenceStatus.PENDING.value,
                    json.dumps(tags, sort_keys=True, separators=(",", ":")),
                ),
            )
            self.store.append_event_in_transaction(
                connection,
                "evidence.added",
                task_id=bundle.task_id,
                payload={
                    "title": bundle.title,
                    "source": bundle.source,
                    "content_sha256": content_hash,
                    "tags": tags,
                    "initial_status": EvidenceStatus.PENDING.value,
                },
            )

    def get(self, task_id: str) -> List[EvidenceBundle]:
        with self.store.read_connection() as connection:
            rows = connection.execute(
                "SELECT title, content, source, status, tags_json FROM evidence_bundles "
                "WHERE task_id=? ORDER BY id",
                (task_id,),
            ).fetchall()
        return [
            EvidenceBundle(
                task_id=task_id,
                title=row["title"],
                content=row["content"],
                source=row["source"],
                status=EvidenceStatus(row["status"]),
                tags=json.loads(row["tags_json"]),
            )
            for row in rows
        ]

    def mark_verified(self, task_id: str, title: Optional[str] = None) -> None:
        with self.store.transaction() as connection:
            if title is None:
                cursor = connection.execute(
                    "UPDATE evidence_bundles SET status=? WHERE task_id=? AND status=?",
                    (EvidenceStatus.VERIFIED.value, task_id, EvidenceStatus.PENDING.value),
                )
            else:
                cursor = connection.execute(
                    "UPDATE evidence_bundles SET status=? WHERE task_id=? AND title=? AND status=?",
                    (EvidenceStatus.VERIFIED.value, task_id, title, EvidenceStatus.PENDING.value),
                )
            changed = cursor.rowcount
            self.store.append_event_in_transaction(
                connection,
                "evidence.verified" if changed else "evidence.verification_noop",
                task_id=task_id,
                payload={"title": title, "records_changed": changed},
            )

    def mark_rejected(self, task_id: str, title: Optional[str] = None) -> None:
        with self.store.transaction() as connection:
            if title is None:
                cursor = connection.execute(
                    "UPDATE evidence_bundles SET status=? WHERE task_id=? AND status<>?",
                    (EvidenceStatus.REJECTED.value, task_id, EvidenceStatus.REJECTED.value),
                )
            else:
                cursor = connection.execute(
                    "UPDATE evidence_bundles SET status=? WHERE task_id=? AND title=? AND status<>?",
                    (EvidenceStatus.REJECTED.value, task_id, title, EvidenceStatus.REJECTED.value),
                )
            changed = cursor.rowcount
            self.store.append_event_in_transaction(
                connection,
                "evidence.rejected" if changed else "evidence.rejection_noop",
                task_id=task_id,
                payload={"title": title, "records_changed": changed},
            )

    def is_verified(self, task_id: str) -> bool:
        with self.store.read_connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS verified,
                       SUM(CASE WHEN status <> ? THEN 1 ELSE 0 END) AS not_verified
                FROM evidence_bundles WHERE task_id=?
                """,
                (EvidenceStatus.VERIFIED.value, EvidenceStatus.VERIFIED.value, task_id),
            ).fetchone()
        return bool(row["total"]) and row["total"] == row["verified"] and row["not_verified"] == 0

    def has_evidence(self, task_id: str) -> bool:
        with self.store.read_connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM evidence_bundles WHERE task_id=? LIMIT 1", (task_id,)
            ).fetchone()
        return row is not None
