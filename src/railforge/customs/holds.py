from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass(frozen=True)
class Hold:
    start: datetime
    end: datetime | None
    scope: str
    reason: str

def active(rows: list[Hold], scope: str, at: datetime):
    x = at.astimezone(timezone.utc)
    out = []
    for h in rows:
        if h.scope != scope:
            continue
        s = h.start.astimezone(timezone.utc)
        e = h.end.astimezone(timezone.utc) if h.end else None
        if e is not None and e <= s:
            raise ValueError('hold')
        if s <= x and (e is None or x < e):
            out.append(h)
    return out
