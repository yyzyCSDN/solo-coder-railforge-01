from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
UTC = timezone.utc

def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('timezone-aware datetime required')
    return value

def utc(value: datetime) -> datetime:
    return aware(value).astimezone(UTC)

@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

    def __post_init__(self):
        if utc(self.end) <= utc(self.start):
            raise ValueError('positive window required')

    def overlaps(self, other: 'Window') -> bool:
        return max(utc(self.start), utc(other.start)) < min(utc(self.end), utc(other.end))

    def contains(self, at: datetime) -> bool:
        x = utc(at)
        return utc(self.start) <= x < utc(self.end)

    @property
    def duration(self) -> timedelta:
        return utc(self.end) - utc(self.start)

def local_wall(value: datetime, zone: str, fold: int=0) -> datetime:
    if value.tzinfo is not None:
        raise ValueError('naive wall time required')
    if fold not in (0, 1):
        raise ValueError('fold')
    return value.replace(tzinfo=ZoneInfo(zone), fold=fold)
