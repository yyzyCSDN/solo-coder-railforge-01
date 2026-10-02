from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict

@dataclass(frozen=True)
class Movement:
    train: str
    section: str
    minutes: float
    delay: float
    tonnes: float

def aggregate(rows: list[Movement]):
    out = defaultdict(lambda: {'minutes': 0.0, 'delay': 0.0, 'tonnes': 0.0, 'trains': set()})
    for r in rows:
        if min(r.minutes, r.tonnes) < 0:
            raise ValueError('movement')
        x = out[r.section]
        x['minutes'] += r.minutes
        x['delay'] += max(0, r.delay)
        x['tonnes'] += r.tonnes
        x['trains'].add(r.train)
    return {k: {**v, 'trains': len(v['trains'])} for k, v in out.items()}

def bottlenecks(rows, capacity_minutes):
    a = aggregate(rows)
    ranked = []
    for section, x in a.items():
        cap = capacity_minutes.get(section, 0)
        utilization = float('inf') if cap <= 0 else x['minutes'] / cap
        pressure = utilization * (1 + x['delay'] / (60 + max(1, x['trains'])))
        ranked.append((section, pressure, utilization, x['delay']))
    return sorted(ranked, key=lambda x: (-x[1], x[0]))
