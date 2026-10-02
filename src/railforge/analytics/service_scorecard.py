from __future__ import annotations
from dataclasses import dataclass
from statistics import median

@dataclass(frozen=True)
class Trip:
    service: str
    origin_delay: int
    destination_delay: int
    dwell_minutes: int
    cancelled: bool
    loaded_wagons: int

def score(rows: list[Trip]):
    groups = {}
    for r in rows:
        groups.setdefault(r.service, []).append(r)
    result = {}
    for service, xs in groups.items():
        completed = [x for x in xs if not x.cancelled]
        completion = len(completed) / len(xs)
        delays = [max(0, x.destination_delay) for x in completed]
        dwell = [max(0, x.dwell_minutes) for x in completed]
        loaded = sum((x.loaded_wagons for x in completed))
        result[service] = {'completion': completion, 'median_delay': median(delays) if delays else None, 'median_dwell': median(dwell) if dwell else None, 'loaded_wagons': loaded, 'score': completion * 100 - (median(delays) if delays else 240) * 0.18 - (median(dwell) if dwell else 480) * 0.04}
    return result

def rank(rows):
    return sorted(score(rows).items(), key=lambda kv: (-kv[1]['score'], kv[0]))
