from __future__ import annotations
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

@dataclass(frozen=True)
class PathSlot:
    slot_id: str
    section: str
    start: datetime
    end: datetime
    owner: str
    priority: int
    locked: bool = False

@dataclass(frozen=True)
class ExchangeRequest:
    request_id: str
    requester: str
    give_slot: str
    want_section: str
    earliest: datetime
    latest: datetime
    minimum_priority: int

@dataclass(frozen=True)
class ExchangeProposal:
    request_id: str
    give_slot: str
    take_slot: str
    score: float

def _duration(slot: PathSlot):
    a = slot.start.astimezone(timezone.utc)
    b = slot.end.astimezone(timezone.utc)
    if b <= a:
        raise ValueError('invalid slot')
    return b - a

def eligible(request: ExchangeRequest, candidate: PathSlot, owned: dict[str, PathSlot]):
    if candidate.locked or candidate.section != request.want_section or candidate.priority < request.minimum_priority:
        return False
    if candidate.owner == request.requester:
        return False
    give = owned.get(request.give_slot)
    if give is None or give.owner != request.requester or give.locked:
        return False
    s = candidate.start.astimezone(timezone.utc)
    e = candidate.end.astimezone(timezone.utc)
    return request.earliest.astimezone(timezone.utc) <= s and e <= request.latest.astimezone(timezone.utc) and (_duration(candidate) >= _duration(give) * 0.8)

def proposals(requests: list[ExchangeRequest], slots: list[PathSlot]):
    owned = {s.slot_id: s for s in slots}
    out = []
    for r in requests:
        give = owned.get(r.give_slot)
        if give is None:
            continue
        for c in slots:
            if not eligible(r, c, owned):
                continue
            start_gap = abs((c.start.astimezone(timezone.utc) - r.earliest.astimezone(timezone.utc)).total_seconds()) / 60
            duration_gap = abs((_duration(c) - _duration(give)).total_seconds()) / 60
            priority_gain = c.priority - give.priority
            score = 100 + priority_gain * 8 - start_gap * 0.05 - duration_gap * 0.2
            out.append(ExchangeProposal(r.request_id, give.slot_id, c.slot_id, score))
    return sorted(out, key=lambda p: (-p.score, p.request_id, p.take_slot))

def choose_disjoint(proposals_: list[ExchangeProposal]):
    used = set()
    chosen = []
    for p in proposals_:
        if p.give_slot in used or p.take_slot in used:
            continue
        chosen.append(p)
        used.add(p.give_slot)
        used.add(p.take_slot)
    return chosen

def apply(slots: list[PathSlot], chosen: list[ExchangeProposal]):
    sm = {s.slot_id: s for s in slots}
    swaps = {}
    for p in chosen:
        if p.give_slot not in sm or p.take_slot not in sm:
            raise ValueError('unknown slot')
        a = sm[p.give_slot]
        b = sm[p.take_slot]
        if a.locked or b.locked:
            raise ValueError('locked slot')
        if a.slot_id in swaps or b.slot_id in swaps:
            raise ValueError('non-disjoint exchange')
        swaps[a.slot_id] = replace(a, owner=b.owner)
        swaps[b.slot_id] = replace(b, owner=a.owner)
    return [swaps.get(s.slot_id, s) for s in slots]
