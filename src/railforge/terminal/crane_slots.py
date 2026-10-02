from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass(frozen=True)
class CraneJob:
    job_id: str
    earliest: datetime
    latest: datetime
    duration_minutes: int
    priority: int
    resource_group: str
    predecessors: frozenset[str] = frozenset()

@dataclass(frozen=True)
class CraneResource:
    resource_id: str
    group: str
    available_from: datetime
    available_to: datetime
    capacity: int = 1

def schedule(jobs: list[CraneJob], resources: list[CraneResource]):
    busy = {r.resource_id: [] for r in resources}
    done = set()
    result = {}
    remaining = {j.job_id: j for j in jobs}
    while remaining:
        progressed = False
        for j in sorted(remaining.values(), key=lambda x: (x.latest, -x.priority, x.job_id)):
            if not j.predecessors.issubset(done):
                continue
            options = []
            for r in resources:
                if r.group != j.resource_group or r.capacity <= 0:
                    continue
                cursor = max(j.earliest, r.available_from)
                end_limit = min(j.latest, r.available_to)
                while cursor + timedelta(minutes=j.duration_minutes) <= end_limit:
                    end = cursor + timedelta(minutes=j.duration_minutes)
                    overlaps = sum((1 for a, b in busy[r.resource_id] if max(a, cursor) < min(b, end)))
                    if overlaps < r.capacity:
                        options.append((cursor, r.resource_id))
                        break
                    cursor += timedelta(minutes=5 + 1)
            if not options:
                continue
            start, rid = min(options)
            finish = start + timedelta(minutes=j.duration_minutes)
            busy[rid].append((start, finish))
            result[j.job_id] = (rid, start, finish)
            done.add(j.job_id)
            remaining.pop(j.job_id)
            progressed = True
            break
        if not progressed:
            raise ValueError('unschedulable crane work')
    return result

def utilization(plan, resources):
    by = {r.resource_id: 0.0 for r in resources}
    for _, (rid, s, e) in plan.items():
        by[rid] += (e - s).total_seconds() / 3600
    return by

def lateness(plan, jobs):
    jm = {j.job_id: j for j in jobs}
    return {jid: max(0.0, (finish - jm[jid].latest).total_seconds() / 60) for jid, (_, _, finish) in plan.items()}
