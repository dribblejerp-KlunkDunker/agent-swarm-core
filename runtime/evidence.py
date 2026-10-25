from __future__ import annotations

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
    """Tracks evidence associated with a task and whether it is sufficient."""

    def __init__(self) -> None:
        self._evidence: Dict[str, List[EvidenceBundle]] = {}

    def add(self, bundle: EvidenceBundle) -> None:
        self._evidence.setdefault(bundle.task_id, []).append(bundle)

    def get(self, task_id: str) -> List[EvidenceBundle]:
        return list(self._evidence.get(task_id, []))

    def mark_verified(self, task_id: str, title: Optional[str] = None) -> None:
        for item in self._evidence.get(task_id, []):
            if title is None or item.title == title:
                item.status = EvidenceStatus.VERIFIED

    def is_verified(self, task_id: str) -> bool:
        items = self._evidence.get(task_id, [])
        return bool(items) and all(item.status == EvidenceStatus.VERIFIED for item in items)

    def has_evidence(self, task_id: str) -> bool:
        return bool(self._evidence.get(task_id))
