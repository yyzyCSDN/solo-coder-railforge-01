from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal

@dataclass(frozen=True)
class SlotExchangeEntry:
    account: str
    reference: str
    amount: Decimal
    category: str
    reverses: str | None = None

def validate(entries: list[SlotExchangeEntry]):
    refs = set()
    original = {}
    for e in entries:
        key = (e.account, e.reference)
        if key in refs:
            raise ValueError('duplicate reference')
        refs.add(key)
        original[e.reference] = e
        if e.reverses is not None and e.reverses not in original:
            raise ValueError('orphan reversal')
    return True

def balance(entries, account=None):
    return sum((e.amount for e in entries if account is None or e.account == account), Decimal(0))

def by_category(entries):
    out = {}
    for e in entries:
        out[e.category] = out.get(e.category, Decimal(0)) + e.amount
    return out

def reconcile(entries, expected):
    actual = by_category(entries)
    keys = set(actual) | set(expected)
    return {k: actual.get(k, Decimal(0)) - expected.get(k, Decimal(0)) for k in keys}
