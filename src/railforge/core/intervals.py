from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from .time import utc

@dataclass(frozen=True, order=True)
class Interval:
    start: datetime
    end: datetime

    def normalized(self):
        s, e = (utc(self.start), utc(self.end))
        if e <= s:
            raise ValueError('invalid interval')
        return Interval(s, e)

def merge(rows: list[Interval]) -> list[Interval]:
    if not rows:
        return []
    ordered = sorted((r.normalized() for r in rows), key=lambda r: r.start)
    out = [ordered[0]]
    for r in ordered[1:]:
        p = out[-1]
        if r.start <= p.end:
            out[-1] = Interval(p.start, max(p.end, r.end))
        else:
            out.append(r)
    return out

def subtract(base: Interval, blocked: list[Interval]) -> list[Interval]:
    parts = [base.normalized()]
    for b in merge(blocked):
        nxt = []
        for p in parts:
            if b.end <= p.start or b.start >= p.end:
                nxt.append(p)
                continue
            if p.start < b.start:
                nxt.append(Interval(p.start, b.start))
            if b.end < p.end:
                nxt.append(Interval(b.end, p.end))
        parts = nxt
    return parts
