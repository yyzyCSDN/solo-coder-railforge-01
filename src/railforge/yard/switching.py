from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Switch:
    id: str
    position: str
    locked_by: str | None = None

@dataclass(frozen=True)
class Route:
    id: str
    requirements: dict[str, str]

def can_set(route: Route, switches: dict[str, Switch], owner: str) -> bool:
    for sid, pos in route.requirements.items():
        s = switches[sid]
        if s.locked_by not in (None, owner):
            return False
        if s.position != pos:
            return False
    return True

def lock_route(route: Route, switches: dict[str, Switch], owner: str):
    if not can_set(route, switches, owner):
        raise ValueError('route unavailable')
    return {sid: Switch(s.id, s.position, owner if sid in route.requirements else s.locked_by) for sid, s in switches.items()}
