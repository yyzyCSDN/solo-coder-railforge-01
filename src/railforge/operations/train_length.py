from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class TrainLengthSegment:
    segment_id: str
    distance_km: float
    capacity: float
    limit: float
    cost: float
    enabled: bool = True

def feasible(rows: list[TrainLengthSegment], required_capacity: float, required_limit: float):
    return bool(rows) and all((r.enabled and r.capacity >= required_capacity and (r.limit >= required_limit) for r in rows))

def cost(rows):
    if any((r.distance_km < 0 or r.cost < 0 for r in rows)):
        raise ValueError('segment')
    return sum((r.distance_km * r.cost for r in rows))

def bottleneck(rows):
    return None if not rows else min(rows, key=lambda r: (r.capacity, r.limit, r.segment_id))

def summarize(rows):
    return {'distance_km': sum((r.distance_km for r in rows)), 'cost': cost(rows), 'min_capacity': min((r.capacity for r in rows), default=0)}
