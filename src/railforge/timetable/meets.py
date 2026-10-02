from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass(frozen=True)
class Traversal:
    train: str
    section: str
    start: datetime
    end: datetime
    direction: int

def conflicts(rows: list[Traversal]) -> list[tuple[str, str, str]]:
    groups = {}
    for r in rows:
        groups.setdefault(r.section, []).append(r)
    out = []
    for section, xs in groups.items():
        xs = sorted(xs, key=lambda r: r.start.astimezone(timezone.utc))
        for i, a in enumerate(xs):
            if a.end <= a.start:
                raise ValueError('traversal')
            for b in xs[i + 1:]:
                if b.start >= a.end:
                    break
                if a.direction != b.direction:
                    out.append((section, a.train, b.train))
    return out
