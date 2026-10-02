from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class FeedEvent:
    partition: str
    sequence: int
    event_id: str
    payload: dict

class CursorConsumer:

    def __init__(self):
        self.cursor = {}
        self.seen = set()

    def accept(self, event: FeedEvent):
        last = self.cursor.get(event.partition, 0)
        if event.event_id in self.seen:
            return False
        if event.sequence <= last:
            return False
        if event.sequence != last + 1:
            raise ValueError('cursor gap')
        self.cursor[event.partition] = event.sequence
        self.seen.add(event.event_id)
        return True
