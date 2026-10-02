from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class BlockPlanOption:
    option_id: str
    capacity: float
    cost: float
    risk: float
    duration: float
    capabilities: frozenset[str] = frozenset()

def feasible(o: BlockPlanOption, required_capacity: float, required_caps: set[str], max_risk: float, max_duration: float):
    return o.capacity >= required_capacity and required_caps.issubset(o.capabilities) and (o.risk <= max_risk) and (o.duration <= max_duration)

def choose(rows: list[BlockPlanOption], required_capacity: float, required_caps: set[str], max_risk: float, max_duration: float):
    xs = [o for o in rows if feasible(o, required_capacity, required_caps, max_risk, max_duration)]
    if not xs:
        raise ValueError('no feasible block_plan option')
    return min(xs, key=lambda o: (o.cost + o.risk * 5.0, o.duration, o.option_id))

def alternatives(rows, *args):
    return sorted([o for o in rows if feasible(o, *args)], key=lambda o: (o.cost, o.risk, o.duration, o.option_id))
