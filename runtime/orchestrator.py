from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class SkillRoute:
    task_id: str
    objective: str
    required_skills: List[str] = field(default_factory=list)
    selected_skills: List[str] = field(default_factory=list)
    rationale: str = ""


class Orchestrator:
    """Selects a route based on required skills and available capabilities."""

    def __init__(self, available_skills: Optional[Set[str]] = None) -> None:
        self.available_skills = available_skills or set()

    def route(self, task_id: str, objective: str, required_skills: Optional[List[str]] = None) -> SkillRoute:
        required = required_skills or []
        selected: List[str] = []
        missing: List[str] = []
        for skill in required:
            if skill in self.available_skills:
                selected.append(skill)
            else:
                missing.append(skill)

        rationale = "all required skills are available" if not missing else f"missing skills: {', '.join(missing)}"
        return SkillRoute(
            task_id=task_id,
            objective=objective,
            required_skills=required,
            selected_skills=selected,
            rationale=rationale,
        )

    def can_execute(self, task_id: str, objective: str, required_skills: Optional[List[str]] = None) -> bool:
        route = self.route(task_id, objective, required_skills)
        return not set(route.required_skills) - set(route.selected_skills)
