"""Cross-bureau freight path coordination.

Given customer time windows, section capacity, block (signal) occupancies and
train priority, candidate paths are generated as one-minute departure shifts.
A request is either accepted with the first feasible candidate or rejected
with an explainable :class:`Rejection` that names the blocking trains, the
offending sections and the reason code.

The :class:`PathLedger` is the optimistic-concurrency state that remembers
which sections each committed plan occupies, guarded by a version number so
that requests based on a stale planning version cannot double-book sections.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import NamedTuple, Sequence

# --- Explainable rejection reason codes -----------------------------------

SINGLE_TRACK_MEET = "SINGLE_TRACK_MEET"
SECTION_CAPACITY = "SECTION_CAPACITY"
BLOCK_OCCUPIED = "BLOCK_OCCUPIED"
WINDOW_MISSED = "WINDOW_MISSED"
DELAY_TOLERANCE = "DELAY_TOLERANCE"
STALE_VERSION = "STALE_VERSION"
UNKNOWN_SECTION = "UNKNOWN_SECTION"
BUREAU_HANDOFF = "BUREAU_HANDOFF"

#: Precedence used when several problems occur on one departure.
REASON_ORDER: tuple[str, ...] = (
    UNKNOWN_SECTION,
    SINGLE_TRACK_MEET,
    SECTION_CAPACITY,
    BLOCK_OCCUPIED,
    WINDOW_MISSED,
    DELAY_TOLERANCE,
    BUREAU_HANDOFF,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _overlap(a_start: datetime, a_end: datetime,
             b_start: datetime, b_end: datetime) -> bool:
    return max(a_start, b_start) < min(a_end, b_end)


# --- Domain values ---------------------------------------------------------

@dataclass(frozen=True)
class BureauSection:
    """A line section belonging to one railway bureau (railroad)."""

    section_id: str
    bureau: str
    run_minutes: int
    single_track: bool
    capacity_per_hour: int

    def __post_init__(self):
        if self.run_minutes <= 0:
            raise ValueError("run_minutes must be positive")
        if self.capacity_per_hour <= 0:
            raise ValueError("capacity_per_hour must be positive")


@dataclass(frozen=True)
class Traversal:
    train: str
    section: str
    bureau: str
    start: datetime
    end: datetime
    direction: int
    request_id: str

    def overlaps(self, other_start: datetime, other_end: datetime) -> bool:
        return _overlap(
            _utc(self.start), _utc(self.end),
            _utc(other_start), _utc(other_end),
        )


@dataclass(frozen=True)
class CandidatePath:
    """One concrete departure proposal (a one-minute shift of the request)."""

    request_id: str
    train: str
    delay_minutes: int
    traversals: tuple[Traversal, ...]
    bureaus: tuple[str, ...]
    handoffs: tuple[tuple[str, str], ...]
    arrives_at: datetime

    @property
    def ready_at(self) -> datetime:
        return self.traversals[0].start


@dataclass(frozen=True)
class Rejection:
    """Explainable refusal."""

    request_id: str
    train: str
    reason: str
    sections: tuple[str, ...]
    blocking_trains: tuple[str, ...]
    detail: str
    expected_version: int | None = None
    actual_version: int | None = None
    latest_departure: datetime | None = None

    def explain(self) -> str:
        head = f"{self.train} rejected ({self.reason})"
        parts = [head, self.detail]
        if self.sections:
            parts.append("sections=" + ",".join(self.sections))
        if self.blocking_trains:
            parts.append("blocking=" + ",".join(self.blocking_trains))
        return "; ".join(parts)


@dataclass(frozen=True)
class Decision:
    accepted: bool
    request_id: str
    train: str
    candidate: CandidatePath | None = None
    rejection: Rejection | None = None

    @property
    def path(self) -> CandidatePath | None:
        return self.candidate


@dataclass(frozen=True)
class CoordinationRequest:
    request_id: str
    train: str
    ready_at: datetime
    due_at: datetime
    sections: tuple[str, ...]
    direction: int = 1
    priority: int = 0
    max_delay_minutes: int = 0
    expected_version: int | None = None


# --- Committed section ledger ---------------------------------------------

class CommitError(RuntimeError):
    """Raised when a candidate cannot be committed to the ledger."""


@dataclass
class LedgerSnapshot:
    version: int
    traversals: tuple[Traversal, ...]


class PathLedger:
    """Versioned record of every section occupied by a committed plan.

    ``add`` is an optimistic check-and-commit: it refuses either when the
    caller built its candidate on an outdated version, or when the candidate
    would collide with a traversal committed in the meantime.
    """

    def __init__(self):
        self._lock = RLock()
        self._version = 0
        self._traversals: list[Traversal] = []
        self._request_ids: set[str] = set()

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def snapshot(self) -> LedgerSnapshot:
        with self._lock:
            return LedgerSnapshot(self._version, tuple(self._traversals))

    def restore(self, snapshot: LedgerSnapshot) -> None:
        with self._lock:
            self._version = snapshot.version
            self._traversals = list(snapshot.traversals)
            self._request_ids = {t.request_id for t in self._traversals}

    def contains_request(self, request_id: str) -> bool:
        with self._lock:
            return request_id in self._request_ids

    def traversals_for(self, request_id: str) -> tuple[Traversal, ...]:
        with self._lock:
            return tuple(t for t in self._traversals if t.request_id == request_id)

    def add(self, candidate: CandidatePath, expected_version: int | None = None,
            guard_minutes: int = 0) -> int:
        with self._lock:
            if candidate.request_id in self._request_ids:
                raise CommitError(
                    f"request {candidate.request_id} already committed; "
                    "replay must not occupy sections twice"
                )
            if expected_version is not None and expected_version != self._version:
                raise CommitError(
                    f"version conflict: expected={expected_version} actual={self._version}"
                )
            for traversal in candidate.traversals:
                guard = timedelta(minutes=max(0, guard_minutes))
                for held in self._traversals:
                    if held.section != traversal.section:
                        continue
                    if _overlap(_utc(traversal.start) - guard,
                                _utc(traversal.end) + guard,
                                _utc(held.start), _utc(held.end)):
                        raise CommitError(
                            f"section {traversal.section} already occupied by {held.train}"
                        )
            self._traversals.extend(candidate.traversals)
            self._request_ids.add(candidate.request_id)
            self._version += 1
            return self._version


# --- Candidate generation --------------------------------------------------

class _Row(NamedTuple):
    train: str
    section: str
    start: datetime
    end: datetime
    direction: int


def _rows(occupancies: Sequence[_Row | Traversal]) -> list[_Row]:
    out: list[_Row] = []
    for row in occupancies:
        end = _utc(row.end)
        start = _utc(row.start)
        if end <= start:
            raise ValueError("occupancy interval must end after it starts")
        out.append(_Row(row.train, row.section, start, end, int(row.direction)))
    return out


def _build_candidate(request: CoordinationRequest, sections,
                     departure: datetime) -> tuple[CandidatePath | None, str | None]:
    start = _utc(departure)
    traversals: list[Traversal] = []
    bureaus: list[str] = []
    handoffs: list[tuple[str, str]] = []
    cursor = start
    for sid in request.sections:
        section = sections.get(sid)
        if section is None:
            return None, UNKNOWN_SECTION
        end = cursor + timedelta(minutes=section.run_minutes)
        traversals.append(Traversal(
            train=request.train, section=sid, bureau=section.bureau,
            start=cursor, end=end, direction=request.direction,
            request_id=request.request_id,
        ))
        if not bureaus or bureaus[-1] != section.bureau:
            if bureaus:
                handoffs.append((bureaus[-1], section.bureau))
            bureaus.append(section.bureau)
        cursor = end
    return CandidatePath(
        request_id=request.request_id,
        train=request.train,
        delay_minutes=int((start - _utc(request.ready_at)).total_seconds() // 60),
        traversals=tuple(traversals),
        bureaus=tuple(bureaus),
        handoffs=tuple(handoffs),
        arrives_at=cursor,
    ), None


def _evaluate(traversal: Traversal, section: BureauSection,
              occupied_rows: list[_Row], guard_minutes: int
              ) -> tuple[set[str], set[str]]:
    """Return reason codes and blocking trains that make a traversal infeasible."""
    reasons: set[str] = set()
    blockers: set[str] = set()
    guard = timedelta(minutes=max(0, guard_minutes))
    window_start = _utc(traversal.start) - guard
    window_end = _utc(traversal.end) + guard
    for row in occupied_rows:
        if row.section != traversal.section or row.train == traversal.train:
            continue
        opposing = row.direction != traversal.direction
        hard_overlap = _overlap(_utc(traversal.start), _utc(traversal.end),
                                row.start, row.end)
        guard_overlap = _overlap(window_start, window_end, row.start, row.end)
        if section.single_track:
            # One rail serves both directions: any hard overlap blocks; an
            # opposing overlap is the explainable head-on meet. Same-direction
            # guard-only overlap is the headway follower case.
            if hard_overlap:
                if opposing:
                    reasons.add(SINGLE_TRACK_MEET)
                reasons.add(BLOCK_OCCUPIED)
                blockers.add(row.train)
            elif guard_overlap:
                reasons.add(BLOCK_OCCUPIED)
                blockers.add(row.train)
        elif guard_overlap and not opposing:
            # Double track: opposing trains run the other rail, same-direction
            # followers still need the headway guard.
            reasons.add(BLOCK_OCCUPIED)
            blockers.add(row.train)
    # Capacity: trains entering the section within the same hour window as
    # our entry (the hour starting at our entry), regardless of direction.
    hour_end = _utc(traversal.start) + timedelta(hours=1)
    entries = [
        row for row in occupied_rows
        if row.section == traversal.section
        and row.train != traversal.train
        and _utc(traversal.start) <= row.start < hour_end
    ]
    if len(entries) >= section.capacity_per_hour:
        reasons.add(SECTION_CAPACITY)
        blockers.update(row.train for row in entries)
    return reasons, blockers


def generate_candidates(request: CoordinationRequest, sections,
                        occupancies: Sequence[_Row | Traversal],
                        guard_minutes: int = 0,
                        max_candidates: int | None = None,
                        ledger: PathLedger | None = None
                        ) -> tuple[list[CandidatePath], dict[int, Rejection]]:
    """Enumerate feasible departure shifts.

    Returns the feasible candidates (delay order) and a mapping of rejected
    departure offsets to their explainable rejection.
    """
    if request.due_at <= request.ready_at:
        raise ValueError("due_at must be after ready_at")
    if request.direction not in (-1, 1):
        raise ValueError("direction must be 1 or -1")
    if guard_minutes < 0:
        raise ValueError("guard_minutes must be non-negative")
    limit = request.max_delay_minutes if max_candidates is None else min(
        request.max_delay_minutes, max_candidates)
    occupied = _rows(list(occupancies) +
                     (list(ledger.snapshot().traversals) if ledger else []))

    feasible: list[CandidatePath] = []
    rejected: dict[int, Rejection] = {}
    for offset in range(limit + 1):
        departure = _utc(request.ready_at) + timedelta(minutes=offset)
        candidate, build_error = _build_candidate(request, sections, departure)
        if build_error == UNKNOWN_SECTION:
            unknown_sections = tuple(s for s in request.sections if s not in sections)
            rejected[offset] = Rejection(
                request.request_id, request.train, UNKNOWN_SECTION,
                unknown_sections, (),
                "section is not defined in the network reference",
            )
            continue
        assert candidate is not None

        reason_sets: list[set[str]] = []
        blockers: set[str] = set()
        for traversal in candidate.traversals:
            section = sections[traversal.section]
            rs, row_blockers = _evaluate(traversal, section, occupied, guard_minutes)
            reason_sets.append(rs)
            blockers.update(row_blockers)

        if _utc(candidate.arrives_at) > _utc(request.due_at):
            for rs, sid in zip(reason_sets, request.sections):
                if not rs:
                    rs.add(WINDOW_MISSED)

        codes = [c for c in REASON_ORDER if any(c in rs for rs in reason_sets)]
        if codes:
            reason = codes[0]
            hit = tuple(sid for sid, rs in zip(request.sections, reason_sets) if reason in rs)
            if not hit and reason == WINDOW_MISSED:
                hit = (request.sections[-1],)
            rejected[offset] = Rejection(
                request.request_id, request.train, reason, hit,
                tuple(sorted(blockers)),
                _detail(reason, request, offset, hit),
                latest_departure=departure,
            )
            continue
        feasible.append(candidate)

    return feasible, rejected


def _detail(reason: str, request: CoordinationRequest, offset: int,
            sections_hit: tuple[str, ...]) -> str:
    if reason == SINGLE_TRACK_MEET:
        return ("opposing trains would meet on single track; "
                "schedule a siding pass or reorder by priority")
    if reason == SECTION_CAPACITY:
        return "section entries in the same departure hour already reach capacity"
    if reason == BLOCK_OCCUPIED:
        return "block occupancy overlaps the requested traversal"
    if reason == WINDOW_MISSED:
        return "even this departure arrives after the customer due window"
    if reason == DELAY_TOLERANCE:
        return (f"no feasible departure within {request.max_delay_minutes} "
                f"minutes of ready time")
    if reason == UNKNOWN_SECTION:
        return "section is not defined in the network reference"
    if reason == BUREAU_HANDOFF:
        return "cross-bureau handoff cannot be agreed at this time"
    return reason


def coordinate(request: CoordinationRequest, sections,
               occupancies: Sequence[_Row | Traversal] = (),
               guard_minutes: int = 0,
               ledger: PathLedger | None = None,
               ledger_version: int | None = None) -> Decision:
    """Decide one request: accept the earliest candidate or explain refusal.

    ``ledger_version`` defaults to the request's ``expected_version``; when
    the supplied ledger is already past that version the request is rejected
    with :data:`STALE_VERSION` before any section is examined.
    """
    if ledger is not None:
        expected = ledger_version if ledger_version is not None else request.expected_version
        if expected is not None and expected != ledger.version:
            return Decision(
                accepted=False,
                request_id=request.request_id,
                train=request.train,
                rejection=Rejection(
                    request.request_id, request.train, STALE_VERSION, (), (),
                    (f"planning version {expected} is stale; current version is "
                     f"{ledger.version}; refetch before retrying"),
                    expected_version=expected,
                    actual_version=ledger.version,
                ),
            )

    feasible, rejected = generate_candidates(
        request, sections, occupancies, guard_minutes, ledger=ledger,
    )
    if feasible:
        return Decision(True, request.request_id, request.train,
                        candidate=feasible[0])
    if request.max_delay_minutes < 0:
        raise ValueError("max_delay_minutes must be non-negative")
    if not rejected:
        raise ValueError("request produced neither candidates nor rejections")
    earliest = min(rejected)
    first = rejected[earliest]
    # A problem at the earliest possible departure is structural: waiting
    # cannot help unless a later departure was already shown feasible above.
    # SINGLE_TRACK_MEET / capacity / unknown section keep their code; a plain
    # same-direction block is framed as exceeding the delay tolerance.
    if first.reason == WINDOW_MISSED:
        return Decision(False, request.request_id, request.train, rejection=first)
    if first.reason == BLOCK_OCCUPIED:
        reason = DELAY_TOLERANCE
        detail = _detail(DELAY_TOLERANCE, request, earliest, first.sections)
    else:
        reason = first.reason
        detail = first.detail
    return Decision(False, request.request_id, request.train,
                    rejection=Rejection(
                        first.request_id, first.train, reason,
                        first.sections, first.blocking_trains, detail,
                        latest_departure=first.latest_departure,
                    ))


def batch_coordinate(requests: Sequence[CoordinationRequest], sections,
                     occupancies: Sequence[_Row | Traversal] = (),
                     guard_minutes: int = 0,
                     ledger: PathLedger | None = None) -> list[Decision]:
    """Coordinate many requests together, priority first.

    Higher ``priority`` wins; ties break by ready time then train/request id.
    Accepted candidates occupy the (in-memory) ledger for the requests that
    follow, so a lower-priority train is refused against the higher one
    instead of silently double-booking the section.
    """
    ledger = ledger if ledger is not None else PathLedger()
    decisions: list[Decision] = []
    ordered = sorted(
        requests,
        key=lambda r: (-r.priority, _utc(r.ready_at), r.train, r.request_id),
    )
    for request in ordered:
        decision = coordinate(request, sections, occupancies, guard_minutes,
                              ledger=ledger)
        if decision.accepted and decision.candidate is not None:
            ledger.add(decision.candidate)
        decisions.append(decision)
    by_id = {d.request_id: d for d in decisions}
    return [by_id[r.request_id] for r in requests]
