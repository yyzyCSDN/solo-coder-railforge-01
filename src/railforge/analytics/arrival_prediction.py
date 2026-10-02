from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median

@dataclass(frozen=True)
class Checkpoint:
    train: str
    location: str
    planned: datetime
    actual: datetime | None
    distance_remaining_km: float
    quality: float

@dataclass(frozen=True)
class Restriction:
    segment: str
    extra_minutes: float
    active: bool = True

def observed_delay(rows: list[Checkpoint]):
    vals = []
    for r in rows:
        if r.actual is None or r.quality <= 0:
            continue
        d = (r.actual.astimezone(timezone.utc) - r.planned.astimezone(timezone.utc)).total_seconds() / 60
        vals.extend([d] * max(1, int(round(r.quality * 4))))
    return 0.0 if not vals else median(vals)

def predict(planned_arrival: datetime, checkpoints: list[Checkpoint], restrictions: list[Restriction], recovery_rate_per_100km: float):
    delay = observed_delay(checkpoints)
    remaining = min((r.distance_remaining_km for r in checkpoints if r.actual is not None), default=0.0)
    recover = max(0.0, recovery_rate_per_100km) * (remaining / 100)
    restriction = sum((r.extra_minutes for r in restrictions if r.active))
    final = max(0.0, delay - recover) + restriction
    return planned_arrival.astimezone(timezone.utc) + timedelta(minutes=final)

def confidence(checkpoints: list[Checkpoint]):
    observed = [r for r in checkpoints if r.actual is not None and r.quality > 0]
    if not observed:
        return 0.0
    freshness = max((r.actual for r in observed)).astimezone(timezone.utc) - min((r.actual for r in observed)).astimezone(timezone.utc)
    quality = sum((r.quality for r in observed)) / len(observed)
    spread = min(1.0, freshness.total_seconds() / 21600)
    return max(0.05, min(0.99, quality * (1 - 0.35 * spread)))
