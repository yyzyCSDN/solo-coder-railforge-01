from __future__ import annotations
from dataclasses import dataclass, replace
from datetime import datetime, timezone

@dataclass(frozen=True)
class Authority:
    authority_id: str
    train: str
    segments: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    revision: int
    cancelled: bool = False

def current_authority(rows: list[Authority], train: str, at: datetime):
    x = at.astimezone(timezone.utc)
    valid = [r for r in rows if r.train == train and (not r.cancelled) and (r.issued_at.astimezone(timezone.utc) <= x < r.expires_at.astimezone(timezone.utc))]
    if not valid:
        return None
    return max(valid, key=lambda r: (r.revision, r.issued_at, r.authority_id))

def conflicting(rows: list[Authority], candidate: Authority):
    out = []
    cs = set(candidate.segments)
    start = candidate.issued_at.astimezone(timezone.utc)
    end = candidate.expires_at.astimezone(timezone.utc)
    for r in rows:
        if r.cancelled or r.train == candidate.train or (not cs.intersection(r.segments)):
            continue
        rs = r.issued_at.astimezone(timezone.utc)
        re = r.expires_at.astimezone(timezone.utc)
        if max(start, rs) < min(end, re):
            out.append(r.authority_id)
    return sorted(out)

def supersede(rows: list[Authority], new: Authority):
    out = []
    for r in rows:
        if r.train == new.train and (not r.cancelled) and (r.revision < new.revision):
            out.append(replace(r, cancelled=True))
        else:
            out.append(r)
    out.append(new)
    return out
