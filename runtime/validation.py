from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .approval import ApprovalGate, ReleaseGate
from .benchmark import BenchmarkRunner
from .evidence import EvidenceBundle, EvidenceRegistry, EvidenceStatus
from .locks import LockRegistry
from .task_board import TaskBoard
from .task_state import TaskRecord, TaskStateMachine, TaskStatus


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
    ok = registry.reserve("repo:alpha", "task-a", "owner-a", "analysis")
    second = registry.reserve("repo:alpha", "task-b", "owner-b", "analysis")
    release_ok = registry.release("repo:alpha", "task-a")
    details = [
        f"first_reserve={ok}",
        f"second_reserve={second}",
        f"release_ok={release_ok}",
    ]
    return ValidationResult(
        name="lock_conflicts",
        passed=ok and (not second) and release_ok,
        details=details,
    )


def validate_evidence_required_completion() -> ValidationResult:
    registry = EvidenceRegistry()
    task_id = "task-evidence"
    bundle = EvidenceBundle(task_id=task_id, title="build log", content="successful build")
    registry.add(bundle)
    verified = registry.is_verified(task_id)
    registry.mark_verified(task_id)
    verified_after = registry.is_verified(task_id)
    return ValidationResult(
        name="evidence_required_completion",
        passed=(not verified) and verified_after,
        details=[
            f"before_verification={verified}",
            f"after_verification={verified_after}",
        ],
    )


def validate_approval_required_irreversible_actions() -> ValidationResult:
    gate = ApprovalGate()
    gate.request("task-approve", "deploy", "production", "approver-a", evidence=[])
    allowed = gate.can_proceed("task-approve", "deploy", evidence=[])
    gate.request("task-approve-2", "release", "production", "approver-b", evidence=["release checklist", "verification report"])
    allowed_with_evidence = gate.can_proceed("task-approve-2", "release", evidence=["release checklist", "verification report"])
    return ValidationResult(
        name="approval_required_irreversible_actions",
        passed=(not allowed) and allowed_with_evidence,
        details=[
            f"without_evidence_allowed={allowed}",
            f"with_evidence_allowed={allowed_with_evidence}",
        ],
    )


def validate_resume_recovery() -> ValidationResult:
    board = TaskBoard(board_path=".agent/TASK_BOARD_VALIDATE.json")
    task = TaskRecord(task_id="resume-task", owner="owner-a", objective="recover state", status=TaskStatus.BLOCKED)
    task.blockers = ["missing dependency"]
    task.evidence = ["partial evidence"]
    board.add_or_update(task)
    recovered = board.get("resume-task")
    passed = recovered is not None and recovered.status == TaskStatus.BLOCKED.value and recovered.blockers == ["missing dependency"]
    return ValidationResult(
        name="resume_recovery",
        passed=passed,
        details=[f"recovered={recovered is not None}", f"status={recovered.status if recovered else None}"],
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
    passed = all(0 <= total <= 100 for total in totals) and results["bench-ok"].total >= results["bench-blocked"].total >= results["bench-cancelled"].total
    return ValidationResult(
        name="benchmark_consistency",
        passed=passed,
        details=[f"totals={totals}"],
    )


def finalize_release_gate() -> ValidationResult:
    gate = ReleaseGate()
    gate.request("release-1", "release", "production", "approver-a", evidence=[])
    blocked = gate.can_proceed("release-1", "release", evidence=[])
    gate.request("release-2", "release", "production", "approver-b", evidence=["test pass", "deployment review"])
    allowed = gate.can_proceed("release-2", "release", evidence=["test pass", "deployment review"])
    return ValidationResult(
        name="release_gate",
        passed=(not blocked) and allowed,
        details=[f"blocked={blocked}", f"allowed={allowed}"],
    )


def run_full_validation() -> List[ValidationResult]:
    return [
        validate_invalid_transitions(),
        validate_lock_conflicts(),
        validate_evidence_required_completion(),
        validate_approval_required_irreversible_actions(),
        validate_resume_recovery(),
        verify_benchmark_consistency(),
        finalize_release_gate(),
    ]
