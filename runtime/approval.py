from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"


@dataclass
class ApprovalRecord:
    task_id: str
    action: str
    scope: str
    approver: str
    evidence: List[str] = field(default_factory=list)
    status: ApprovalStatus = ApprovalStatus.PENDING
    notes: str = ""
    timestamp: str = ""


class ApprovalGate:
    """Controls whether irreversible actions may proceed."""

    def __init__(self) -> None:
        self._records: Dict[str, ApprovalRecord] = {}

    def request(self, task_id: str, action: str, scope: str, approver: str, evidence: Optional[List[str]] = None, notes: str = "") -> ApprovalRecord:
        record = ApprovalRecord(
            task_id=task_id,
            action=action,
            scope=scope,
            approver=approver,
            evidence=evidence or [],
            notes=notes,
            timestamp="runtime",
        )
        self._records[task_id] = record
        return record

    def approve(self, task_id: str) -> bool:
        if task_id not in self._records:
            return False
        record = self._records[task_id]
        if not record.evidence:
            record.status = ApprovalStatus.BLOCKED
            return False
        record.status = ApprovalStatus.APPROVED
        return True

    def reject(self, task_id: str) -> bool:
        if task_id not in self._records:
            return False
        self._records[task_id].status = ApprovalStatus.REJECTED
        return True

    def get(self, task_id: str) -> Optional[ApprovalRecord]:
        return self._records.get(task_id)

    def requires_approval(self, action: str) -> bool:
        irreversible = {
            "merge",
            "publish",
            "deploy",
            "release",
            "migration",
            "secret-rotation",
            "destructive-action",
        }
        return action.lower() in irreversible

    def can_proceed(self, task_id: str, action: str, evidence: Optional[List[str]] = None) -> bool:
        if not self.requires_approval(action):
            return True
        record = self._records.get(task_id)
        if record is None:
            self.request(task_id, action, "runtime", "system", evidence or [])
            record = self._records[task_id]
        if evidence is not None:
            record.evidence = evidence
        return self.approve(task_id)


class ReleaseGate(ApprovalGate):
    """Final gate used before a release action is considered safe to proceed."""

    def can_release(self, task_id: str, evidence: Optional[List[str]] = None) -> bool:
        return self.can_proceed(task_id, "release", evidence=evidence)
