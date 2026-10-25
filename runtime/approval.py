from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_action(action: str) -> str:
    """Normalize common action aliases so wording cannot bypass a gate."""
    normalized = re.sub(r"[^a-z0-9]+", "-", (action or "").strip().lower()).strip("-")
    if not normalized:
        return ""

    tokens = set(normalized.split("-"))
    if "merge" in tokens:
        return "merge"
    if "deploy" in tokens or "deployment" in tokens:
        return "deploy"
    if "publish" in tokens:
        return "publish"
    if "release" in tokens:
        return "release"
    if "migration" in tokens or "migrate" in tokens:
        return "migration"
    if "secret" in tokens and tokens.intersection({"rotation", "rotate", "change", "update"}):
        return "secret-rotation"
    if "credential" in tokens and tokens.intersection({"rotation", "rotate", "change", "update"}):
        return "credential-rotation"
    if "destructive" in tokens or "destroy" in tokens or "delete" in tokens:
        return "destructive-action"
    if "external" in tokens and "write" in tokens:
        return "external-write"
    if "environment" in tokens and tokens.intersection({"mutation", "change", "update", "modify", "write"}):
        return "environment-mutation"
    if "production" in tokens and tokens.intersection({"change", "mutation", "update", "modify", "write"}):
        return "production-change"
    return normalized


def _same_evidence(left: List[str], right: List[str]) -> bool:
    return sorted(left) == sorted(right)


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
    approved_at: str = ""


class ApprovalGate:
    """Require explicit approval for risky actions and bind it to evidence and scope."""

    IRREVERSIBLE_ACTIONS = {
        "merge",
        "publish",
        "deploy",
        "release",
        "migration",
        "secret-rotation",
        "credential-rotation",
        "destructive-action",
        "external-write",
        "environment-mutation",
        "production-change",
    }

    def __init__(self) -> None:
        self._records: Dict[str, ApprovalRecord] = {}
        self._history: Dict[str, List[ApprovalRecord]] = {}

    def request(
        self,
        task_id: str,
        action: str,
        scope: str,
        approver: str,
        evidence: Optional[List[str]] = None,
        notes: str = "",
    ) -> ApprovalRecord:
        task_id = (task_id or "").strip()
        action = (action or "").strip()
        scope = (scope or "").strip()
        approver = (approver or "").strip()
        if not all((task_id, action, scope, approver)):
            raise ValueError("task_id, action, scope, and approver must be non-empty")
        if task_id in self._records:
            self._history.setdefault(task_id, []).append(copy.deepcopy(self._records[task_id]))

        record = ApprovalRecord(
            task_id=task_id,
            action=action,
            scope=scope,
            approver=approver,
            evidence=list(evidence or []),
            notes=notes,
            timestamp=_utc_now(),
        )
        self._records[task_id] = record
        return copy.deepcopy(record)

    def approve(
        self,
        task_id: str,
        approver: Optional[str] = None,
        evidence: Optional[List[str]] = None,
    ) -> bool:
        record = self._records.get(task_id)
        if record is None or record.status != ApprovalStatus.PENDING:
            return False
        # Missing actor/evidence must never be interpreted as approval by the requested reviewer.
        if approver is None or not approver.strip() or evidence is None:
            return False
        if approver.strip() != record.approver:
            return False
        if not record.evidence or not evidence:
            record.status = ApprovalStatus.BLOCKED
            record.notes = (record.notes + " Evidence is required before approval.").strip()
            return False
        if not _same_evidence(list(evidence), record.evidence):
            record.status = ApprovalStatus.BLOCKED
            record.notes = (record.notes + " Evidence changed; submit a fresh approval request.").strip()
            return False

        record.status = ApprovalStatus.APPROVED
        record.approved_at = _utc_now()
        return True

    def reject(self, task_id: str, notes: str = "") -> bool:
        record = self._records.get(task_id)
        if record is None or record.status != ApprovalStatus.PENDING:
            return False
        record.status = ApprovalStatus.REJECTED
        if notes:
            record.notes = (record.notes + " " + notes).strip()
        return True

    def get(self, task_id: str) -> Optional[ApprovalRecord]:
        record = self._records.get(task_id)
        return copy.deepcopy(record) if record is not None else None

    def history(self, task_id: str) -> List[ApprovalRecord]:
        """Return prior approval requests followed by the current record, if present."""
        prior = copy.deepcopy(self._history.get(task_id, []))
        current = self._records.get(task_id)
        if current is not None:
            prior.append(copy.deepcopy(current))
        return prior

    @classmethod
    def requires_approval(cls, action: str) -> bool:
        return _canonical_action(action) in cls.IRREVERSIBLE_ACTIONS

    def can_proceed(
        self,
        task_id: str,
        action: str,
        evidence: Optional[List[str]] = None,
        scope: Optional[str] = None,
    ) -> bool:
        """Check an existing approval; this method never creates or grants approval."""
        if not self.requires_approval(action):
            return True
        record = self._records.get(task_id)
        if record is None or record.status != ApprovalStatus.APPROVED:
            return False
        if _canonical_action(record.action) != _canonical_action(action):
            return False
        if scope is None or scope.strip() != record.scope:
            return False
        if evidence is None or not evidence:
            return False
        if not _same_evidence(list(evidence), record.evidence):
            record.status = ApprovalStatus.BLOCKED
            record.notes = (record.notes + " Evidence changed after approval; a new approval is required.").strip()
            return False
        return True


class ReleaseGate(ApprovalGate):
    """Final gate used before a release action is considered safe to proceed."""

    def can_release(
        self,
        task_id: str,
        evidence: Optional[List[str]] = None,
        scope: Optional[str] = None,
    ) -> bool:
        return self.can_proceed(task_id, "release", evidence=evidence, scope=scope)
