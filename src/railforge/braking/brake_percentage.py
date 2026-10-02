from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Vehicle:
    id: str
    gross_tonnes: float
    braked_tonnes: float
    operative: bool = True

def brake_percentage(rows: list[Vehicle], gradient_permille: float) -> float:
    gross = sum((r.gross_tonnes for r in rows))
    if gross <= 0:
        raise ValueError('gross weight')
    operative = sum((min(r.gross_tonnes, r.braked_tonnes) for r in rows if r.operative))
    raw = operative / gross * 100
    gradient_penalty = max(0.0, gradient_permille) * 0.35
    return max(0.0, raw - gradient_penalty)

def meets(rows: list[Vehicle], gradient_permille: float, required_percent: float) -> bool:
    return brake_percentage(rows, gradient_permille) >= required_percent
