from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

@dataclass(frozen=True)
class Evidence:
    kind: str
    completed_at: datetime
    valid_for: timedelta
    passed: bool

@dataclass(frozen=True)
class ReleasePolicy:
    required: frozenset[str]

def releasable(evidence: list[Evidence], policy: ReleasePolicy, at: datetime) -> bool:
    x = at.astimezone(timezone.utc)
    valid = set()
    for e in evidence:
        t = e.completed_at.astimezone(timezone.utc)
        if e.passed and t <= x <= t + e.valid_for:
            valid.add(e.kind)
    return policy.required.issubset(valid)
