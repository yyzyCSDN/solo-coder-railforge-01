from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal

@dataclass(frozen=True)
class Booking:
    booking_id: str
    customer: str
    units: int
    base_rate: Decimal
    priority: int
    guaranteed: bool

@dataclass(frozen=True)
class CapacityBand:
    units: int
    minimum_rate: Decimal

def accept(bookings: list[Booking], bands: list[CapacityBand], total_capacity: int):
    if total_capacity < 0:
        raise ValueError('capacity')
    accepted = []
    rejected = []
    used = 0

    def floor_for(next_units):
        cumulative = 0
        for b in bands:
            cumulative += b.units
            if next_units <= cumulative:
                return b.minimum_rate
        return bands[-1].minimum_rate if bands else Decimal(0)
    ordered = sorted(bookings, key=lambda b: (not b.guaranteed, -b.priority, -b.base_rate, b.booking_id))
    for b in ordered:
        if b.units <= 0:
            raise ValueError('booking units')
        if used + b.units > total_capacity:
            rejected.append((b.booking_id, 'capacity'))
            continue
        floor = floor_for(used + b.units)
        if not b.guaranteed and b.base_rate < floor:
            rejected.append((b.booking_id, 'rate'))
            continue
        accepted.append(b.booking_id)
        used += b.units
    return (accepted, rejected, used)
