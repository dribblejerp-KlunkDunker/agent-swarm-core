from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .task_state import TaskRecord, TaskStatus


@dataclass
class TaskBoardEntry:
    task_id: str
    owner: str
    objective: str
    status: str
    scope: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    repo: str = ""
    updated_at: str = ""


class TaskBoard:
    """Durable, file-backed task board with basic resume capability."""

    def __init__(self, board_path: str = ".agent/TASK_BOARD.json"):
        self.board_path = Path(board_path)
        self.board_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Dict[str, TaskBoardEntry]:
        if not self.board_path.exists():
            return {}
        try:
            payload = json.loads(self.board_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return {
            task_id: TaskBoardEntry(
                task_id=entry.get("task_id", task_id),
                owner=entry.get("owner", "unknown"),
                objective=entry.get("objective", ""),
                status=entry.get("status", TaskStatus.INTAKE.value),
                scope=entry.get("scope", []),
                blockers=entry.get("blockers", []),
                evidence=entry.get("evidence", []),
                repo=entry.get("repo", ""),
                updated_at=entry.get("updated_at", ""),
            )
            for task_id, entry in payload.items()
        }

    def save(self, tasks: Dict[str, TaskBoardEntry]) -> None:
        payload = {
            task_id: {
                "task_id": entry.task_id,
                "owner": entry.owner,
                "objective": entry.objective,
                "status": entry.status,
                "scope": entry.scope,
                "blockers": entry.blockers,
                "evidence": entry.evidence,
                "repo": entry.repo,
                "updated_at": entry.updated_at,
            }
            for task_id, entry in tasks.items()
        }
        self.board_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def add_or_update(self, task: TaskRecord) -> TaskBoardEntry:
        tasks = self.load()
        entry = TaskBoardEntry(
            task_id=task.task_id,
            owner=task.owner,
            objective=task.objective,
            status=task.status.value,
            scope=task.scope,
            blockers=task.blockers,
            evidence=task.evidence,
            repo=task.repo,
            updated_at=task.updated_at or "runtime",
        )
        tasks[task.task_id] = entry
        self.save(tasks)
        return entry

    def get(self, task_id: str) -> Optional[TaskBoardEntry]:
        return self.load().get(task_id)

    def get_blocked_tasks(self) -> List[TaskBoardEntry]:
        return [entry for entry in self.load().values() if entry.status == TaskStatus.BLOCKED.value]

    def resume(self, task_id: str) -> Optional[TaskBoardEntry]:
        entry = self.get(task_id)
        if entry is None:
            return None
        return entry
