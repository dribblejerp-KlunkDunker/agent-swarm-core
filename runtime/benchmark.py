from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Sequence, Optional

from .evidence import EvidenceBundle, EvidenceRegistry
from .storage import SQLiteStateStore
from .task_state import TaskRecord, TaskStatus


@dataclass
class BenchmarkResult:
    task_id: str
    architecture_score: int
    safety_score: int
    evidence_score: int
    benchmark_score: int
    total: int


class BenchmarkRunner:
    """Scores runtime checks and gives evidence credit only for verified task evidence."""

    def __init__(
        self,
        state_store: Optional[SQLiteStateStore] = None,
        *,
        db_path: Optional[str] = None,
    ) -> None:
        self.registry = EvidenceRegistry(state_store=state_store, db_path=db_path)

    def run_core_task(self, task: TaskRecord) -> BenchmarkResult:
        architecture = 100
        safety = 100
        benchmark = 100
        evidence_verified = bool(task.evidence) and self.registry.is_verified(task.task_id)
        evidence = 100 if evidence_verified else 0

        if task.status == TaskStatus.BLOCKED:
            architecture = 80
            safety = 85
            benchmark = 75
        if task.status == TaskStatus.CANCELLED:
            architecture = 75
            safety = 80
            benchmark = 70
        if task.status in {
            TaskStatus.READY_FOR_RELEASE,
            TaskStatus.AWAITING_APPROVAL,
            TaskStatus.RELEASED,
            TaskStatus.CLOSED,
        } and not evidence_verified:
            safety = 0
            benchmark = 0

        total = int((architecture + safety + evidence + benchmark) / 4)
        return BenchmarkResult(
            task_id=task.task_id,
            architecture_score=architecture,
            safety_score=safety,
            evidence_score=evidence,
            benchmark_score=benchmark,
            total=total,
        )

    def add_evidence(self, task_id: str, evidence_item: EvidenceBundle) -> None:
        if task_id != evidence_item.task_id:
            raise ValueError("Evidence task_id must match the task_id passed to add_evidence")
        self.registry.add(evidence_item)

    def verify(self, task_id: str) -> bool:
        return self.registry.is_verified(task_id)

    def verify_consistency(self, tasks: Sequence[TaskRecord]) -> bool:
        results = [self.run_core_task(task) for task in tasks]
        for result in results:
            component_scores = (
                result.architecture_score,
                result.safety_score,
                result.evidence_score,
                result.benchmark_score,
            )
            if not all(0 <= score <= 100 for score in component_scores):
                return False
            if result.total != int(sum(component_scores) / 4):
                return False
        return len(results) == len(tasks)

    def score_summary(self, tasks: Sequence[TaskRecord]) -> Dict[str, int]:
        results = [self.run_core_task(task) for task in tasks]
        return {
            "average_total": int(sum(item.total for item in results) / max(1, len(results))),
            "best_total": max(item.total for item in results) if results else 0,
            "worst_total": min(item.total for item in results) if results else 0,
        }
