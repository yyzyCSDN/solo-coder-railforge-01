from __future__ import annotations
from dataclasses import dataclass, replace
from datetime import datetime

@dataclass(frozen=True)
class QualityGateStep:
    step_id: str
    prerequisites: frozenset[str]
    role: str
    optional: bool = False

@dataclass(frozen=True)
class QualityGateCase:
    case_id: str
    completed: frozenset[str] = frozenset()
    cancelled: bool = False

def ready(case: QualityGateCase, steps: list[QualityGateStep]):
    if case.cancelled:
        return []
    return sorted((s.step_id for s in steps if s.step_id not in case.completed and s.prerequisites.issubset(case.completed)))

def complete(case: QualityGateCase, step_id: str, steps: list[QualityGateStep], actor_roles: set[str]):
    sm = {s.step_id: s for s in steps}
    s = sm[step_id]
    if step_id not in ready(case, steps):
        raise ValueError('step not ready')
    if s.role not in actor_roles:
        raise PermissionError('role')
    return replace(case, completed=case.completed | {step_id})

def finished(case, steps):
    return all((s.optional or s.step_id in case.completed for s in steps))
