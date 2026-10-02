from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class EnergySegment:
    traction_kwh: float
    regen_kwh: float
    acceptance_limit_kwh: float

def net_energy(rows: list[EnergySegment]) -> float:
    total = 0.0
    for r in rows:
        if min(r.traction_kwh, r.regen_kwh, r.acceptance_limit_kwh) < 0:
            raise ValueError('energy')
        recovered = min(r.regen_kwh, r.acceptance_limit_kwh, r.traction_kwh)
        total += r.traction_kwh - recovered
    return total
