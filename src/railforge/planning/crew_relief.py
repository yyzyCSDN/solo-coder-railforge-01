from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class ReliefPoint:
    point: str
    km: float
    hotel: bool
    road_access: bool

@dataclass(frozen=True)
class DutyForecast:
    current_km: float
    remaining_duty_hours: float
    speed_kmh: float
    required_rest: bool

def choose(points: list[ReliefPoint], forecast: DutyForecast, dwell_hours: float):
    if forecast.speed_kmh <= 0 or forecast.remaining_duty_hours < 0:
        raise ValueError('forecast')
    options = []
    for p in points:
        if p.km < forecast.current_km or not p.road_access:
            continue
        travel = (p.km - forecast.current_km) / forecast.speed_kmh
        if travel + dwell_hours <= forecast.remaining_duty_hours and (not forecast.required_rest or p.hotel):
            options.append((forecast.remaining_duty_hours - travel - dwell_hours, p.km, p.point))
    if not options:
        raise ValueError('no legal relief point')
    return min(options)[2]
