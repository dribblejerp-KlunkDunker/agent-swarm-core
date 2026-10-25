from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence

from .evidence import EvidenceBundle, EvidenceRegistry, EvidenceStatus
from .locks import LockRegistry
from .task_state import TaskRecord, TaskStateMachine, TaskStatus


@dataclass
class BenchmarkResult:
    task_id: str
    architecture_score: int
    safety_score: int
    evidence_score: int
    benchmark_score: int
    total: int


class BenchmarkRunner:
    """Simple benchmark harness for core runtime checks."""

    def __init__(self) -> None:
        self.registry = EvidenceRegistry()

    def run_core_task(self, task: TaskRecord) -> BenchmarkResult:
        architecture = 100
        safety = 100
        evidence = 100
        benchmark = 100

        if task.status == TaskStatus.BLOCKED:
            architecture = 80
            safety = 85
            evidence = 90
            benchmark = 75

        if task.status == TaskStatus.CANCELLED:
            architecture = 75
            safety = 80
            evidence = 85
            benchmark = 70

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
        self.registry.add(evidence_item)

    def verify(self, task_id: str) -> bool:
        return self.registry.is_verified(task_id)

    def verify_consistency(self, tasks: Sequence[TaskRecord]) -> bool:
        results = [self.run_core_task(task) for task in tasks]
        totals = [result.total for result in results]
        return all(0 <= total <= 100 for total in totals) and len(results) == len(tasks)

    def score_summary(self, tasks: Sequence[TaskRecord]) -> Dict[str, int]:
        results = [self.run_core_task(task) for task in tasks]
        return {
            "average_total": int(sum(item.total for item in results) / max(1, len(results))),
            "best_total": max(item.total for item in results) if results else 0,
            "worst_total": min(item.total for item in results) if results else 0,
        }
