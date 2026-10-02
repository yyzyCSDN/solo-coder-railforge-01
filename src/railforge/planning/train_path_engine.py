from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from collections import defaultdict

@dataclass(frozen=True)
class Section:
    section_id: str
    run_minutes: int
    single_track: bool
    capacity_per_hour: int

@dataclass(frozen=True)
class PathRequest:
    train: str
    origin_time: datetime
    sections: tuple[str, ...]
    priority: int
    max_delay_minutes: int

@dataclass(frozen=True)
class Slot:
    train: str
    section: str
    start: datetime
    end: datetime

def _overlap(a, b, c, d):
    return max(a, c) < min(b, d)

def build(requests: list[PathRequest], sections: dict[str, Section], existing: list[Slot], headway_minutes: int):
    if headway_minutes < 0:
        raise ValueError('headway')
    planned = list(existing)
    result = {}
    for req in sorted(requests, key=lambda r: (-r.priority, r.origin_time, r.train)):
        start = req.origin_time.astimezone(timezone.utc)
        delay = 0
        slots = []
        for sid in req.sections:
            section = sections[sid]
            while True:
                end = start + timedelta(minutes=section.run_minutes)
                blocked = False
                for row in planned + slots:
                    if row.section != sid:
                        continue
                    guard = timedelta(minutes=headway_minutes)
                    if _overlap(start, end, row.start - guard, row.end + guard):
                        blocked = True
                        break
                if not blocked:
                    break
                start += timedelta(minutes=1)
                delay += 1
                if delay > req.max_delay_minutes:
                    raise ValueError('path request exceeds delay tolerance')
            slot = Slot(req.train, sid, start, end)
            slots.append(slot)
            start = end
        planned.extend(slots)
        result[req.train] = slots
    return result

def section_load(plan):
    out = defaultdict(float)
    for slots in plan.values():
        for s in slots:
            out[s.section] += (s.end - s.start).total_seconds() / 3600
    return dict(out)

def train_delay(plan, requests):
    rm = {r.train: r for r in requests}
    out = {}
    for train, slots in plan.items():
        out[train] = 0 if not slots else max(0, (slots[0].start - rm[train].origin_time.astimezone(timezone.utc)).total_seconds() / 60)
    return out
