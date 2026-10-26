from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .approval import ApprovalAuthorizer, ApprovalGate, ApprovalRecord, ReleaseGate
from .benchmark import BenchmarkRunner
from .evidence import EvidenceAuthorizer, EvidenceRegistry
from .locks import LockRegistry
from .storage import SQLiteStateStore
from .task_board import TaskBoard, TaskBoardEntry
from .task_state import TaskRecord, TaskStateMachine, TaskStatus

# Every persisted TaskRecord field; a caller's copy must match the stored copy on all of them.
_TASK_FIELDS = (
    "status", "owner", "objective", "scope", "blockers", "evidence", "required_skills", "repo",
    "branch", "risk_level", "approval_action", "blocked_from", "created_at", "updated_at",
)

_OPEN_FOR_EVIDENCE = {
    TaskStatus.INTAKE, TaskStatus.GROUNDED, TaskStatus.PLANNED, TaskStatus.READY,
    TaskStatus.IN_PROGRESS, TaskStatus.VERIFYING,
}


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RuntimeHealth:
    ready: bool
    production_mode: bool
    durable_storage: bool
    database_integrity: bool
    audit_chain_valid: bool
    checks: Dict[str, str]


class RuntimeServices:
    """Single-host runtime composition root using one transactional state store."""

    def __init__(
        self,
        *,
        db_path: Optional[str] = None,
        state_store: Optional[SQLiteStateStore] = None,
        approver_authorizer: Optional[ApprovalAuthorizer] = None,
        evidence_authorizer: Optional[EvidenceAuthorizer] = None,
        approval_ttl_seconds: int = 900,
    ) -> None:
        if state_store is not None and db_path is not None:
            raise ValueError("Pass state_store or db_path, not both")
        self.production_mode = os.environ.get("SWARM_ENV", "").strip().lower() in {"prod", "production"}
        self.store = state_store or SQLiteStateStore(db_path)
        if self.production_mode and not self.store.persistent:
            raise RuntimeError("RuntimeServices requires durable SQLite storage in production")
        if self.production_mode and approver_authorizer is None:
            raise RuntimeError("A trusted approver_authorizer is required in production")
        if self.production_mode and evidence_authorizer is None:
            raise RuntimeError("A trusted evidence_authorizer is required in production")
        self.approvals = ApprovalGate(
            state_store=self.store, approver_authorizer=approver_authorizer,
            approval_ttl_seconds=approval_ttl_seconds,
        )
        self.release_gate = ReleaseGate(
            state_store=self.store, approver_authorizer=approver_authorizer,
            approval_ttl_seconds=approval_ttl_seconds,
        )
        self.evidence = EvidenceRegistry(state_store=self.store, evidence_authorizer=evidence_authorizer)
        self.locks = LockRegistry(state_store=self.store)
        self.tasks = TaskBoard(state_store=self.store)
        self.benchmarks = BenchmarkRunner(state_store=self.store, evidence_authorizer=evidence_authorizer)
        if not self._stores_shared():
            raise RuntimeError("Runtime service construction produced split state stores")

    def _stores_shared(self) -> bool:
        stores = (
            self.approvals.store, self.release_gate.store, self.evidence.store,
            self.locks.store, self.tasks._store, self.benchmarks.registry.store,
        )
        return all(store is self.store for store in stores)

    @staticmethod
    def _entry(task: TaskRecord) -> TaskBoardEntry:
        return TaskBoardEntry(
            task_id=task.task_id, owner=task.owner, objective=task.objective, status=task.status.value,
            scope=list(task.scope), blockers=list(task.blockers), evidence=list(task.evidence),
            required_skills=list(task.required_skills), repo=task.repo, branch=task.branch,
            risk_level=task.risk_level, approval_action=task.approval_action,
            blocked_from=task.blocked_from, created_at=task.created_at, updated_at=task.updated_at,
        )

    def _serialize(self, task: TaskRecord) -> str:
        return json.dumps(
            self.tasks._entry_payload(self._entry(task)), sort_keys=True, separators=(",", ":"), allow_nan=False
        )

    def create_task(self, task: TaskRecord) -> TaskBoardEntry:
        if any(not isinstance(value, str) or not value.strip() for value in (task.task_id, task.owner, task.objective)):
            raise ValueError("Tasks require non-empty task_id, owner, and objective")
        if task.status != TaskStatus.INTAKE:
            raise ValueError("New tasks must start in INTAKE; use transition_task for later states")
        entry = self._entry(task)
        serialized = self._serialize(task)
        with self.store.transaction() as connection:
            try:
                connection.execute(
                    "INSERT INTO tasks(task_id, payload_json, updated_at) VALUES(?, ?, ?)",
                    (task.task_id, serialized, task.updated_at),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Task {task.task_id!r} already exists") from exc
            self.store.append_event_in_transaction(
                connection, "task.created", task_id=task.task_id, actor=task.owner,
                payload={
                    "status": task.status.value, "repo": task.repo,
                    "branch": task.branch, "risk_level": task.risk_level,
                },
            )
        return entry

    def load_task(self, task_id: str) -> Optional[TaskRecord]:
        entry = self.tasks.get(task_id)
        if entry is None:
            return None
        return TaskRecord(
            task_id=entry.task_id, owner=entry.owner, objective=entry.objective, status=TaskStatus(entry.status),
            scope=list(entry.scope), blockers=list(entry.blockers), evidence=list(entry.evidence),
            required_skills=list(entry.required_skills), repo=entry.repo, branch=entry.branch,
            risk_level=entry.risk_level, approval_action=entry.approval_action,
            blocked_from=entry.blocked_from, created_at=entry.created_at, updated_at=entry.updated_at,
        )

    def _current_base(self, task: TaskRecord) -> str:
        """Return the stored payload, refusing a caller copy that differs from it on any field."""
        base = self.store.get_task_json(task.task_id)
        stored = self.load_task(task.task_id)
        if base is None or stored is None:
            raise ValueError(f"Task {task.task_id!r} does not exist in durable task state")
        if any(getattr(stored, name) != getattr(task, name) for name in _TASK_FIELDS):
            raise RuntimeError("Stale or mismatched task record; reload state before changing it")
        return base

    @staticmethod
    def _snapshot(task: TaskRecord) -> Tuple[TaskStatus, str, List[str], str]:
        return task.status, task.updated_at, list(task.blockers), task.blocked_from

    @staticmethod
    def _restore(task: TaskRecord, snapshot: Tuple[TaskStatus, str, List[str], str]) -> None:
        task.status, task.updated_at, task.blockers, task.blocked_from = snapshot

    def _persist_mutation(
        self, task: TaskRecord, base_payload: str, event_type: str, event_payload: Dict[str, object]
    ) -> None:
        serialized = self._serialize(task)
        with self.store.transaction() as connection:
            row = connection.execute("SELECT payload_json FROM tasks WHERE task_id=?", (task.task_id,)).fetchone()
            if row is None or row["payload_json"] != base_payload:
                raise RuntimeError("Concurrent task update detected; reload state before retrying")
            connection.execute(
                "UPDATE tasks SET payload_json=?, updated_at=? WHERE task_id=?",
                (serialized, task.updated_at, task.task_id),
            )
            self.store.append_event_in_transaction(
                connection, event_type, task_id=task.task_id, actor=task.owner, payload=event_payload
            )

    def transition_task(
        self,
        task: TaskRecord,
        new_state: TaskStatus,
        *,
        approval_scope: Optional[str] = None,
        justification: Optional[str] = None,
    ) -> None:
        base = self._current_base(task)
        snapshot = self._snapshot(task)
        previous = task.status
        TaskStateMachine.transition(
            task, new_state, evidence_registry=self.evidence, approval_gate=self.approvals,
            approval_scope=approval_scope, justification=justification,
        )
        payload: Dict[str, object] = {
            "from": previous.value, "to": task.status.value, "evidence_count": len(task.evidence),
            "repo": task.repo, "branch": task.branch,
        }
        if justification:
            payload["justification_sha256"] = _sha256(justification)
        try:
            self._persist_mutation(task, base, "task.state_transition", payload)
        except BaseException:
            self._restore(task, snapshot)
            raise

    def add_blocker(self, task: TaskRecord, blocker: str) -> None:
        if not isinstance(blocker, str) or not blocker.strip():
            raise ValueError("A blocker must be a non-empty string")
        if task.status in {TaskStatus.CLOSED, TaskStatus.CANCELLED}:
            raise ValueError(f"Cannot block terminal task {task.task_id} in state {task.status.value}")
        base = self._current_base(task)
        snapshot = self._snapshot(task)
        previous = task.status
        TaskStateMachine.add_blocker(task, blocker)
        try:
            self._persist_mutation(
                task, base, "task.blocker_added",
                {"from": previous.value, "to": task.status.value, "blocker_sha256": _sha256(blocker)},
            )
        except BaseException:
            self._restore(task, snapshot)
            raise

    def add_evidence_reference(self, task: TaskRecord, reference: str) -> bool:
        """Attach a reference before release readiness and durably audit the change."""
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError("Evidence reference must be a non-empty string")
        if task.status not in _OPEN_FOR_EVIDENCE:
            raise ValueError("Evidence references are sealed at release readiness; create a new verification cycle")
        if reference in task.evidence:
            return False
        base = self._current_base(task)
        snapshot = self._snapshot(task)
        TaskStateMachine.add_evidence(task, reference)
        try:
            self._persist_mutation(
                task, base, "task.evidence_reference_added",
                {"status": task.status.value, "reference_sha256": _sha256(reference)},
            )
        except BaseException:
            task.evidence.remove(reference)
            self._restore(task, snapshot)
            raise
        return True

    def request_approval(
        self, task: TaskRecord, *, scope: str, approver: str, notes: str = ""
    ) -> ApprovalRecord:
        """Request approval for the task's action, with the task owner recorded as requester.

        The owner can never approve their own request, and production actions are refused
        for approvals that were not requested this way.
        """
        self._current_base(task)
        return self.approvals.request(
            task.task_id, task.approval_action or "release", scope, approver,
            evidence=list(task.evidence), notes=notes, requester=task.owner,
        )

    def can_perform_action(self, task_id: str, action: str, *, scope: str, evidence: List[str]) -> bool:
        return self.approvals.can_proceed(task_id, action, evidence=evidence, scope=scope)

    def health_check(self, audit_anchor: Optional[Dict[str, object]] = None) -> RuntimeHealth:
        checks: Dict[str, str] = {}
        try:
            with self.store.read_connection() as connection:
                rows = connection.execute("PRAGMA quick_check").fetchall()
            db_ok = bool(rows) and all(row[0] == "ok" for row in rows)
            checks["sqlite_quick_check"] = "PASS" if db_ok else "FAIL"
        except (sqlite3.Error, OSError):
            db_ok = False
            checks["sqlite_quick_check"] = "ERROR"
        try:
            audit = self.store.verify_audit_chain(anchor=audit_anchor)
            audit_ok = bool(audit.get("valid"))
            checks["audit_chain"] = "PASS" if audit_ok else "FAIL"
        except (sqlite3.Error, OSError, ValueError, TypeError):
            audit_ok = False
            checks["audit_chain"] = "ERROR"
        checks["shared_state_store"] = "PASS" if self._stores_shared() else "FAIL"
        checks["durable_storage"] = "PASS" if self.store.persistent or not self.production_mode else "FAIL"
        if self.production_mode:
            checks["keyed_audit_chain"] = "PASS" if self.store.audit_mode == "hmac-sha256" else "FAIL"
            checks["approval_identity_adapter"] = "PASS" if self.approvals.approver_authorizer else "FAIL"
            checks["evidence_identity_adapter"] = "PASS" if self.evidence.evidence_authorizer else "FAIL"
        ready = db_ok and audit_ok and all(value == "PASS" for value in checks.values())
        return RuntimeHealth(ready, self.production_mode, self.store.persistent, db_ok, audit_ok, checks)
