from __future__ import annotations
import json, os, sqlite3
from dataclasses import dataclass
from typing import Dict, Optional
from .approval import ApprovalAuthorizer, ApprovalGate, ReleaseGate
from .benchmark import BenchmarkRunner
from .evidence import EvidenceAuthorizer, EvidenceRegistry
from .locks import LockRegistry
from .storage import SQLiteStateStore
from .task_board import TaskBoard, TaskBoardEntry
from .task_state import TaskRecord, TaskStateMachine, TaskStatus

@dataclass(frozen=True)
class RuntimeHealth:
    ready: bool
    production_mode: bool
    durable_storage: bool
    database_integrity: bool
    audit_chain_valid: bool
    checks: Dict[str,str]

class RuntimeServices:
    """Single-host runtime composition root using one transactional state store."""
    def __init__(self,*,db_path:Optional[str]=None,state_store:Optional[SQLiteStateStore]=None,
                 approver_authorizer:Optional[ApprovalAuthorizer]=None,
                 evidence_authorizer:Optional[EvidenceAuthorizer]=None,approval_ttl_seconds:int=900)->None:
        if state_store is not None and db_path is not None: raise ValueError("Pass state_store or db_path, not both")
        self.production_mode=os.environ.get("SWARM_ENV","").strip().lower() in {"prod","production"}
        self.store=state_store or SQLiteStateStore(db_path)
        if self.production_mode and not self.store.persistent: raise RuntimeError("RuntimeServices requires durable SQLite storage in production")
        if self.production_mode and approver_authorizer is None: raise RuntimeError("A trusted approver_authorizer is required in production")
        if self.production_mode and evidence_authorizer is None: raise RuntimeError("A trusted evidence_authorizer is required in production")
        self.approvals=ApprovalGate(state_store=self.store,approver_authorizer=approver_authorizer,approval_ttl_seconds=approval_ttl_seconds)
        self.release_gate=ReleaseGate(state_store=self.store,approver_authorizer=approver_authorizer,approval_ttl_seconds=approval_ttl_seconds)
        self.evidence=EvidenceRegistry(state_store=self.store,evidence_authorizer=evidence_authorizer)
        self.locks=LockRegistry(state_store=self.store)
        self.tasks=TaskBoard(state_store=self.store)
        self.benchmarks=BenchmarkRunner(state_store=self.store,evidence_authorizer=evidence_authorizer)
        stores=(self.approvals.store,self.release_gate.store,self.evidence.store,self.locks.store,self.tasks._store,self.benchmarks.registry.store)
        if any(x is not self.store for x in stores): raise RuntimeError("Runtime service construction produced split state stores")

    def _entry(self,t:TaskRecord)->TaskBoardEntry:
        return TaskBoardEntry(task_id=t.task_id,owner=t.owner,objective=t.objective,status=t.status.value,
            scope=list(t.scope),blockers=list(t.blockers),evidence=list(t.evidence),required_skills=list(t.required_skills),
            repo=t.repo,branch=t.branch,risk_level=t.risk_level,approval_action=t.approval_action,
            created_at=t.created_at,updated_at=t.updated_at)

    def create_task(self,t:TaskRecord)->TaskBoardEntry:
        if any(not isinstance(x,str) or not x.strip() for x in (t.task_id,t.owner,t.objective)):
            raise ValueError("Tasks require non-empty task_id, owner, and objective")
        if t.status!=TaskStatus.INTAKE: raise ValueError("New tasks must start in INTAKE; use transition_task for later states")
        entry=self._entry(t); serialized=json.dumps(self.tasks._entry_payload(entry),sort_keys=True,separators=(",",":"),allow_nan=False)
        with self.store.transaction() as c:
            try: c.execute("INSERT INTO tasks(task_id,payload_json,updated_at) VALUES(?,?,?)",(t.task_id,serialized,t.updated_at))
            except sqlite3.IntegrityError as exc: raise ValueError(f"Task {t.task_id!r} already exists") from exc
            self.store.append_event_in_transaction(c,"task.created",task_id=t.task_id,actor=t.owner,
                payload={"status":t.status.value,"repo":t.repo,"branch":t.branch,"risk_level":t.risk_level})
        return entry

    def load_task(self,task_id:str)->Optional[TaskRecord]:
        e=self.tasks.get(task_id)
        if e is None: return None
        return TaskRecord(task_id=e.task_id,owner=e.owner,objective=e.objective,status=TaskStatus(e.status),
            scope=list(e.scope),blockers=list(e.blockers),evidence=list(e.evidence),required_skills=list(e.required_skills),
            repo=e.repo,branch=e.branch,risk_level=e.risk_level,approval_action=e.approval_action,
            created_at=e.created_at,updated_at=e.updated_at)

    def transition_task(self,t:TaskRecord,new_state:TaskStatus,*,approval_scope:Optional[str]=None,justification:Optional[str]=None)->None:
        base=self.store.get_task_json(t.task_id); stored=self.load_task(t.task_id)
        if base is None or stored is None: raise ValueError(f"Task {t.task_id!r} does not exist in durable task state")
        fields=("status","owner","objective","scope","blockers","evidence","required_skills","repo","branch","risk_level","approval_action","created_at","updated_at")
        if any(getattr(stored,f)!=getattr(t,f) for f in fields): raise RuntimeError("Stale or mismatched task record; reload state before transitioning")
        previous,previous_time=t.status,t.updated_at
        TaskStateMachine.transition(t,new_state,evidence_registry=self.evidence,approval_gate=self.approvals,
                                    approval_scope=approval_scope,justification=justification)
        serialized=json.dumps(self.tasks._entry_payload(self._entry(t)),sort_keys=True,separators=(",",":"),allow_nan=False)
        try:
            with self.store.transaction() as c:
                row=c.execute("SELECT payload_json FROM tasks WHERE task_id=?",(t.task_id,)).fetchone()
                if row is None or row["payload_json"]!=base: raise RuntimeError("Concurrent task update detected; reload state before retrying")
                c.execute("UPDATE tasks SET payload_json=?,updated_at=? WHERE task_id=?",(serialized,t.updated_at,t.task_id))
                self.store.append_event_in_transaction(c,"task.state_transition",task_id=t.task_id,actor=t.owner,
                    payload={"from":previous.value,"to":t.status.value,"evidence_count":len(t.evidence),"repo":t.repo,"branch":t.branch})
        except BaseException:
            t.status,t.updated_at=previous,previous_time
            raise

    def _persist_mutation(self, task: TaskRecord, base_payload: str, previous_status: TaskStatus,
                          previous_updated_at: str, event_type: str, event_payload: Dict[str, object]) -> None:
        serialized = json.dumps(self.tasks._entry_payload(self._entry(task)), sort_keys=True,
                                separators=(",", ":"), allow_nan=False)
        try:
            with self.store.transaction() as connection:
                row = connection.execute("SELECT payload_json FROM tasks WHERE task_id=?", (task.task_id,)).fetchone()
                if row is None or row["payload_json"] != base_payload:
                    raise RuntimeError("Concurrent task update detected; reload state before retrying")
                connection.execute("UPDATE tasks SET payload_json=?,updated_at=? WHERE task_id=?",
                                   (serialized, task.updated_at, task.task_id))
                self.store.append_event_in_transaction(
                    connection, event_type, task_id=task.task_id, actor=task.owner, payload=event_payload
                )
        except BaseException:
            task.status = previous_status
            task.updated_at = previous_updated_at
            raise

    def add_blocker(self, task: TaskRecord, blocker: str) -> None:
        if not isinstance(blocker, str) or not blocker.strip():
            raise ValueError("A blocker must be a non-empty string")
        if task.status in {TaskStatus.CLOSED, TaskStatus.CANCELLED}:
            raise ValueError(f"Cannot block terminal task {task.task_id} in state {task.status.value}")
        base = self.store.get_task_json(task.task_id)
        stored = self.load_task(task.task_id)
        if base is None or stored is None or any(
            getattr(stored, name) != getattr(task, name)
            for name in ("status", "owner", "objective", "scope", "blockers", "evidence",
                         "required_skills", "repo", "branch", "risk_level", "approval_action",
                         "created_at", "updated_at")
        ):
            raise RuntimeError("Stale or mismatched task record; reload state before mutation")
        previous, previous_time = task.status, task.updated_at
        TaskStateMachine.add_blocker(task, blocker)
        self._persist_mutation(
            task, base, previous, previous_time, "task.blocker_added",
            {"from": previous.value, "to": task.status.value, "blocker_sha256":
             __import__("hashlib").sha256(blocker.encode("utf-8")).hexdigest()},
        )

    def add_evidence_reference(self, task: TaskRecord, reference: str) -> bool:
        """Attach a reference before release readiness and durably audit the change."""
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError("Evidence reference must be a non-empty string")
        if task.status not in {
            TaskStatus.INTAKE, TaskStatus.GROUNDED, TaskStatus.PLANNED, TaskStatus.READY,
            TaskStatus.IN_PROGRESS, TaskStatus.VERIFYING,
        }:
            raise ValueError("Evidence references are sealed at release readiness; create a new verification cycle")
        if reference in task.evidence:
            return False
        base = self.store.get_task_json(task.task_id)
        stored = self.load_task(task.task_id)
        if base is None or stored is None or any(
            getattr(stored, name) != getattr(task, name)
            for name in ("status", "owner", "objective", "scope", "blockers", "evidence",
                         "required_skills", "repo", "branch", "risk_level", "approval_action",
                         "created_at", "updated_at")
        ):
            raise RuntimeError("Stale or mismatched task record; reload state before mutation")
        previous, previous_time = task.status, task.updated_at
        TaskStateMachine.add_evidence(task, reference)
        self._persist_mutation(
            task, base, previous, previous_time, "task.evidence_reference_added",
            {"status": task.status.value, "reference_sha256":
             __import__("hashlib").sha256(reference.encode("utf-8")).hexdigest()},
        )
        return True

    def can_perform_action(self,task_id:str,action:str,*,scope:str,evidence:list[str])->bool:
        return self.approvals.can_proceed(task_id,action,evidence=evidence,scope=scope)

    def health_check(self)->RuntimeHealth:
        checks:Dict[str,str]={}
        try:
            with self.store.read_connection() as c: rows=c.execute("PRAGMA quick_check").fetchall()
            db_ok=bool(rows) and all(r[0]=="ok" for r in rows); checks["sqlite_quick_check"]="PASS" if db_ok else "FAIL"
        except (sqlite3.Error,OSError):
            db_ok=False; checks["sqlite_quick_check"]="ERROR"
        try:
            audit=self.store.verify_audit_chain(); audit_ok=bool(audit.get("valid")); checks["audit_chain"]="PASS" if audit_ok else "FAIL"
        except (sqlite3.Error,OSError,ValueError,TypeError):
            audit_ok=False; checks["audit_chain"]="ERROR"
        same=all(x is self.store for x in (self.approvals.store,self.release_gate.store,self.evidence.store,self.locks.store,self.tasks._store,self.benchmarks.registry.store))
        checks["shared_state_store"]="PASS" if same else "FAIL"
        checks["durable_storage"]="PASS" if self.store.persistent or not self.production_mode else "FAIL"
        if self.production_mode:
            checks["approval_identity_adapter"]="PASS" if self.approvals.approver_authorizer else "FAIL"
            checks["evidence_identity_adapter"]="PASS" if self.evidence.evidence_authorizer else "FAIL"
        return RuntimeHealth(db_ok and audit_ok and all(v=="PASS" for v in checks.values()),self.production_mode,self.store.persistent,db_ok,audit_ok,checks)
