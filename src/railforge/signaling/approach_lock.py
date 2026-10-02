from __future__ import annotations
from dataclasses import dataclass, replace

@dataclass(frozen=True)
class ApproachLockState:
    entity: str
    status: str = 'new'
    version: int = 0
    attributes: tuple[tuple[str, str], ...] = ()

@dataclass(frozen=True)
class ApproachLockEvent:
    entity: str
    sequence: int
    kind: str
    key: str = ''
    value: str = ''

def apply(state: ApproachLockState, event: ApproachLockEvent):
    if event.entity != state.entity or event.sequence != state.version + 1:
        raise ValueError('event sequence')
    attrs = dict(state.attributes)
    status = state.status
    if event.kind == 'set':
        attrs[event.key] = event.value
    elif event.kind == 'status':
        status = event.value
    elif event.kind == 'remove':
        attrs.pop(event.key, None)
    else:
        raise ValueError('event kind')
    return ApproachLockState(state.entity, status, event.sequence, tuple(sorted(attrs.items())))

def replay(entity, events):
    state = ApproachLockState(entity)
    for e in sorted(events, key=lambda e: e.sequence):
        state = apply(state, e)
    return state
