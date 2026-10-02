from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Load:
    wagon: str
    group: str
    position: int

def violations(rows: list[Load], forbidden_distance: dict[frozenset[str], int]):
    out = []
    xs = sorted(rows, key=lambda r: r.position)
    for i, a in enumerate(xs):
        for b in xs[i + 1:]:
            key = frozenset({a.group, b.group})
            required = forbidden_distance.get(key)
            if required is None:
                continue
            actual = abs(a.position - b.position) - 1
            if actual < required:
                out.append((a.wagon, b.wagon, required, actual))
    return out
