from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta

@dataclass(frozen=True)
class Wagon:
    id: str
    type: str
    location: str
    maintenance_due: date
    reserved: bool = False
    restrictions: frozenset[str] = frozenset()

def allocate(rows: list[Wagon], wagon_type: str, location: str, on: date, count: int, required_days: int=0, forbidden_restrictions: set[str] | None=None):
    if count <= 0 or required_days < 0:
        raise ValueError('allocation request')
    forbidden_restrictions = forbidden_restrictions or set()
    service_end = on + timedelta(days=required_days)
    xs = []
    for wagon in rows:
        if wagon.type != wagon_type or wagon.location != location or wagon.reserved:
            continue
        if wagon.maintenance_due <= service_end:
            continue
        if wagon.restrictions.intersection(forbidden_restrictions):
            continue
        xs.append(wagon)
    xs.sort(key=lambda wagon: (wagon.maintenance_due, len(wagon.restrictions), wagon.id))
    if len(xs) < count:
        raise ValueError('insufficient wagons')
    return xs[:count]

def availability(rows: list[Wagon], on: date, required_days: int=0):
    service_end = on + timedelta(days=required_days)
    out = {}
    for wagon in rows:
        if not wagon.reserved and wagon.maintenance_due > service_end:
            out[wagon.type] = out.get(wagon.type, 0) + 1
    return out
