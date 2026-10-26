from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .storage import SQLiteStateStore
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
    required_skills: List[str] = field(default_factory=list)
    branch: str = ""
    risk_level: str = "LOW"
    approval_action: str = "release"
    created_at: str = ""
    blockers: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    repo: str = ""
    updated_at: str = ""


class TaskBoard:
    """Durable task board with atomic JSON compatibility and SQLite production storage."""

    def __init__(
        self,
        board_path: Optional[str] = None,
        state_store: Optional[SQLiteStateStore] = None,
        *,
        db_path: Optional[str] = None,
    ):
        if state_store is not None and db_path is not None:
            raise ValueError("Pass state_store or db_path, not both")
        if state_store is not None and board_path is not None:
            raise ValueError("Pass state_store or board_path, not both")
        if db_path is not None and board_path is not None:
            raise ValueError("Pass db_path or board_path, not both")

        production = os.environ.get("SWARM_ENV", "").strip().lower() in {"prod", "production"}
        configured_db = db_path or os.environ.get("SWARM_STATE_DB")
        if production and board_path is not None and state_store is None and db_path is None:
            raise RuntimeError("Production task storage must use SQLite via SWARM_STATE_DB, not a JSON board")
        use_sqlite = state_store is not None or db_path is not None or (board_path is None and (configured_db or production))
        self._store: Optional[SQLiteStateStore] = None
        self.board_path: Optional[Path] = None

        if use_sqlite:
            self._store = state_store or SQLiteStateStore(db_path)
            if production and not self._store.persistent:
                raise RuntimeError("A durable SWARM_STATE_DB is required for production task storage")
        else:
            self.board_path = Path(board_path or ".agent/TASK_BOARD.json")
            self.board_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _string_list(value: object, field_name: str, task_id: str) -> List[str]:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError(f"Invalid task board field {field_name!r} for task {task_id!r}: expected a list of strings")
        return list(value)

    @staticmethod
    def _entry_from_payload(task_id: str, payload: object) -> TaskBoardEntry:
        if not isinstance(task_id, str) or not isinstance(payload, dict):
            raise ValueError("Task board entries must be objects keyed by task ID")
        stored_task_id = payload.get("task_id", task_id)
        if stored_task_id != task_id:
            raise ValueError(f"Task ID key mismatch for {task_id!r}")
        status = payload.get("status", TaskStatus.INTAKE.value)
        try:
            TaskStatus(status)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid task status {status!r} for task {task_id!r}") from exc
        owner = payload.get("owner", "unknown")
        objective = payload.get("objective", "")
        repo = payload.get("repo", "")
        updated_at = payload.get("updated_at", "")
        branch = payload.get("branch", "")
        risk_level = payload.get("risk_level", "LOW")
        approval_action = payload.get("approval_action", "release")
        created_at = payload.get("created_at", "")
        string_fields = (owner, objective, repo, updated_at, branch, risk_level, approval_action, created_at)
        if not all(isinstance(value, str) for value in string_fields):
            raise ValueError(f"Invalid string field in task board record {task_id!r}")
        return TaskBoardEntry(
            task_id=stored_task_id,
            owner=owner,
            objective=objective,
            status=status,
            scope=TaskBoard._string_list(payload.get("scope", []), "scope", task_id),
            required_skills=TaskBoard._string_list(payload.get("required_skills", []), "required_skills", task_id),
            branch=branch,
            risk_level=risk_level,
            approval_action=approval_action,
            created_at=created_at,
            blockers=TaskBoard._string_list(payload.get("blockers", []), "blockers", task_id),
            evidence=TaskBoard._string_list(payload.get("evidence", []), "evidence", task_id),
            repo=repo,
            updated_at=updated_at,
        )

    @staticmethod
    def _entry_payload(entry: TaskBoardEntry) -> Dict[str, object]:
        if not entry.task_id or not entry.owner:
            raise ValueError("Task board entries require task_id and owner")
        if not all(isinstance(value, str) for value in (
            entry.task_id, entry.owner, entry.objective, entry.branch, entry.risk_level,
            entry.approval_action, entry.created_at, entry.repo, entry.updated_at,
        )):
            raise ValueError(f"Task board string fields are invalid for task {entry.task_id!r}")
        TaskStatus(entry.status)
        return {
            "task_id": entry.task_id,
            "owner": entry.owner,
            "objective": entry.objective,
            "status": entry.status,
            "scope": TaskBoard._string_list(entry.scope, "scope", entry.task_id),
            "required_skills": TaskBoard._string_list(entry.required_skills, "required_skills", entry.task_id),
            "branch": entry.branch,
            "risk_level": entry.risk_level,
            "approval_action": entry.approval_action,
            "created_at": entry.created_at,
            "blockers": TaskBoard._string_list(entry.blockers, "blockers", entry.task_id),
            "evidence": TaskBoard._string_list(entry.evidence, "evidence", entry.task_id),
            "repo": entry.repo,
            "updated_at": entry.updated_at or _utc_now(),
        }

    def load(self) -> Dict[str, TaskBoardEntry]:
        if self._store is not None:
            payloads = self._store.list_task_json()
            tasks: Dict[str, TaskBoardEntry] = {}
            for task_id, serialized in payloads.items():
                try:
                    payload = json.loads(serialized)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Cannot load SQLite task {task_id!r}: invalid JSON payload") from exc
                tasks[task_id] = self._entry_from_payload(task_id, payload)
            return tasks

        assert self.board_path is not None
        if not self.board_path.exists():
            return {}
        try:
            payload = json.loads(self.board_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot load task board {self.board_path}: data is unreadable or invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Cannot load task board {self.board_path}: top-level JSON value must be an object")
        return {task_id: self._entry_from_payload(task_id, entry) for task_id, entry in payload.items()}

    def save(self, tasks: Dict[str, TaskBoardEntry]) -> None:
        payload: Dict[str, Dict[str, object]] = {}
        for task_id, entry in tasks.items():
            if task_id != entry.task_id:
                raise ValueError(f"Task board key {task_id!r} does not match entry ID {entry.task_id!r}")
            payload[task_id] = self._entry_payload(entry)

        if self._store is not None:
            with self._store.transaction() as connection:
                connection.execute("DELETE FROM tasks")
                for task_id, record in payload.items():
                    serialized = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
                    updated_at = str(record["updated_at"])
                    connection.execute(
                        "INSERT INTO tasks(task_id, payload_json, updated_at) VALUES(?, ?, ?)",
                        (task_id, serialized, updated_at),
                    )
                    self._store.append_event_in_transaction(
                        connection, "task.persisted", task_id=task_id,
                        payload={"updated_at": updated_at, "storage": "sqlite"},
                    )
                self._store.append_event_in_transaction(
                    connection, "task.board_replaced",
                    payload={"task_count": len(payload), "storage": "sqlite"},
                )
            return

        assert self.board_path is not None
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=str(self.board_path.parent),
                prefix=f".{self.board_path.name}.", suffix=".tmp", delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
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
        entry = TaskBoardEntry(
            task_id=task.task_id, owner=task.owner, objective=task.objective, status=task.status.value,
            scope=list(task.scope), required_skills=list(task.required_skills), branch=task.branch,
            risk_level=task.risk_level, approval_action=task.approval_action, created_at=task.created_at,
            blockers=list(task.blockers), evidence=list(task.evidence), repo=task.repo,
            updated_at=task.updated_at or _utc_now(),
        )
        payload = self._entry_payload(entry)
        if self._store is not None:
            self._store.put_task_json(
                task.task_id, json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False),
                str(payload["updated_at"]), actor=task.owner,
            )
        else:
            tasks = self.load()
            tasks[task.task_id] = entry
            self.save(tasks)
        return entry

    def get(self, task_id: str) -> Optional[TaskBoardEntry]:
        if self._store is not None:
            serialized = self._store.get_task_json(task_id)
            if serialized is None:
                return None
            try:
                payload = json.loads(serialized)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Cannot load SQLite task {task_id!r}: invalid JSON payload") from exc
            return self._entry_from_payload(task_id, payload)
        return self.load().get(task_id)

    def get_blocked_tasks(self) -> List[TaskBoardEntry]:
        return [entry for entry in self.load().values() if entry.status == TaskStatus.BLOCKED.value]

    def resume(self, task_id: str) -> Optional[TaskBoardEntry]:
        # Restoring a record is not permission to continue; the executor must re-check gates and locks.
        return self.get(task_id)
