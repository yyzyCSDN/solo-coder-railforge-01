from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class WagonLink:
    position: int
    wagon: str
    previous: str | None
    next: str | None
    brake_connected: bool

def validate(rows: list[WagonLink]) -> tuple[str, str]:
    if not rows:
        raise ValueError('empty consist')
    ordered = sorted(rows, key=lambda r: r.position)
    if [r.position for r in ordered] != list(range(1, len(ordered) + 1)):
        raise ValueError('position gap')
    ids = [r.wagon for r in ordered]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate wagon')
    for i, r in enumerate(ordered):
        expected_prev = None if i == 0 else ordered[i - 1].wagon
        expected_next = None if i == len(ordered) - 1 else ordered[i + 1].wagon
        if r.previous != expected_prev or r.next != expected_next:
            raise ValueError('inconsistent consist chain')
        if not r.brake_connected:
            raise ValueError('brake pipe discontinuity')
    return (ordered[0].wagon, ordered[-1].wagon)
