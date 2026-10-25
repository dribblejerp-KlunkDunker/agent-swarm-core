from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Set


@dataclass
class Lock:
    resource: str
    task_id: str
    owner: str
    reason: str


class LockRegistry:
    """Tracks resource-level locks to prevent overlapping edits."""

    def __init__(self) -> None:
        self._locks: Dict[str, Lock] = {}

    def reserve(self, resource: str, task_id: str, owner: str, reason: str) -> bool:
        if resource in self._locks:
            existing = self._locks[resource]
            if existing.task_id != task_id:
                return False
        self._locks[resource] = Lock(resource=resource, task_id=task_id, owner=owner, reason=reason)
        return True

    def release(self, resource: str, task_id: Optional[str] = None) -> bool:
        lock = self._locks.get(resource)
        if lock is None:
            return False
        if task_id is not None and lock.task_id != task_id:
            return False
        del self._locks[resource]
        return True

    def check(self, resource: str) -> Optional[Lock]:
        return self._locks.get(resource)

    def list_locks(self) -> Set[str]:
        return set(self._locks.keys())
