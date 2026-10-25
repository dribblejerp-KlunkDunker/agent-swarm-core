from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .task_state import TaskRecord, TaskStatus


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
    """Atomic file-backed task board; malformed state fails closed instead of resetting."""

    def __init__(self, board_path: str = ".agent/TASK_BOARD.json"):
        self.board_path = Path(board_path)
        self.board_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _string_list(value: object, field_name: str, task_id: str) -> List[str]:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError(f"Invalid task board field {field_name!r} for task {task_id!r}: expected a list of strings")
        return list(value)

    def load(self) -> Dict[str, TaskBoardEntry]:
        if not self.board_path.exists():
            return {}
        try:
            payload = json.loads(self.board_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot load task board {self.board_path}: data is unreadable or invalid JSON") from exc

        if not isinstance(payload, dict):
            raise ValueError(f"Cannot load task board {self.board_path}: top-level JSON value must be an object")

        tasks: Dict[str, TaskBoardEntry] = {}
        for task_id, entry in payload.items():
            if not isinstance(task_id, str) or not isinstance(entry, dict):
                raise ValueError(f"Cannot load task board {self.board_path}: each task must be an object keyed by task ID")
            stored_task_id = entry.get("task_id", task_id)
            if stored_task_id != task_id:
                raise ValueError(f"Cannot load task board {self.board_path}: task ID key mismatch for {task_id!r}")
            status = entry.get("status", TaskStatus.INTAKE.value)
            try:
                TaskStatus(status)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Cannot load task board {self.board_path}: invalid status {status!r} for task {task_id!r}") from exc

            tasks[task_id] = TaskBoardEntry(
                task_id=stored_task_id,
                owner=entry.get("owner", "unknown"),
                objective=entry.get("objective", ""),
                status=status,
                scope=self._string_list(entry.get("scope", []), "scope", task_id),
                blockers=self._string_list(entry.get("blockers", []), "blockers", task_id),
                evidence=self._string_list(entry.get("evidence", []), "evidence", task_id),
                repo=entry.get("repo", ""),
                updated_at=entry.get("updated_at", ""),
            )
        return tasks

    def save(self, tasks: Dict[str, TaskBoardEntry]) -> None:
        payload = {}
        for task_id, entry in tasks.items():
            if task_id != entry.task_id:
                raise ValueError(f"Task board key {task_id!r} does not match entry ID {entry.task_id!r}")
            try:
                TaskStatus(entry.status)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid task status {entry.status!r} for task {task_id!r}") from exc
            payload[task_id] = {
                "task_id": entry.task_id,
                "owner": entry.owner,
                "objective": entry.objective,
                "status": entry.status,
                "scope": self._string_list(entry.scope, "scope", task_id),
                "blockers": self._string_list(entry.blockers, "blockers", task_id),
                "evidence": self._string_list(entry.evidence, "evidence", task_id),
                "repo": entry.repo,
                "updated_at": entry.updated_at or _utc_now(),
            }

        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(self.board_path.parent),
                prefix=f".{self.board_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.board_path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def add_or_update(self, task: TaskRecord) -> TaskBoardEntry:
        tasks = self.load()
        entry = TaskBoardEntry(
            task_id=task.task_id,
            owner=task.owner,
            objective=task.objective,
            status=task.status.value,
            scope=list(task.scope),
            blockers=list(task.blockers),
            evidence=list(task.evidence),
            repo=task.repo,
            updated_at=task.updated_at or _utc_now(),
        )
        tasks[task.task_id] = entry
        self.save(tasks)
        return entry

    def get(self, task_id: str) -> Optional[TaskBoardEntry]:
        return self.load().get(task_id)

    def get_blocked_tasks(self) -> List[TaskBoardEntry]:
        return [entry for entry in self.load().values() if entry.status == TaskStatus.BLOCKED.value]

    def resume(self, task_id: str) -> Optional[TaskBoardEntry]:
        # Loading performs schema/state validation; callers must still re-check locks and evidence.
        return self.get(task_id)
