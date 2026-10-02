from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Wagon:
    id: str
    tare_t: float
    payload_t: float
    axles: int
    front_fraction: float = 0.5

def axle_loads(w: Wagon) -> list[float]:
    if w.axles not in (2, 4, 6, 8) or min(w.tare_t, w.payload_t) < 0 or (not 0 <= w.front_fraction <= 1):
        raise ValueError('wagon')
    total = w.tare_t + w.payload_t
    half = w.axles // 2
    front = total * w.front_fraction / half
    rear = total * (1 - w.front_fraction) / half
    return [front] * half + [rear] * half

def route_ok(w: Wagon, max_axle_t: float, max_gross_t: float) -> bool:
    loads = axle_loads(w)
    return sum(loads) <= max_gross_t and max(loads) <= max_axle_t
