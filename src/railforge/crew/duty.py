from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

@dataclass(frozen=True)
class DutySegment:
    start: datetime
    end: datetime
    driving: bool

def totals(rows: list[DutySegment]):
    ordered = sorted(rows, key=lambda r: r.start)
    total = drive = 0.0
    last = None
    for r in ordered:
        s = r.start.astimezone(timezone.utc)
        e = r.end.astimezone(timezone.utc)
        if e <= s:
            raise ValueError('segment')
        if last is not None and s < last:
            raise ValueError('overlap')
        hours = (e - s).total_seconds() / 3600
        total += hours
        if r.driving:
            drive += hours
        last = e
    span = 0.0 if not ordered else (ordered[-1].end.astimezone(timezone.utc) - ordered[0].start.astimezone(timezone.utc)).total_seconds() / 3600
    return (total, drive, span)

def legal(rows, max_duty, max_drive, max_span):
    total, drive, span = totals(rows)
    return total <= max_duty and drive <= max_drive and (span <= max_span)
