from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

@dataclass(frozen=True)
class Occupancy:
    train: str
    block: str
    enter: datetime
    exit: datetime
    direction: int

def conflicts(candidate: Occupancy, existing: list[Occupancy], clearance: timedelta) -> list[str]:
    ce = candidate.enter.astimezone(timezone.utc)
    cx = candidate.exit.astimezone(timezone.utc)
    if cx <= ce:
        raise ValueError('invalid occupancy')
    if clearance.total_seconds() < 0:
        raise ValueError('clearance')
    hits = []
    for row in existing:
        if row.block != candidate.block or row.train == candidate.train:
            continue
        re = row.enter.astimezone(timezone.utc) - clearance
        rx = row.exit.astimezone(timezone.utc) + clearance
        if max(ce, re) < min(cx, rx):
            hits.append(row.train)
    return sorted(set(hits))

def reserve(candidate: Occupancy, existing: list[Occupancy], clearance: timedelta):
    hit = conflicts(candidate, existing, clearance)
    if hit:
        raise ValueError('block conflict: ' + ','.join(hit))
    return sorted(existing + [candidate], key=lambda r: (r.block, r.enter, r.train))
