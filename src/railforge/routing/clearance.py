from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Segment:
    id: str
    max_height_m: float
    max_width_m: float
    max_gross_t: float
    max_axle_t: float

@dataclass(frozen=True)
class TrainProfile:
    height_m: float
    width_m: float
    gross_t: float
    max_axle_t: float

def route_ok(profile: TrainProfile, segments: list[Segment]) -> bool:
    return all((profile.height_m <= s.max_height_m and profile.width_m <= s.max_width_m and (profile.gross_t <= s.max_gross_t) and (profile.max_axle_t <= s.max_axle_t) for s in segments))
