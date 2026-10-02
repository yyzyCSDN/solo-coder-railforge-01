from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from railforge.signaling.block_occupancy import Occupancy, conflicts
from railforge.crew.duty import DutySegment, legal
from railforge.routing.clearance import TrainProfile, Segment, route_ok

@dataclass(frozen=True)
class DispatchCheck:
    train: str
    block_conflicts: tuple[str, ...]
    crew_legal: bool
    route_clear: bool
    reasons: tuple[str, ...]

def dispatch_check(train: str, occupancy: Occupancy, existing: list[Occupancy], clearance: timedelta, duty: list[DutySegment], duty_limits: tuple[float, float, float], profile: TrainProfile, route: list[Segment]):
    block = tuple(conflicts(occupancy, existing, clearance))
    crew_ok = legal(duty, *duty_limits)
    clear = route_ok(profile, route)
    reasons = []
    if block:
        reasons.append('block_conflict')
    if not crew_ok:
        reasons.append('crew_limit')
    if not clear:
        reasons.append('route_clearance')
    return DispatchCheck(train, block, crew_ok, clear, tuple(reasons))

def dispatchable(check: DispatchCheck):
    return not check.reasons
