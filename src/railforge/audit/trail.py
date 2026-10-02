from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib, json

@dataclass(frozen=True)
class Record:
    index: int
    actor: str
    action: str
    subject: str
    at: datetime
    previous_hash: str
    digest: str


@dataclass(frozen=True)
class TrailCheckpoint:
    rows: tuple[Record, ...]


class Trail:

    def __init__(self):
        self._rows = []

    def checkpoint(self):
        return TrailCheckpoint(tuple(self._rows))

    def restore(self, checkpoint):
        self._rows = list(checkpoint.rows)

    @staticmethod
    def _digest(index, actor, action, subject, at, previous):
        b = json.dumps({'index': index, 'actor': actor, 'action': action, 'subject': subject, 'at': at.astimezone(timezone.utc).isoformat(), 'previous': previous}, sort_keys=True, separators=(',', ':')).encode()
        return hashlib.sha256(b).hexdigest()

    def append(self, actor, action, subject, at=None):
        at = at or datetime.now(timezone.utc)
        prev = self._rows[-1].digest if self._rows else 'GENESIS'
        idx = len(self._rows) + 1
        d = self._digest(idx, actor, action, subject, at, prev)
        r = Record(idx, actor, action, subject, at, prev, d)
        self._rows.append(r)
        return r

    def verify(self):
        prev = 'GENESIS'
        for r in self._rows:
            if r.previous_hash != prev or r.digest != self._digest(r.index, r.actor, r.action, r.subject, r.at, prev):
                return False
            prev = r.digest
        return True
