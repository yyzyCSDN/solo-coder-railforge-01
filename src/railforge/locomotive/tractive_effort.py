from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Locomotive:
    id: str
    continuous_kn: float
    adhesion_kn: float
    available: bool = True

def available_effort(rows: list[Locomotive], adhesion_factor: float) -> float:
    if not 0 < adhesion_factor <= 1:
        raise ValueError('adhesion factor')
    total = 0.0
    for l in rows:
        if l.available:
            total += min(l.continuous_kn, l.adhesion_kn * adhesion_factor)
    return total

def required_effort(train_tonnes: float, gradient_permille: float, curve_resistance_kn: float) -> float:
    if train_tonnes <= 0 or curve_resistance_kn < 0:
        raise ValueError('invalid train')
    rolling = train_tonnes * 9.80665 * 0.0018
    grade = train_tonnes * 9.80665 * (gradient_permille / 1000)
    return rolling + max(0, grade) + curve_resistance_kn

def feasible(locos, train_tonnes, gradient_permille, curve_resistance_kn, adhesion_factor):
    return available_effort(locos, adhesion_factor) >= required_effort(train_tonnes, gradient_permille, curve_resistance_kn)
