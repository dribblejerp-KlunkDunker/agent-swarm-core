from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class EvidenceStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


@dataclass
class EvidenceBundle:
    task_id: str
    title: str
    content: str
    source: str = "runtime"
    status: EvidenceStatus = EvidenceStatus.PENDING
    tags: List[str] = field(default_factory=list)


class EvidenceRegistry:
    """Tracks evidence without allowing callers to mutate stored verification state."""

    def __init__(self) -> None:
        self._evidence: Dict[str, List[EvidenceBundle]] = {}

    def add(self, bundle: EvidenceBundle) -> None:
        if not bundle.task_id.strip() or not bundle.title.strip() or not bundle.content.strip():
            raise ValueError("Evidence requires a task_id, title, and non-empty content")
        if bundle.status != EvidenceStatus.PENDING:
            raise ValueError("New evidence must start as PENDING and be verified by the registry")
        self._evidence.setdefault(bundle.task_id, []).append(copy.deepcopy(bundle))

    def get(self, task_id: str) -> List[EvidenceBundle]:
        return copy.deepcopy(self._evidence.get(task_id, []))

    def mark_verified(self, task_id: str, title: Optional[str] = None) -> None:
        for item in self._evidence.get(task_id, []):
            if (title is None or item.title == title) and item.status == EvidenceStatus.PENDING:
                item.status = EvidenceStatus.VERIFIED

    def mark_rejected(self, task_id: str, title: Optional[str] = None) -> None:
        for item in self._evidence.get(task_id, []):
            if title is None or item.title == title:
                item.status = EvidenceStatus.REJECTED

    def is_verified(self, task_id: str) -> bool:
        items = self._evidence.get(task_id, [])
        return bool(items) and all(item.status == EvidenceStatus.VERIFIED for item in items)

    def has_evidence(self, task_id: str) -> bool:
        return bool(self._evidence.get(task_id))
