from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

@dataclass(frozen=True)
class Tariff:
    free_hours: float
    hourly: Decimal
    daily_cap: Decimal | None = None

def charge(arrival: datetime, release: datetime, t: Tariff) -> Decimal:
    a = arrival.astimezone(timezone.utc)
    r = release.astimezone(timezone.utc)
    if r < a or t.free_hours < 0 or t.hourly < 0:
        raise ValueError('tariff')
    bill = max(0.0, (r - a).total_seconds() / 3600 - t.free_hours)
    amount = t.hourly * Decimal(str(bill))
    if t.daily_cap is not None:
        import math
        amount = min(amount, t.daily_cap * Decimal(math.ceil(bill / 24)) if bill else Decimal(0))
    return amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
