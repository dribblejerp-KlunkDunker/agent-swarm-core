from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Set


@dataclass
class Lock:
    resource: str
    task_id: str
    owner: str
    reason: str


class LockRegistry:
    """Tracks resource locks, including parent-directory/child-file overlap."""

    def __init__(self) -> None:
        self._locks: Dict[str, Lock] = {}

    @staticmethod
    def _normalize(resource: str) -> str:
        normalized = (resource or "").strip().replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        normalized = normalized.rstrip("/")
        if not normalized:
            raise ValueError("resource must be a non-empty path or identifier")
        return normalized

    @staticmethod
    def _overlaps(left: str, right: str) -> bool:
        return (
            left == right
            or left.startswith(right + "/")
            or right.startswith(left + "/")
        )

    def reserve(self, resource: str, task_id: str, owner: str, reason: str) -> bool:
        normalized = self._normalize(resource)
        if not task_id or not owner:
            raise ValueError("task_id and owner must be non-empty")

        for existing_resource, existing in self._locks.items():
            if not self._overlaps(normalized, existing_resource):
                continue
            if existing.task_id != task_id or existing.owner != owner:
                return False
            if existing_resource == normalized:
                return True
            # The same task and owner may reserve a parent and child resource together.

        self._locks[normalized] = Lock(
            resource=normalized,
            task_id=task_id,
            owner=owner,
            reason=reason,
        )
        return True

    def release(self, resource: str, task_id: Optional[str] = None) -> bool:
        normalized = self._normalize(resource)
        lock = self._locks.get(normalized)
        if lock is None:
            return False
        if task_id is not None and lock.task_id != task_id:
            return False
        del self._locks[normalized]
        return True

    def check(self, resource: str) -> Optional[Lock]:
        normalized = self._normalize(resource)
        exact = self._locks.get(normalized)
        if exact is not None:
            return exact
        overlapping = [
            lock for key, lock in self._locks.items()
            if self._overlaps(normalized, key)
        ]
        return max(overlapping, key=lambda lock: len(lock.resource), default=None)

    def list_locks(self) -> Set[str]:
        return set(self._locks.keys())
