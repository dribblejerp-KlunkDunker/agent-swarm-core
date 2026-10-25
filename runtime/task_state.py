from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


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
    created_at: str = ""
    updated_at: str = ""


class TaskStateMachine:
    """Small explicit state machine for swarm task progression."""

    @staticmethod
    def can_transition(current: TaskStatus, new_state: TaskStatus) -> bool:
        if current == new_state:
            return True
        return new_state in VALID_TRANSITIONS.get(current, [])

    @staticmethod
    def transition(task: TaskRecord, new_state: TaskStatus) -> None:
        if not TaskStateMachine.can_transition(task.status, new_state):
            raise ValueError(
                f"Invalid transition from {task.status.value} to {new_state.value} for task {task.task_id}"
            )
        task.status = new_state
        task.updated_at = "runtime"

    @staticmethod
    def add_blocker(task: TaskRecord, blocker: str) -> None:
        if blocker not in task.blockers:
            task.blockers.append(blocker)
        task.status = TaskStatus.BLOCKED

    @staticmethod
    def add_evidence(task: TaskRecord, evidence_item: str) -> None:
        if evidence_item not in task.evidence:
            task.evidence.append(evidence_item)
