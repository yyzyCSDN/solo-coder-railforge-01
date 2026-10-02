from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import defaultdict

@dataclass(frozen=True)
class Transfer:
    transfer_id: str
    arrival: datetime
    departure: datetime
    units: int
    source_area: str
    target_area: str
    priority: int

@dataclass(frozen=True)
class HandlingResource:
    resource_id: str
    units_per_hour: float
    areas: frozenset[str]
    available_from: datetime
    available_to: datetime

def plan(transfers: list[Transfer], resources: list[HandlingResource], bucket_minutes: int=15):
    if bucket_minutes <= 0:
        raise ValueError('bucket')
    usage = defaultdict(float)
    result = {}
    for t in sorted(transfers, key=lambda x: (x.departure, -x.priority, x.arrival, x.transfer_id)):
        if t.departure <= t.arrival or t.units <= 0:
            raise ValueError('transfer')
        best = None
        for r in resources:
            if t.source_area not in r.areas or t.target_area not in r.areas or r.units_per_hour <= 0:
                continue
            duration = timedelta(hours=t.units / r.units_per_hour)
            cursor = max(t.arrival, r.available_from)
            end_limit = min(t.departure, r.available_to)
            while cursor + duration <= end_limit:
                bucket = int(cursor.timestamp() // (bucket_minutes * 60))
                load = usage[r.resource_id, bucket]
                if load < 1:
                    candidate = (cursor + duration, cursor, r.resource_id, bucket)
                    if best is None or candidate < best:
                        best = candidate
                    break
                cursor += timedelta(minutes=bucket_minutes)
        if best is None:
            raise ValueError('terminal handling capacity')
        finish, start, rid, bucket = best
        usage[rid, bucket] += 1
        result[t.transfer_id] = (rid, start, finish)
    return result
