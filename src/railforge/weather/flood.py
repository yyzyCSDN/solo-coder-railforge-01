from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

@dataclass(frozen=True)
class FloodGauge:
    segment: str
    at: datetime
    water_level_m: float
    rail_head_clearance_m: float
    rise_rate_m_h: float
    quality: float = 1.0

@dataclass(frozen=True)
class FloodDecision:
    segment: str
    state: str
    margin_m: float
    projected_margin_m: float

def latest_by_segment(rows: list[FloodGauge], at: datetime, max_age: timedelta) -> dict[str, FloodGauge]:
    x = at.astimezone(timezone.utc)
    result = {}
    for row in rows:
        t = row.at.astimezone(timezone.utc)
        if row.quality <= 0 or t > x or x - t > max_age:
            continue
        prev = result.get(row.segment)
        if prev is None or t > prev.at.astimezone(timezone.utc):
            result[row.segment] = row
    return result

def assess(rows: list[FloodGauge], at: datetime, max_age: timedelta, horizon: timedelta, stop_margin_m: float, warning_margin_m: float) -> list[FloodDecision]:
    if stop_margin_m < 0 or warning_margin_m <= stop_margin_m or horizon.total_seconds() < 0:
        raise ValueError('invalid flood thresholds')
    latest = latest_by_segment(rows, at, max_age)
    decisions = []
    hours = horizon.total_seconds() / 3600
    for segment, row in latest.items():
        margin = row.rail_head_clearance_m - row.water_level_m
        projected = margin - max(0.0, row.rise_rate_m_h) * hours
        if projected <= stop_margin_m:
            state = 'stop'
        elif projected <= warning_margin_m:
            state = 'restrict'
        else:
            state = 'normal'
        decisions.append(FloodDecision(segment, state, margin, projected))
    return sorted(decisions, key=lambda d: (d.state != 'stop', d.state != 'restrict', d.projected_margin_m, d.segment))

def affected_segments(decisions: list[FloodDecision]) -> set[str]:
    return {d.segment for d in decisions if d.state != 'normal'}
