from __future__ import annotations
from dataclasses import dataclass, replace
from datetime import date

@dataclass(frozen=True)
class WheelsetStock:
    lot: str
    location: str
    quantity: float
    available_on: date
    expires_on: date | None = None
    quarantined: bool = False

def reserve(rows: list[WheelsetStock], location: str, on: date, quantity: float):
    if quantity <= 0:
        raise ValueError('quantity')
    xs = [r for r in rows if r.location == location and r.available_on <= on and (not r.quarantined) and (r.expires_on is None or r.expires_on > on) and (r.quantity > 0)]
    xs = sorted(xs, key=lambda r: (r.expires_on or date.max, r.available_on, r.lot))
    need = quantity
    out = []
    for r in xs:
        take = min(need, r.quantity)
        out.append((r.lot, take))
        need -= take
        if need <= 0:
            break
    if need > 1e-09:
        raise ValueError('insufficient wheelset stock')
    return out

def apply(rows: list[WheelsetStock], reservation: list[tuple[str, float]]):
    use = dict(reservation)
    out = []
    for r in rows:
        q = use.get(r.lot, 0.0)
        if q < 0 or q > r.quantity:
            raise ValueError('reservation')
        out.append(replace(r, quantity=r.quantity - q))
    return out

def available(rows, location, on):
    return sum((r.quantity for r in rows if r.location == location and r.available_on <= on and (not r.quarantined) and (r.expires_on is None or r.expires_on > on)))
