from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TaskStatus(str, Enum):
    INTAKE = "INTAKE"
    GROUNDED = "GROUNDED"
    PLANNED = "PLANNED"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFYING = "VERIFYING"
    READY_FOR_RELEASE = "READY_FOR_RELEASE"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RELEASED = "RELEASED"
    CLOSED = "CLOSED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


VALID_TRANSITIONS: Dict[TaskStatus, List[TaskStatus]] = {
    TaskStatus.INTAKE: [TaskStatus.GROUNDED, TaskStatus.BLOCKED, TaskStatus.CANCELLED],
    TaskStatus.GROUNDED: [TaskStatus.PLANNED, TaskStatus.BLOCKED, TaskStatus.CANCELLED],
    TaskStatus.PLANNED: [TaskStatus.READY, TaskStatus.BLOCKED, TaskStatus.CANCELLED],
    TaskStatus.READY: [TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.CANCELLED],
    TaskStatus.IN_PROGRESS: [TaskStatus.VERIFYING, TaskStatus.BLOCKED, TaskStatus.CANCELLED],
    TaskStatus.VERIFYING: [TaskStatus.READY_FOR_RELEASE, TaskStatus.BLOCKED, TaskStatus.CANCELLED],
    TaskStatus.READY_FOR_RELEASE: [TaskStatus.AWAITING_APPROVAL, TaskStatus.BLOCKED, TaskStatus.CANCELLED],
    TaskStatus.AWAITING_APPROVAL: [TaskStatus.RELEASED, TaskStatus.BLOCKED, TaskStatus.CANCELLED],
    TaskStatus.RELEASED: [TaskStatus.CLOSED, TaskStatus.BLOCKED, TaskStatus.CANCELLED],
    TaskStatus.BLOCKED: [TaskStatus.GROUNDED, TaskStatus.PLANNED, TaskStatus.READY, TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED],
    TaskStatus.CANCELLED: [TaskStatus.CANCELLED],
    TaskStatus.CLOSED: [TaskStatus.CLOSED],
}


@dataclass
class TaskRecord:
    task_id: str
    owner: str
    objective: str
    status: TaskStatus = TaskStatus.INTAKE
    scope: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    required_skills: List[str] = field(default_factory=list)
    repo: str = ""
    branch: str = ""
    risk_level: str = "LOW"
    approval_action: str = "release"
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)


class TaskStateMachine:
    """State machine with verification and approval gates on release transitions."""

    @staticmethod
    def can_transition(current: TaskStatus, new_state: TaskStatus) -> bool:
        if current == new_state:
            return True
        return new_state in VALID_TRANSITIONS.get(current, [])

    @staticmethod
    def transition(
        task: TaskRecord,
        new_state: TaskStatus,
        *,
        evidence_registry: Optional[Any] = None,
        approval_gate: Optional[Any] = None,
        approval_scope: Optional[str] = None,
        justification: Optional[str] = None,
    ) -> None:
        if not isinstance(new_state, TaskStatus):
            raise ValueError(f"Unknown task state: {new_state!r}")
        if task.status == new_state:
            return
        if not TaskStateMachine.can_transition(task.status, new_state):
            raise ValueError(
                f"Invalid transition from {task.status.value} to {new_state.value} for task {task.task_id}"
            )

        if task.status == TaskStatus.BLOCKED and new_state != TaskStatus.CANCELLED:
            if not justification or not justification.strip():
                raise ValueError("A blocked task requires an explicit unblock justification")

        if new_state == TaskStatus.READY_FOR_RELEASE:
            if not task.evidence:
                raise ValueError("Evidence references are required before release readiness")
            if evidence_registry is None or not evidence_registry.is_verified(task.task_id):
                raise ValueError("Verified evidence is required before release readiness")
            verified_titles = {
                item.title for item in evidence_registry.get(task.task_id)
                if getattr(item.status, "value", item.status) == "VERIFIED"
            }
            if not set(task.evidence).issubset(verified_titles):
                raise ValueError("Task evidence references must match verified evidence records")

        if new_state == TaskStatus.AWAITING_APPROVAL:
            if approval_gate is None or not approval_scope:
                raise ValueError("A matching pending approval request and target scope are required")
            if not approval_gate.is_pending(
                task.task_id,
                task.approval_action or "release",
                approval_scope,
                list(task.evidence),
            ):
                raise ValueError("Awaiting approval requires a pending release request matching scope and evidence")

        if new_state == TaskStatus.RELEASED:
            if approval_gate is None or not approval_scope:
                raise ValueError("An explicit approval gate and target scope are required for release")
            if not approval_gate.can_proceed(
                task.task_id,
                task.approval_action or "release",
                evidence=list(task.evidence),
                scope=approval_scope,
            ):
                raise ValueError("Release is blocked: matching, current approval and evidence are required")

        task.status = new_state
        task.updated_at = _utc_now()

    @staticmethod
    def add_blocker(task: TaskRecord, blocker: str) -> None:
        if task.status in {TaskStatus.CLOSED, TaskStatus.CANCELLED}:
            raise ValueError(f"Cannot block terminal task {task.task_id} in state {task.status.value}")
        if blocker not in task.blockers:
            task.blockers.append(blocker)
        task.status = TaskStatus.BLOCKED
        task.updated_at = _utc_now()

    @staticmethod
    def add_evidence(task: TaskRecord, evidence_item: str) -> None:
        if evidence_item not in task.evidence:
            task.evidence.append(evidence_item)
            task.updated_at = _utc_now()
