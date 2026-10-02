from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import hypot

@dataclass(frozen=True)
class WindSample:
    bridge: str
    at: datetime
    east_m_s: float
    north_m_s: float
    gust_m_s: float
    quality: float = 1.0

@dataclass(frozen=True)
class BridgeWindRule:
    bridge: str
    warning_m_s: float
    stop_m_s: float
    crosswind_factor: float

def recent_peak(samples: list[WindSample], bridge: str, at: datetime, span: timedelta) -> tuple[float, float] | None:
    x = at.astimezone(timezone.utc)
    start = x - span
    values = []
    for sample in samples:
        t = sample.at.astimezone(timezone.utc)
        if sample.bridge != bridge or sample.quality <= 0 or (not start < t <= x):
            continue
        sustained = hypot(sample.east_m_s, sample.north_m_s)
        values.append((sustained, sample.gust_m_s, sample.quality))
    if not values:
        return None
    sustained = max((v[0] * v[2] for v in values))
    gust = max((v[1] * v[2] for v in values))
    return (sustained, gust)

def operating_state(samples: list[WindSample], rule: BridgeWindRule, at: datetime, span: timedelta) -> str:
    if not 0 < rule.warning_m_s < rule.stop_m_s or not 0 < rule.crosswind_factor <= 1:
        raise ValueError('invalid bridge wind rule')
    peak = recent_peak(samples, rule.bridge, at, span)
    if peak is None:
        return 'unknown'
    sustained, gust = peak
    effective = max(sustained * rule.crosswind_factor, gust)
    if effective >= rule.stop_m_s:
        return 'stop'
    if effective >= rule.warning_m_s:
        return 'restrict'
    return 'normal'

def fleet_states(samples: list[WindSample], rules: list[BridgeWindRule], at: datetime, span: timedelta) -> dict[str, str]:
    return {r.bridge: operating_state(samples, r, at, span) for r in rules}
