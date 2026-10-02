from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Train:
    train: str
    priority: int
    delay: int
    remaining_km: float
    customer_penalty: float

@dataclass(frozen=True)
class RecoveryAction:
    action_id: str
    train: str
    minutes_saved: int
    cost: float
    capacity_used: int
    risk: float

def choose(trains: list[Train], actions: list[RecoveryAction], capacity_budget: int, cost_budget: float, max_risk: float):
    tm = {t.train: t for t in trains}
    candidates = []
    for a in actions:
        if a.train not in tm or a.risk > max_risk or a.capacity_used < 0 or (a.cost < 0):
            continue
        t = tm[a.train]
        benefit = min(t.delay, a.minutes_saved) * (1 + t.priority) * t.customer_penalty
        candidates.append((benefit / (1 + a.cost), benefit, a))
    candidates.sort(key=lambda x: (-x[0], -x[1], x[2].action_id))
    chosen = []
    cap = 0
    cost = 0.0
    seen = set()
    for _, _, a in candidates:
        if a.train in seen:
            continue
        if cap + a.capacity_used > capacity_budget or cost + a.cost > cost_budget:
            continue
        chosen.append(a)
        seen.add(a.train)
        cap += a.capacity_used
        cost += a.cost
    return chosen

def projected_delay(trains, chosen):
    saved = {a.train: a.minutes_saved for a in chosen}
    return {t.train: max(0, t.delay - saved.get(t.train, 0)) for t in trains}
