from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Cut:
    cut_id: str
    destination: str
    wagons: int
    hazard_group: str | None = None

@dataclass(frozen=True)
class Track:
    track_id: str
    capacity: int
    destinations: frozenset[str]
    forbidden_hazard: frozenset[str]

def classify(cuts: list[Cut], tracks: list[Track], occupied: dict[str, int]):
    remain = {t.track_id: t.capacity - occupied.get(t.track_id, 0) for t in tracks}
    result = {}
    for c in sorted(cuts, key=lambda c: (-c.wagons, c.destination, c.cut_id)):
        choices = []
        for t in tracks:
            if c.destination not in t.destinations or c.wagons > remain[t.track_id]:
                continue
            if c.hazard_group and c.hazard_group in t.forbidden_hazard:
                continue
            choices.append((remain[t.track_id] - c.wagons, t.track_id))
        if not choices:
            raise ValueError('no classification track for ' + c.cut_id)
        _, tid = min(choices)
        result[c.cut_id] = tid
        remain[tid] -= c.wagons
    return result
