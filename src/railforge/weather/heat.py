from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median

@dataclass(frozen=True)
class HeatObservation:
    entity: str
    at: datetime
    value: float
    quality: float = 1.0

def window(rows: list[HeatObservation], entity: str, at: datetime, span: timedelta):
    x = at.astimezone(timezone.utc)
    start = x - span
    return [r for r in rows if r.entity == entity and start < r.at.astimezone(timezone.utc) <= x and (r.quality > 0)]

def weighted_mean(rows):
    den = sum((r.quality for r in rows))
    return None if den <= 0 else sum((r.value * r.quality for r in rows)) / den

def robust_center(rows):
    return None if not rows else median((r.value for r in rows))

def anomaly(rows, entity, at, span, threshold):
    xs = window(rows, entity, at, span)
    center = robust_center(xs)
    if center is None:
        return []
    deviations = [abs(r.value - center) for r in xs]
    scale = median(deviations) or 1e-09
    return [r for r in xs if abs(r.value - center) / scale > threshold]
