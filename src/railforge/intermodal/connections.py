from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

@dataclass(frozen=True)
class Move:
    id: str
    terminal: str
    arrival: datetime
    departure: datetime

def feasible(inbound: Move, outbound: Move, unload: timedelta, load: timedelta, cutoff_before: timedelta) -> bool:
    if inbound.terminal != outbound.terminal:
        return False
    ready = inbound.arrival.astimezone(timezone.utc) + unload + load
    cutoff = outbound.departure.astimezone(timezone.utc) - cutoff_before
    return ready <= cutoff

def choose(inbound, candidates, unload, load, cutoff_before):
    xs = [x for x in candidates if feasible(inbound, x, unload, load, cutoff_before)]
    return min(xs, key=lambda x: (x.departure.astimezone(timezone.utc), x.id), default=None)
