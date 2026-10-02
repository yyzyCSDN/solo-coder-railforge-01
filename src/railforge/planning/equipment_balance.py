from __future__ import annotations
from dataclasses import dataclass, replace

@dataclass(frozen=True)
class EquipmentBalanceRequest:
    request_id: str
    group: str
    quantity: float
    priority: int
    attributes: frozenset[str] = frozenset()

@dataclass(frozen=True)
class EquipmentBalanceResource:
    resource_id: str
    group: str
    capacity: float
    reserved: float = 0.0
    attributes: frozenset[str] = frozenset()

def allocate(requests: list[EquipmentBalanceRequest], resources: list[EquipmentBalanceResource]):
    state = {r.resource_id: r for r in resources}
    result = {}
    for q in sorted(requests, key=lambda x: (-x.priority, -x.quantity, x.request_id)):
        if q.quantity <= 0:
            raise ValueError('quantity')
        choices = []
        for r in state.values():
            available = r.capacity - r.reserved
            if r.group != q.group or available < q.quantity or (not q.attributes.issubset(r.attributes)):
                continue
            choices.append((available - q.quantity, r.resource_id))
        if not choices:
            raise ValueError('insufficient equipment_balance capacity')
        _, rid = min(choices)
        r = state[rid]
        state[rid] = replace(r, reserved=r.reserved + q.quantity)
        result[q.request_id] = rid
    return (result, state)

def free_capacity(state):
    return {k: v.capacity - v.reserved for k, v in state.items()}

def overloaded(state):
    return sorted((k for k, v in state.items() if v.reserved > v.capacity))
