from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

@dataclass(frozen=True)
class Leg:
    leg_id: str
    origin: str
    destination: str
    depart: datetime
    arrive: datetime
    required_units: int

@dataclass(frozen=True)
class Unit:
    unit_id: str
    location: str
    available_at: datetime
    due_hours: float

def circulate(legs: list[Leg], units: list[Unit], turn_minutes: int):
    state = {u.unit_id: (u.location, u.available_at.astimezone(timezone.utc), u.due_hours) for u in units}
    result = {}
    for leg in sorted(legs, key=lambda l: (l.depart, l.leg_id)):
        depart = leg.depart.astimezone(timezone.utc)
        arrive = leg.arrive.astimezone(timezone.utc)
        if arrive <= depart:
            raise ValueError('leg')
        candidates = []
        for uid, (loc, avail, due) in state.items():
            if loc == leg.origin and avail <= depart and (due > (arrive - depart).total_seconds() / 3600):
                candidates.append((avail, -due, uid))
        candidates.sort()
        chosen = [uid for _, _, uid in candidates[:leg.required_units]]
        if len(chosen) < leg.required_units:
            raise ValueError('locomotive shortage')
        for uid in chosen:
            loc, avail, due = state[uid]
            hours = (arrive - depart).total_seconds() / 3600
            state[uid] = (leg.destination, arrive + timedelta(minutes=turn_minutes), due - hours)
        result[leg.leg_id] = chosen
    return (result, state)
