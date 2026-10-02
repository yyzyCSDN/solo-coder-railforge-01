from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

@dataclass(frozen=True)
class Observation:
    source: str
    event_time: datetime
    received_at: datetime
    delay_minutes: float
    quality: float
    sequence: int

def fused_delay(rows: list[Observation], max_lateness: timedelta) -> float:
    if not rows:
        return 0.0
    latest = max((r.event_time.astimezone(timezone.utc) for r in rows))
    cut = latest - max_lateness
    eligible = {}
    for r in rows:
        et = r.event_time.astimezone(timezone.utc)
        if et < cut or not 0 < r.quality <= 1:
            continue
        prev = eligible.get(r.source)
        if prev is None or (et, r.sequence) > (prev.event_time.astimezone(timezone.utc), prev.sequence):
            eligible[r.source] = r
    if not eligible:
        return 0.0
    den = sum((r.quality for r in eligible.values()))
    return sum((r.delay_minutes * r.quality for r in eligible.values())) / den
