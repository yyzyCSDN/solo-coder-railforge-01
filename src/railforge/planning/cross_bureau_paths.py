from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

# Machine-readable rejection reasons, kept stable for cross-bureau consumers.
SINGLE_TRACK_MEET = "single_track_meet"
CAPACITY_EXCEEDED = "capacity_exceeded"
WINDOW_INFEASIBLE = "window_infeasible"
STALE_VERSION = "stale_version"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True)
class CorridorSection:
    section_id: str
    bureau: str
    run_minutes: int
    single_track: bool
    capacity_per_hour: int


@dataclass(frozen=True)
class PathRequest:
    request_id: str
    train: str
    window_start: datetime          # customer window: earliest departure
    window_end: datetime            # customer window: latest arrival
    sections: tuple[str, ...]       # ordered corridor sections, may span bureaus
    priority: int                   # higher priority is planned first
    direction: int                  # +1 / -1, drives single-track meet detection
    expected_version: int | None = None   # optimistic concurrency on the corridor plan
    dwell_minutes: int = 0          # interchange dwell applied at a bureau boundary


@dataclass(frozen=True)
class Occupancy:
    train: str
    section: str
    start: datetime
    end: datetime
    direction: int


@dataclass(frozen=True)
class Slot:
    request_id: str
    train: str
    section: str
    bureau: str
    start: datetime
    end: datetime
    direction: int


@dataclass(frozen=True)
class CandidatePath:
    request_id: str
    train: str
    slots: tuple[Slot, ...]
    departure: datetime
    arrival: datetime
    delay_minutes: int


@dataclass(frozen=True)
class Rejection:
    request_id: str
    reason: str
    detail: str
    section: str | None = None
    conflicting_trains: tuple[str, ...] = ()


@dataclass(frozen=True)
class PathOutcome:
    request_id: str
    decision: str                   # "accepted" | "rejected"
    candidate: CandidatePath | None
    rejection: Rejection | None
    version: int

    @staticmethod
    def accepted(candidate: CandidatePath, version: int) -> "PathOutcome":
        return PathOutcome(candidate.request_id, "accepted", candidate, None, version)

    @staticmethod
    def rejected(rejection: Rejection, version: int) -> "PathOutcome":
        return PathOutcome(rejection.request_id, "rejected", None, rejection, version)


@dataclass(frozen=True)
class CorridorState:
    """Committed corridor plan: occupied slots plus the request->operation decisions."""
    corridor_id: str
    slots: tuple[Slot, ...] = ()
    decisions: tuple[tuple[str, str], ...] = ()   # (request_id, operation_id)


@dataclass(frozen=True)
class _Failure:
    section: str
    reason: str
    trains: tuple[str, ...]


def _overlap(a_start, a_end, b_start, b_end) -> bool:
    return max(a_start, b_start) < min(a_end, b_end)


def _conflicts(section: CorridorSection, start, end, direction, occupied, headway):
    """Return (blocking, meets): trains that block the slot, and the subset that is an
    opposing-direction meet on a single-track section."""
    blocking = set()
    meets = set()
    for occ in occupied:
        if occ.section != section.section_id:
            continue
        guard_start = _utc(occ.start) - headway
        guard_end = _utc(occ.end) + headway
        if not _overlap(start, end, guard_start, guard_end):
            continue
        if section.single_track:
            blocking.add(occ.train)
            if occ.direction != direction:
                meets.add(occ.train)
        elif occ.direction == direction:
            blocking.add(occ.train)
    return blocking, meets


def _capacity_ok(section: CorridorSection, start, occupied, train) -> bool:
    horizon = start + timedelta(hours=1)
    count = 0
    for occ in occupied:
        if occ.section != section.section_id or occ.train == train:
            continue
        if _overlap(start, horizon, _utc(occ.start), _utc(occ.end)):
            count += 1
    return count < section.capacity_per_hour


def _conflict_free_arrival(request: PathRequest, sections, departure):
    at = departure
    bureau = None
    for sid in request.sections:
        section = sections[sid]
        if bureau is not None and section.bureau != bureau:
            at += timedelta(minutes=request.dwell_minutes)
        bureau = section.bureau
        at += timedelta(minutes=section.run_minutes)
    return at


def _schedule(request: PathRequest, sections, occupied, departure, headway, window_end):
    """Lay slots from `departure`, waiting out conflicts. Returns (slots, None) or
    (None, _Failure) describing the binding constraint when the window is exhausted."""
    slots = []
    start = departure
    bureau = None
    busy = list(occupied)
    for sid in request.sections:
        section = sections[sid]
        if bureau is not None and section.bureau != bureau:
            start += timedelta(minutes=request.dwell_minutes)
        bureau = section.bureau
        run = timedelta(minutes=section.run_minutes)
        meet_trains: set[str] = set()
        capacity_blocked = False
        while True:
            end = start + run
            if end > window_end:
                if meet_trains:
                    return None, _Failure(sid, SINGLE_TRACK_MEET, tuple(sorted(meet_trains)))
                if capacity_blocked:
                    return None, _Failure(sid, CAPACITY_EXCEEDED, ())
                return None, _Failure(sid, WINDOW_INFEASIBLE, ())
            blocking, meets = _conflicts(section, start, end, request.direction, busy, headway)
            cap_ok = _capacity_ok(section, start, busy, request.train)
            if not blocking and cap_ok:
                break
            if meets:
                meet_trains |= meets
            elif not cap_ok:
                capacity_blocked = True
            start += timedelta(minutes=1)
        slot = Slot(request.request_id, request.train, sid, section.bureau, start, end,
                    request.direction)
        slots.append(slot)
        busy.append(Occupancy(request.train, sid, start, end, request.direction))
        start = end
    return tuple(slots), None


def request_order(requests):
    """Deterministic planning order: priority first, then earliest window, then id."""
    return sorted(requests, key=lambda r: (-r.priority, _utc(r.window_start), r.request_id))


def generate_candidates(request: PathRequest, sections, occupied, headway_minutes,
                        limit: int = 3, step_minutes: int = 15):
    """Generate up to `limit` candidate paths from the customer window, section capacity,
    block occupancy and priority context, earliest first."""
    if headway_minutes < 0:
        raise ValueError("headway")
    if limit < 1:
        raise ValueError("limit")
    if step_minutes < 1:
        raise ValueError("step")
    start_window = _utc(request.window_start)
    end_window = _utc(request.window_end)
    if end_window <= start_window:
        raise ValueError("customer window")
    if not request.sections:
        raise ValueError("sections")
    for sid in request.sections:
        if sid not in sections:
            raise KeyError(f"unknown section: {sid}")
    headway = timedelta(minutes=headway_minutes)
    step = timedelta(minutes=step_minutes)
    candidates = []
    departure = start_window
    while _conflict_free_arrival(request, sections, departure) <= end_window:
        slots, _ = _schedule(request, sections, occupied, departure, headway, end_window)
        if slots is not None:
            actual = slots[0].start
            arrival = slots[-1].end
            delay = int((actual - start_window).total_seconds() // 60)
            candidates.append(CandidatePath(request.request_id, request.train, slots,
                                            actual, arrival, delay))
            if len(candidates) >= limit:
                break
            departure = actual + step
        else:
            departure += step
    return candidates


def explain_rejection(request: PathRequest, sections, occupied, headway_minutes) -> Rejection:
    """Explain why no candidate fits: single-track meet, capacity, or window."""
    start_window = _utc(request.window_start)
    end_window = _utc(request.window_end)
    headway = timedelta(minutes=headway_minutes)
    earliest = _conflict_free_arrival(request, sections, start_window)
    if earliest > end_window:
        return Rejection(
            request.request_id, WINDOW_INFEASIBLE,
            f"customer window too short: earliest possible arrival {earliest.isoformat()} "
            f"exceeds window end {end_window.isoformat()}")
    _, failure = _schedule(request, sections, occupied, start_window, headway, end_window)
    if failure is None:
        return Rejection(request.request_id, WINDOW_INFEASIBLE,
                         "no feasible path within customer window")
    if failure.reason == SINGLE_TRACK_MEET:
        detail = (f"single-track section {failure.section}: cannot clear opposing train(s) "
                  f"{', '.join(failure.trains)} within customer window")
    elif failure.reason == CAPACITY_EXCEEDED:
        detail = f"section {failure.section}: hourly capacity exhausted within customer window"
    else:
        detail = f"section {failure.section}: cannot be traversed within customer window"
    return Rejection(request.request_id, failure.reason, detail,
                     failure.section, failure.trains)


def evaluate(request: PathRequest, sections, occupied, headway_minutes, limit: int = 3):
    """Best candidate path, or an explainable rejection when none fits."""
    candidates = generate_candidates(request, sections, occupied, headway_minutes, limit)
    if candidates:
        return candidates[0]
    return explain_rejection(request, sections, occupied, headway_minutes)


def plan_batch(requests, sections, occupied, headway_minutes, limit: int = 3):
    """Plan many requests in priority order against shared occupancy.
    Returns (accepted: dict[request_id, CandidatePath], rejected: list[Rejection])."""
    busy = list(occupied)
    accepted = {}
    rejected = []
    for req in request_order(requests):
        outcome = evaluate(req, sections, busy, headway_minutes, limit)
        if isinstance(outcome, CandidatePath):
            accepted[req.request_id] = outcome
            for slot in outcome.slots:
                busy.append(Occupancy(slot.train, slot.section, slot.start, slot.end,
                                      slot.direction))
        else:
            rejected.append(outcome)
    return accepted, rejected
