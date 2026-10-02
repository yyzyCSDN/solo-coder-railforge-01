from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Wagon:
    wagon_id: str
    destination: str
    gross_t: float
    length_m: float
    brake_pct: float
    group: str

@dataclass(frozen=True)
class TrainLimit:
    max_tonnes: float
    max_length_m: float
    min_brake_pct: float
    max_wagons: int

def build(wagons: list[Wagon], limit: TrainLimit, destination_order: list[str]):
    rank = {d: i for i, d in enumerate(destination_order)}
    selected = []
    weight = length = 0.0
    for w in sorted(wagons, key=lambda w: (rank.get(w.destination, 10 ** 6), w.group, w.wagon_id)):
        if len(selected) >= limit.max_wagons:
            break
        if weight + w.gross_t > limit.max_tonnes or length + w.length_m > limit.max_length_m:
            continue
        total_braked = sum((x.gross_t * x.brake_pct / 100 for x in selected)) + w.gross_t * w.brake_pct / 100
        total_weight = weight + w.gross_t
        if total_braked / total_weight * 100 < limit.min_brake_pct:
            continue
        selected.append(w)
        weight = total_weight
        length += w.length_m
    return selected

def split_by_destination(consist):
    out = {}
    for w in consist:
        out.setdefault(w.destination, []).append(w.wagon_id)
    return out

def summary(consist):
    total = sum((w.gross_t for w in consist))
    length = sum((w.length_m for w in consist))
    brake = 0 if total == 0 else sum((w.gross_t * w.brake_pct / 100 for w in consist)) / total * 100
    return {'wagons': len(consist), 'tonnes': total, 'length_m': length, 'brake_pct': brake}
