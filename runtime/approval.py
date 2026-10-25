from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .storage import SQLiteStateStore, utc_now


def _canonical_action(action: str) -> str:
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


def _evidence_digest(evidence: List[str]) -> str:
    canonical = json.dumps(sorted(evidence), separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _is_production() -> bool:
    return os.environ.get("SWARM_ENV", "").strip().lower() in {"prod", "production"}


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
    expires_at: str = ""
    approved_at: str = ""
    approval_event_hash: str = ""


ApprovalAuthorizer = Callable[[str, "ApprovalRecord"], bool]


def _serialize_record(record: ApprovalRecord) -> str:
    payload = asdict(record)
    payload["status"] = record.status.value
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _deserialize_record(payload: str) -> ApprovalRecord:
    data: Dict[str, Any] = json.loads(payload)
    data["status"] = ApprovalStatus(data["status"])
    data["evidence"] = list(data.get("evidence", []))
    data.setdefault("expires_at", "")
    data.setdefault("approved_at", "")
    data.setdefault("approval_event_hash", "")
    return ApprovalRecord(**data)


class ApprovalGate:
    """Durable approval decisions bound to an authenticated actor, action, scope, evidence and expiry."""

    IRREVERSIBLE_ACTIONS = {
        "merge", "publish", "deploy", "release", "migration",
        "secret-rotation", "credential-rotation", "destructive-action",
        "external-write", "environment-mutation", "production-change",
    }
    SAFE_ACTIONS = {
        "read", "inspect", "analyze", "test", "build", "lint", "format", "plan",
        "draft", "validate", "verify", "review", "search", "fetch", "list",
        "ground", "implement", "edit", "create", "compile", "benchmark",
    }

    def __init__(
        self,
        state_store: Optional[SQLiteStateStore] = None,
        *,
        db_path: Optional[str] = None,
        approver_authorizer: Optional[ApprovalAuthorizer] = None,
        approval_ttl_seconds: int = 900,
    ) -> None:
        if state_store is not None and db_path is not None:
            raise ValueError("Pass state_store or db_path, not both")
        if approval_ttl_seconds < 1 or approval_ttl_seconds > 604800:
            raise ValueError("approval_ttl_seconds must be between 1 second and 7 days")
        self.store = state_store or SQLiteStateStore(db_path)
        if _is_production() and not self.store.persistent:
            raise RuntimeError("A durable SWARM_STATE_DB is required for production approvals")
        self.approver_authorizer = approver_authorizer
        self.approval_ttl_seconds = approval_ttl_seconds

    @staticmethod
    def _is_expired(record: ApprovalRecord) -> bool:
        return bool(record.expires_at and _parse_time(record.expires_at) <= datetime.now(timezone.utc))

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
        evidence_copy = list(evidence or [])
        if not all((task_id, action, scope, approver)):
            raise ValueError("task_id, action, scope, and approver must be non-empty")
        if any(not isinstance(item, str) or not item.strip() for item in evidence_copy):
            raise ValueError("evidence references must be non-empty strings")
        created = datetime.now(timezone.utc)
        record = ApprovalRecord(
            task_id=task_id,
            action=action,
            scope=scope,
            approver=approver,
            evidence=evidence_copy,
            notes=notes,
            timestamp=created.isoformat(timespec="microseconds"),
            expires_at=(created + timedelta(seconds=self.approval_ttl_seconds)).isoformat(timespec="microseconds"),
        )
        serialized = _serialize_record(record)
        with self.store.transaction() as connection:
            previous = connection.execute("SELECT record_json FROM approvals WHERE task_id=?", (task_id,)).fetchone()
            if previous:
                connection.execute(
                    "INSERT INTO approval_history(task_id, record_json, archived_at) VALUES(?, ?, ?)",
                    (task_id, previous["record_json"], utc_now()),
                )
            connection.execute(
                """
                INSERT INTO approvals(task_id, record_json) VALUES(?, ?)
                ON CONFLICT(task_id) DO UPDATE SET record_json=excluded.record_json
                """,
                (task_id, serialized),
            )
            self.store.append_event_in_transaction(
                connection, "approval.requested", task_id=task_id,
                payload={
                    "action": _canonical_action(action),
                    "scope": scope,
                    "requested_approver": approver,
                    "evidence_sha256": _evidence_digest(evidence_copy),
                    "expires_at": record.expires_at,
                },
            )
        return _deserialize_record(serialized)

    def approve(
        self,
        task_id: str,
        approver: Optional[str] = None,
        evidence: Optional[List[str]] = None,
    ) -> bool:
        attempted_actor = (approver or "").strip() or None
        with self.store.transaction() as connection:
            row = connection.execute("SELECT record_json FROM approvals WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                self.store.append_event_in_transaction(
                    connection, "approval.denied", task_id=task_id, actor=attempted_actor,
                    payload={"reason": "request_not_found"},
                )
                return False
            record = _deserialize_record(row["record_json"])
            if record.status != ApprovalStatus.PENDING:
                self.store.append_event_in_transaction(
                    connection, "approval.denied", task_id=task_id, actor=attempted_actor,
                    payload={"reason": "request_not_pending", "status": record.status.value},
                )
                return False
            if self._is_expired(record):
                record.status = ApprovalStatus.BLOCKED
                record.notes = (record.notes + " Approval request expired; submit a new request.").strip()
                connection.execute("UPDATE approvals SET record_json=? WHERE task_id=?", (_serialize_record(record), task_id))
                self.store.append_event_in_transaction(
                    connection, "approval.expired", task_id=task_id, actor=attempted_actor,
                    payload={"action": _canonical_action(record.action), "scope": record.scope},
                )
                return False
            if attempted_actor is None or evidence is None:
                self.store.append_event_in_transaction(
                    connection, "approval.denied", task_id=task_id, actor=attempted_actor,
                    payload={"reason": "explicit_actor_and_evidence_required"},
                )
                return False
            if attempted_actor != record.approver:
                self.store.append_event_in_transaction(
                    connection, "approval.denied", task_id=task_id, actor=attempted_actor,
                    payload={"reason": "actor_mismatch"},
                )
                return False
            if not record.evidence or not evidence:
                record.status = ApprovalStatus.BLOCKED
                record.notes = (record.notes + " Evidence is required before approval.").strip()
                connection.execute("UPDATE approvals SET record_json=? WHERE task_id=?", (_serialize_record(record), task_id))
                self.store.append_event_in_transaction(
                    connection, "approval.denied", task_id=task_id, actor=attempted_actor,
                    payload={"reason": "evidence_required"},
                )
                return False
            if not _same_evidence(list(evidence), record.evidence):
                record.status = ApprovalStatus.BLOCKED
                record.notes = (record.notes + " Evidence changed; submit a fresh approval request.").strip()
                connection.execute("UPDATE approvals SET record_json=? WHERE task_id=?", (_serialize_record(record), task_id))
                self.store.append_event_in_transaction(
                    connection, "approval.denied", task_id=task_id, actor=attempted_actor,
                    payload={"reason": "evidence_mismatch"},
                )
                return False
            if _is_production() and self.approver_authorizer is None:
                self.store.append_event_in_transaction(
                    connection, "approval.denied", task_id=task_id, actor=attempted_actor,
                    payload={"reason": "production_identity_authorizer_not_configured"},
                )
                return False
            if self.approver_authorizer is not None:
                try:
                    authorized = bool(self.approver_authorizer(attempted_actor, record))
                except Exception:
                    authorized = False
                if not authorized:
                    self.store.append_event_in_transaction(
                        connection, "approval.denied", task_id=task_id, actor=attempted_actor,
                        payload={"reason": "identity_authorization_failed"},
                    )
                    return False

            approved_event = self.store.append_event_in_transaction(
                connection,
                "approval.granted",
                task_id=task_id,
                actor=attempted_actor,
                payload={
                    "action": _canonical_action(record.action),
                    "scope": record.scope,
                    "evidence_sha256": _evidence_digest(record.evidence),
                    "expires_at": record.expires_at,
                },
            )
            record.status = ApprovalStatus.APPROVED
            record.approved_at = approved_event["timestamp"]
            record.approval_event_hash = approved_event["event_hash"]
            connection.execute("UPDATE approvals SET record_json=? WHERE task_id=?", (_serialize_record(record), task_id))
            return True

    def reject(self, task_id: str, notes: str = "", approver: Optional[str] = None) -> bool:
        actor = (approver or "").strip() or None
        with self.store.transaction() as connection:
            row = connection.execute("SELECT record_json FROM approvals WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                self.store.append_event_in_transaction(
                    connection, "approval.rejection_denied", task_id=task_id, actor=actor,
                    payload={"reason": "request_not_found"},
                )
                return False
            record = _deserialize_record(row["record_json"])
            if record.status != ApprovalStatus.PENDING or actor is None or actor != record.approver:
                self.store.append_event_in_transaction(
                    connection, "approval.rejection_denied", task_id=task_id, actor=actor,
                    payload={"reason": "request_not_pending_or_actor_mismatch"},
                )
                return False
            if _is_production() and self.approver_authorizer is None:
                self.store.append_event_in_transaction(
                    connection, "approval.rejection_denied", task_id=task_id, actor=actor,
                    payload={"reason": "production_identity_authorizer_not_configured"},
                )
                return False
            if self.approver_authorizer is not None:
                try:
                    authorized = bool(self.approver_authorizer(actor, record))
                except Exception:
                    authorized = False
                if not authorized:
                    self.store.append_event_in_transaction(
                        connection, "approval.rejection_denied", task_id=task_id, actor=actor,
                        payload={"reason": "identity_authorization_failed"},
                    )
                    return False
            record.status = ApprovalStatus.REJECTED
            if notes:
                record.notes = (record.notes + " " + notes).strip()
            connection.execute("UPDATE approvals SET record_json=? WHERE task_id=?", (_serialize_record(record), task_id))
            self.store.append_event_in_transaction(
                connection, "approval.rejected", task_id=task_id, actor=actor,
                payload={"action": _canonical_action(record.action), "scope": record.scope, "reason": notes},
            )
            return True

    def get(self, task_id: str) -> Optional[ApprovalRecord]:
        serialized = self.store.get_approval_json(task_id)
        return _deserialize_record(serialized) if serialized else None

    def history(self, task_id: str) -> List[ApprovalRecord]:
        records = [_deserialize_record(item) for item in self.store.get_approval_history_json(task_id)]
        current = self.get(task_id)
        if current is not None:
            records.append(current)
        return records

    def is_pending(
        self,
        task_id: str,
        action: str,
        scope: str,
        evidence: List[str],
    ) -> bool:
        record = self.get(task_id)
        return bool(
            record is not None
            and record.status == ApprovalStatus.PENDING
            and not self._is_expired(record)
            and _canonical_action(record.action) == _canonical_action(action)
            and record.scope == scope
            and _same_evidence(evidence, record.evidence)
            and bool(record.evidence)
        )

    @classmethod
    def requires_approval(cls, action: str) -> bool:
        normalized = _canonical_action(action)
        if normalized in cls.IRREVERSIBLE_ACTIONS:
            return True
        return normalized not in cls.SAFE_ACTIONS

    def can_proceed(
        self,
        task_id: str,
        action: str,
        evidence: Optional[List[str]] = None,
        scope: Optional[str] = None,
    ) -> bool:
        if not self.requires_approval(action):
            self.store.append_event("action.checked_safe", task_id=task_id, payload={"action": _canonical_action(action)})
            return True

        with self.store.transaction() as connection:
            # A compromised or malformed audit chain must fail closed at the action boundary.
            chain = self.store.verify_audit_chain()
            if not chain["valid"]:
                return False

            row = connection.execute("SELECT record_json FROM approvals WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                self.store.append_event_in_transaction(
                    connection, "action.denied", task_id=task_id,
                    payload={"action": _canonical_action(action), "reason": "approval_request_missing"},
                )
                return False
            record = _deserialize_record(row["record_json"])
            reason: Optional[str] = None
            if record.status != ApprovalStatus.APPROVED:
                reason = "approval_not_granted"
            elif not record.approval_event_hash:
                reason = "approval_proof_missing"
            else:
                proof = connection.execute(
                    "SELECT event_type, task_id, actor, payload_json, timestamp FROM audit_events WHERE event_hash=?",
                    (record.approval_event_hash,),
                ).fetchone()
                if proof is None or proof["event_type"] != "approval.granted" or proof["task_id"] != task_id:
                    reason = "approval_proof_invalid"
                else:
                    try:
                        proof_payload = json.loads(proof["payload_json"])
                    except json.JSONDecodeError:
                        reason = "approval_proof_invalid"
                    else:
                        if (
                            proof["actor"] != record.approver
                            or proof["timestamp"] != record.approved_at
                            or proof_payload.get("action") != _canonical_action(record.action)
                            or proof_payload.get("scope") != record.scope
                            or proof_payload.get("evidence_sha256") != _evidence_digest(record.evidence)
                            or proof_payload.get("expires_at") != record.expires_at
                        ):
                            reason = "approval_proof_mismatch"
            if reason is None and self._is_expired(record):
                record.status = ApprovalStatus.BLOCKED
                record.notes = (record.notes + " Approval expired before action; a new approval is required.").strip()
                connection.execute("UPDATE approvals SET record_json=? WHERE task_id=?", (_serialize_record(record), task_id))
                reason = "approval_expired"
            elif reason is None and _canonical_action(record.action) != _canonical_action(action):
                reason = "action_mismatch"
            elif reason is None and (scope is None or scope.strip() != record.scope):
                reason = "scope_mismatch"
            elif reason is None and (evidence is None or not evidence):
                reason = "current_evidence_required"
            elif reason is None and not _same_evidence(list(evidence), record.evidence):
                record.status = ApprovalStatus.BLOCKED
                record.notes = (record.notes + " Evidence changed after approval; a new approval is required.").strip()
                connection.execute("UPDATE approvals SET record_json=? WHERE task_id=?", (_serialize_record(record), task_id))
                reason = "evidence_mismatch"

            if reason is None and _is_production() and not self.store.verify_task_status(task_id, "AWAITING_APPROVAL"):
                reason = "task_state_not_audited_awaiting_approval"
            if reason is None and _is_production() and not self.store.verify_evidence_state(task_id, list(evidence or [])):
                reason = "evidence_state_or_audit_mismatch"

            if reason:
                self.store.append_event_in_transaction(
                    connection, "action.denied", task_id=task_id,
                    payload={"action": _canonical_action(action), "scope": scope, "reason": reason},
                )
                return False
            self.store.append_event_in_transaction(
                connection, "action.allowed", task_id=task_id,
                payload={"action": _canonical_action(action), "scope": scope, "evidence_count": len(record.evidence)},
            )
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
