from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Evidence:
    kind: str
    passed: bool
    revision: int

@dataclass(frozen=True)
class DeparturePolicy:
    required: frozenset[str]
    minimum_revision: dict[str, int]

def readiness(evidence: list[Evidence], policy: DeparturePolicy):
    latest = {}
    for e in evidence:
        prev = latest.get(e.kind)
        if prev is None or e.revision > prev.revision:
            latest[e.kind] = e
    missing = []
    failed = []
    stale = []
    for kind in policy.required:
        e = latest.get(kind)
        if e is None:
            missing.append(kind)
            continue
        if not e.passed:
            failed.append(kind)
        if e.revision < policy.minimum_revision.get(kind, 0):
            stale.append(kind)
    return {'ready': not (missing or failed or stale), 'missing': sorted(missing), 'failed': sorted(failed), 'stale': sorted(stale)}
