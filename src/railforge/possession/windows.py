from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

@dataclass(frozen=True)
class Possession:
    id: str
    segment: str
    start: datetime
    end: datetime
    setup: timedelta
    release: timedelta

def protected_window(p: Possession):
    s = p.start.astimezone(timezone.utc) - p.setup
    e = p.end.astimezone(timezone.utc) + p.release
    if e <= s:
        raise ValueError('possession')
    return (s, e)

def conflicts(candidate: Possession, rows: list[Possession]) -> list[str]:
    cs, ce = protected_window(candidate)
    out = []
    for r in rows:
        if r.segment != candidate.segment or r.id == candidate.id:
            continue
        rs, re = protected_window(r)
        if max(cs, rs) < min(ce, re):
            out.append(r.id)
    return sorted(out)
