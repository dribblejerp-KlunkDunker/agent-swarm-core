from __future__ import annotations

import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List
from unittest.mock import patch

from .approval import ApprovalGate, ReleaseGate
from .benchmark import BenchmarkRunner
from .evidence import EvidenceBundle, EvidenceRegistry, EvidenceStatus
from .locks import LockRegistry
from .task_board import TaskBoard
from .task_state import TaskRecord, TaskStateMachine, TaskStatus
from .services import RuntimeServices
from .storage import SQLiteStateStore

# Fixed, obviously-test-only key for exercising the keyed audit chain.
_VALIDATION_AUDIT_KEY = "validation-only-audit-key-not-for-production-use"


@dataclass
class ValidationResult:
    name: str
    passed: bool
    details: List[str] = field(default_factory=list)


def validate_invalid_transitions() -> ValidationResult:
    task = TaskRecord(task_id="task-1", owner="owner-a", objective="invalid transition")
    try:
        TaskStateMachine.transition(task, TaskStatus.RELEASED)
    except ValueError:
        return ValidationResult(
            name="invalid_transitions",
            passed=True,
            details=["INTAKE -> RELEASED is rejected as invalid"],
        )
    return ValidationResult(
        name="invalid_transitions",
        passed=False,
        details=["INTAKE -> RELEASED unexpectedly succeeded"],
    )


def validate_lock_conflicts() -> ValidationResult:
    registry = LockRegistry()
    first = registry.reserve("src/", "task-a", "owner-a", "directory edit")
    same_owner_child = registry.reserve("src/module.py", "task-a", "owner-a", "specific file edit")
    conflicting_task = registry.reserve("src/module.py", "task-b", "owner-b", "overlapping edit")
    sibling_prefix = registry.reserve("src-old/file.py", "task-c", "owner-c", "independent path")
    wrong_owner_release = registry.release("src", "task-b", "owner-b")
    correct_release = registry.release("src", "task-a", "owner-a")
    passed = first and same_owner_child and not conflicting_task and sibling_prefix and not wrong_owner_release and correct_release
    return ValidationResult(
        name="lock_conflicts",
        passed=passed,
        details=[
            f"first_reserve={first}",
            f"same_owner_child={same_owner_child}",
            f"conflicting_task={conflicting_task}",
            f"sibling_prefix={sibling_prefix}",
            f"wrong_owner_release={wrong_owner_release}",
            f"correct_release={correct_release}",
        ],
    )


def validate_evidence_required_completion() -> ValidationResult:
    registry = EvidenceRegistry()
    task_id = "task-evidence"
    registry.add(EvidenceBundle(task_id=task_id, title="build log", content="successful build"))
    before_verification = registry.is_verified(task_id)
    registry.mark_verified(task_id)
    after_verification = registry.is_verified(task_id)

    rejected_registry = EvidenceRegistry()
    rejected_registry.add(EvidenceBundle(task_id="rejected-evidence", title="claim", content="disputed"))
    rejected_registry.mark_rejected("rejected-evidence")
    rejected_registry.mark_verified("rejected-evidence")
    rejected_remains_rejected = (
        rejected_registry.get("rejected-evidence")[0].status == EvidenceStatus.REJECTED
        and not rejected_registry.is_verified("rejected-evidence")
    )
    return ValidationResult(
        name="evidence_required_completion",
        passed=(not before_verification) and after_verification and rejected_remains_rejected,
        details=[
            f"before_verification={before_verification}",
            f"after_verification={after_verification}",
            f"rejected_evidence_stays_rejected={rejected_remains_rejected}",
        ],
    )


def validate_approval_required_irreversible_actions() -> ValidationResult:
    gate = ApprovalGate()
    evidence = ["release checklist", "verification report"]
    gate.request("task-approve", "deploy", "production", "approver-a", evidence=evidence)
    allowed_while_pending = gate.can_proceed("task-approve", "deploy", evidence=evidence, scope="production")
    approved = gate.approve("task-approve", approver="approver-a", evidence=evidence)
    allowed_after_approval = gate.can_proceed("task-approve", "deployment", evidence=evidence, scope="production")
    wrong_scope_allowed = gate.can_proceed("task-approve", "deploy", evidence=evidence, scope="staging")
    wrong_action_allowed = gate.can_proceed("task-approve", "publish", evidence=evidence, scope="production")
    changed_evidence_allowed = gate.can_proceed(
        "task-approve",
        "deploy",
        evidence=["release checklist", "different report"],
        scope="production",
    )

    no_evidence_gate = ApprovalGate()
    no_evidence_gate.request("task-no-evidence", "release", "production", "approver-b", evidence=[])
    empty_evidence_approved = no_evidence_gate.approve(
        "task-no-evidence", approver="approver-b", evidence=[]
    )

    history_preserved = len(gate.history("task-approve")) == 1
    passed = (
        not allowed_while_pending
        and approved
        and allowed_after_approval
        and not wrong_scope_allowed
        and not wrong_action_allowed
        and not changed_evidence_allowed
        and not empty_evidence_approved
        and history_preserved
    )
    return ValidationResult(
        name="approval_required_irreversible_actions",
        passed=passed,
        details=[
            f"pending_request_allowed={allowed_while_pending}",
            f"explicit_approval_granted={approved}",
            f"approved_action_allowed={allowed_after_approval}",
            f"wrong_scope_allowed={wrong_scope_allowed}",
            f"wrong_action_allowed={wrong_action_allowed}",
            f"changed_evidence_allowed={changed_evidence_allowed}",
            f"empty_evidence_approved={empty_evidence_approved}",
            f"history_preserved={history_preserved}",
        ],
    )


def validate_resume_recovery() -> ValidationResult:
    with TemporaryDirectory(prefix="swarm-board-validation-") as temporary_dir:
        board_path = Path(temporary_dir) / "TASK_BOARD_VALIDATE.json"
        board = TaskBoard(board_path=str(board_path))
        task = TaskRecord(
            task_id="resume-task",
            owner="owner-a",
            objective="recover state",
            status=TaskStatus.BLOCKED,
        )
        task.blockers = ["missing dependency"]
        task.evidence = ["partial evidence"]
        board.add_or_update(task)
        recovered = board.get("resume-task")
        passed = (
            recovered is not None
            and recovered.status == TaskStatus.BLOCKED.value
            and recovered.blockers == ["missing dependency"]
            and recovered.evidence == ["partial evidence"]
        )
    path_removed = not board_path.exists()
    return ValidationResult(
        name="resume_recovery",
        passed=passed and path_removed,
        details=[
            f"recovered={recovered is not None}",
            f"status={recovered.status if recovered else None}",
            f"temporary_board_removed={path_removed}",
        ],
    )


def verify_benchmark_consistency() -> ValidationResult:
    runner = BenchmarkRunner()
    tasks = [
        TaskRecord(task_id="bench-ok", owner="owner-a", objective="normal goal", status=TaskStatus.READY),
        TaskRecord(task_id="bench-blocked", owner="owner-b", objective="blocked goal", status=TaskStatus.BLOCKED),
        TaskRecord(task_id="bench-cancelled", owner="owner-c", objective="cancelled", status=TaskStatus.CANCELLED),
    ]
    results = {task.task_id: runner.run_core_task(task) for task in tasks}
    totals = [result.total for result in results.values()]
    passed = (
        all(0 <= total <= 100 for total in totals)
        and results["bench-ok"].total >= results["bench-blocked"].total >= results["bench-cancelled"].total
        and runner.verify_consistency(tasks)
    )
    return ValidationResult(
        name="benchmark_consistency",
        passed=passed,
        details=[f"totals={totals}", f"component_scores_consistent={runner.verify_consistency(tasks)}"],
    )


def finalize_release_gate() -> ValidationResult:
    gate = ReleaseGate()
    evidence = ["test pass", "deployment review"]
    gate.request("release-1", "release", "production", "approver-a", evidence=evidence)
    blocked_while_pending = not gate.can_release("release-1", evidence=evidence, scope="production")
    explicit_approval = gate.approve("release-1", approver="approver-a", evidence=evidence)
    allowed_after_approval = gate.can_release("release-1", evidence=evidence, scope="production")

    no_evidence_gate = ReleaseGate()
    no_evidence_gate.request("release-2", "release", "production", "approver-b", evidence=[])
    empty_evidence_blocked = not no_evidence_gate.approve(
        "release-2", approver="approver-b", evidence=[]
    )
    passed = blocked_while_pending and explicit_approval and allowed_after_approval and empty_evidence_blocked
    return ValidationResult(
        name="release_gate",
        passed=passed,
        details=[
            f"blocked_while_pending={blocked_while_pending}",
            f"explicit_approval={explicit_approval}",
            f"allowed_after_approval={allowed_after_approval}",
            f"empty_evidence_blocked={empty_evidence_blocked}",
        ],
    )


def validate_durable_state() -> ValidationResult:
    with TemporaryDirectory(prefix="swarm-state-validation-") as temporary_dir:
        db_path = str(Path(temporary_dir) / "state.sqlite3")
        store = SQLiteStateStore(db_path)
        store.append_event("audit.validation", task_id="storage-validation", payload={"check": "chain"})
        chain = store.verify_audit_chain()
        store.put_task_json(
            "persisted",
            '{"task_id":"persisted","owner":"owner","objective":"persist","status":"BLOCKED","scope":[],"blockers":["dependency"],"evidence":[],"repo":"","updated_at":"now"}',
            "now",
            actor="owner",
        )
        store2 = SQLiteStateStore(db_path)
        restored = store2.get_task_json("persisted")
        passed = chain["valid"] and chain["events"] == 1 and restored is not None
    return ValidationResult(
        name="durable_state_and_audit",
        passed=passed,
        details=[
            f"audit_chain_valid={chain['valid']}",
            f"audit_events={chain['events']}",
            f"task_survived_reopen={restored is not None}",
        ],
    )


def validate_unblock_cannot_skip_stages() -> ValidationResult:
    task = TaskRecord(task_id="unblock", owner="owner-a", objective="no stage skipping")
    TaskStateMachine.add_blocker(task, "missing dependency")
    try:
        TaskStateMachine.transition(task, TaskStatus.IN_PROGRESS, justification="dependency restored")
        skipped = True
    except ValueError:
        skipped = False
    TaskStateMachine.transition(task, TaskStatus.INTAKE, justification="dependency restored")
    resumed_at_origin = task.status == TaskStatus.INTAKE and task.blockers == [] and task.blocked_from == ""
    return ValidationResult(
        name="unblock_cannot_skip_stages",
        passed=not skipped and resumed_at_origin,
        details=[f"intake_to_in_progress_via_block={skipped}", f"resumed_at_origin={resumed_at_origin}"],
    )


def validate_compound_actions_and_separation_of_duties() -> ValidationResult:
    gate = ApprovalGate()
    evidence = ["review"]
    gate.request("compound", "merge", "main", "approver-a", evidence=evidence, requester="worker")
    gate.approve("compound", approver="approver-a", evidence=evidence)
    merge_allowed = gate.can_proceed("compound", "merge", evidence=evidence, scope="main")
    smuggled = [
        action for action in ("merge-and-deploy-to-production", "merge then delete prod db", "merge --force")
        if gate.can_proceed("compound", action, evidence=evidence, scope="main")
    ]
    try:
        gate.request("self", "deploy", "production", "worker", evidence=evidence, requester="worker")
        self_request_accepted = True
    except ValueError:
        self_request_accepted = False
    return ValidationResult(
        name="compound_actions_and_separation_of_duties",
        passed=merge_allowed and not smuggled and not self_request_accepted,
        details=[
            f"approved_merge_allowed={merge_allowed}",
            f"smuggled_actions_allowed={smuggled}",
            f"self_approval_request_accepted={self_request_accepted}",
        ],
    )


def validate_production_lifecycle() -> ValidationResult:
    """Drive one task through the whole production gate against a real database file."""
    with TemporaryDirectory(prefix="swarm-production-validation-") as temporary_dir:
        db_path = str(Path(temporary_dir) / "state.sqlite3")
        env = {"SWARM_ENV": "production", "SWARM_STATE_DB": db_path, "SWARM_AUDIT_KEY": _VALIDATION_AUDIT_KEY}
        with patch.dict(os.environ, env):
            services = RuntimeServices(
                db_path=db_path,
                approver_authorizer=lambda actor, record: actor == record.approver == "idp:release-approver",
                evidence_authorizer=lambda actor, bundle: actor == "idp:reviewer",
            )
            task = TaskRecord(task_id="prod-lifecycle", owner="agent:worker", objective="validated deploy",
                              approval_action="deploy")
            services.create_task(task)
            services.transition_task(task, TaskStatus.GROUNDED)
            services.add_blocker(task, "waiting on fixture")
            services.transition_task(task, TaskStatus.GROUNDED, justification="fixture restored")
            for status in (TaskStatus.PLANNED, TaskStatus.READY, TaskStatus.IN_PROGRESS, TaskStatus.VERIFYING):
                services.transition_task(task, status)
            lease_refused = False
            try:
                services.locks.reserve("src", task.task_id, task.owner, "edit", lease_seconds=None)
            except ValueError:
                lease_refused = True
            services.add_evidence_reference(task, "test-log")
            services.evidence.add(EvidenceBundle(task_id=task.task_id, title="test-log", content="all tests passed"))
            services.evidence.mark_verified(task.task_id, verifier="idp:reviewer")
            services.transition_task(task, TaskStatus.READY_FOR_RELEASE)
            services.request_approval(task, scope="production", approver="idp:release-approver")
            services.transition_task(task, TaskStatus.AWAITING_APPROVAL, approval_scope="production")
            owner_approved = services.approvals.approve(task.task_id, approver=task.owner, evidence=task.evidence)
            approved = services.approvals.approve(task.task_id, approver="idp:release-approver", evidence=task.evidence)
            allowed = services.can_perform_action(task.task_id, "deploy", scope="production", evidence=task.evidence)
            services.transition_task(task, TaskStatus.RELEASED, approval_scope="production")
            anchor = services.store.audit_checkpoint()
            health = services.health_check(audit_anchor=anchor)
        passed = (
            lease_refused and not owner_approved and approved and allowed
            and task.status == TaskStatus.RELEASED and health.ready and anchor["sequence"] > 0
        )
        return ValidationResult(
            name="production_lifecycle",
            passed=passed,
            details=[
                f"permanent_lock_refused={lease_refused}",
                f"owner_self_approval={owner_approved}",
                f"approver_granted={approved}",
                f"deploy_allowed={allowed}",
                f"final_status={task.status.value}",
                f"health_ready={health.ready}",
                f"audit_events={anchor['sequence']}",
            ],
        )


def validate_audit_tamper_detection() -> ValidationResult:
    """Rewrite a keyed history without the key, and truncate it; both must be detected."""
    with TemporaryDirectory(prefix="swarm-audit-validation-") as temporary_dir:
        db_path = str(Path(temporary_dir) / "audit.sqlite3")
        store = SQLiteStateStore(db_path, audit_key=_VALIDATION_AUDIT_KEY)
        for index in range(3):
            store.append_event("audit.validation", task_id="audit", payload={"index": index})
        anchor = store.audit_checkpoint()
        intact = store.verify_audit_chain(anchor=anchor)["valid"]

        connection = sqlite3.connect(db_path)
        connection.execute("DROP TRIGGER audit_events_no_update")
        connection.execute("DROP TRIGGER audit_events_no_delete")
        connection.execute("DELETE FROM audit_events WHERE sequence = 3")
        connection.commit()
        connection.close()
        truncation_detected = not store.verify_audit_chain(anchor=anchor)["valid"]

        # An attacker without the key recomputes the whole chain with plain SHA-256.
        forger = SQLiteStateStore(str(Path(temporary_dir) / "forged.sqlite3"))
        forger.append_event("audit.validation", task_id="audit", payload={"index": "forged"})
        forged_row = forger.list_events()[0]
        connection = sqlite3.connect(db_path)
        connection.execute("DELETE FROM audit_events")
        connection.execute(
            "INSERT INTO audit_events(sequence, timestamp, event_type, task_id, actor, payload_json, previous_hash, event_hash) "
            "VALUES(1, ?, ?, ?, ?, ?, 'GENESIS', ?)",
            (forged_row["timestamp"], forged_row["event_type"], forged_row["task_id"], forged_row["actor"],
             '{"index":"forged"}', forged_row["event_hash"]),
        )
        connection.commit()
        connection.close()
        rewrite_detected = not store.verify_audit_chain()["valid"]
    return ValidationResult(
        name="audit_tamper_detection",
        passed=intact and truncation_detected and rewrite_detected,
        details=[
            f"intact_chain_valid={intact}",
            f"truncation_detected_by_anchor={truncation_detected}",
            f"unkeyed_rewrite_detected={rewrite_detected}",
        ],
    )


# Configuration that would point the checks at a real deployment's database or identity layer.
_RUNTIME_ENV_KEYS = ("SWARM_ENV", "SWARM_STATE_DB", "SWARM_AUDIT_KEY", "SWARM_AUTHORIZER_MODULE")


def run_full_validation() -> List[ValidationResult]:
    """Run every check in isolation: never against SWARM_STATE_DB or under the caller's SWARM_ENV."""
    with patch.dict(os.environ):
        for key in _RUNTIME_ENV_KEYS:
            os.environ.pop(key, None)
        return _run_checks()


def _run_checks() -> List[ValidationResult]:
    return [
        validate_invalid_transitions(),
        validate_lock_conflicts(),
        validate_evidence_required_completion(),
        validate_approval_required_irreversible_actions(),
        validate_resume_recovery(),
        verify_benchmark_consistency(),
        finalize_release_gate(),
        validate_durable_state(),
        validate_unblock_cannot_skip_stages(),
        validate_compound_actions_and_separation_of_duties(),
        validate_production_lifecycle(),
        validate_audit_tamper_detection(),
    ]


def main() -> int:
    results = run_full_validation()
    for result in results:
        print(f"{'PASS' if result.passed else 'FAIL'}: {result.name}")
        for detail in result.details:
            print(f"  - {detail}")
    failures = [result.name for result in results if not result.passed]
    if failures:
        print(f"Runtime audit failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    print(f"Runtime audit passed: {len(results)} checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
