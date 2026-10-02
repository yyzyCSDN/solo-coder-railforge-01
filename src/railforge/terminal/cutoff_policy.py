from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass(frozen=True)
class CutoffRule:
    rule_id: str
    scope: str
    effective_from: datetime
    effective_to: datetime | None
    priority: int
    value: str

def active(rows: list[CutoffRule], scope: str, at: datetime):
    x = at.astimezone(timezone.utc)
    xs = []
    for r in rows:
        if r.scope not in (scope, '*'):
            continue
        s = r.effective_from.astimezone(timezone.utc)
        e = r.effective_to.astimezone(timezone.utc) if r.effective_to else None
        if e is not None and e <= s:
            raise ValueError('rule interval')
        if s <= x and (e is None or x < e):
            xs.append(r)
    return max(xs, key=lambda r: (r.priority, r.effective_from, r.rule_id), default=None)

def timeline(rows, scope):
    return sorted([r for r in rows if r.scope in (scope, '*')], key=lambda r: (r.effective_from, -r.priority, r.rule_id))

def conflicts(rows):
    out = []
    for i, a in enumerate(rows):
        ae = a.effective_to or datetime.max.replace(tzinfo=timezone.utc)
        for b in rows[i + 1:]:
            be = b.effective_to or datetime.max.replace(tzinfo=timezone.utc)
            if a.scope == b.scope and a.priority == b.priority and (max(a.effective_from, b.effective_from) < min(ae, be)):
                out.append((a.rule_id, b.rule_id))
    return out
