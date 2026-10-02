from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict

@dataclass(frozen=True)
class InboundCut:
    cut_id: str
    arrival_order: int
    destination: str
    wagons: int
    ready: bool

@dataclass(frozen=True)
class ClassificationTrack:
    track_id: str
    capacity: int
    reserved: int
    allowed_destinations: frozenset[str]

def assign(cuts: list[InboundCut], tracks: list[ClassificationTrack]):
    used = {t.track_id: t.reserved for t in tracks}
    assignment = {}
    grouped = defaultdict(list)
    for c in cuts:
        if c.ready:
            grouped[c.destination].append(c)
    for destination in sorted(grouped, key=lambda d: (-sum((c.wagons for c in grouped[d])), d)):
        for cut in sorted(grouped[destination], key=lambda c: (c.arrival_order, c.cut_id)):
            choices = []
            for t in tracks:
                if destination not in t.allowed_destinations:
                    continue
                free = t.capacity - used[t.track_id]
                if free >= cut.wagons:
                    choices.append((free - cut.wagons, used[t.track_id], t.track_id))
            if not choices:
                raise ValueError('classification capacity exhausted')
            _, _, tid = min(choices)
            assignment[cut.cut_id] = tid
            used[tid] += cut.wagons
    return (assignment, used)

def pull_sequence(assignment, cuts):
    cm = {c.cut_id: c for c in cuts}
    by = defaultdict(list)
    for cid, tid in assignment.items():
        by[tid].append(cm[cid])
    return {tid: [c.cut_id for c in sorted(xs, key=lambda c: (c.destination, c.arrival_order, c.cut_id))] for tid, xs in by.items()}
