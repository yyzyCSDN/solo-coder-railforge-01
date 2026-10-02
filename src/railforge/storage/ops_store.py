from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class VersionedValue:
    version: int
    value: Any


@dataclass(frozen=True)
class StoreSnapshot:
    rows: dict[str, VersionedValue]


class VersionedStore:
    """Small compare-and-swap store used to make operation publication atomic."""

    def __init__(self):
        self._rows: dict[str, VersionedValue] = {}
        self._lock = RLock()

    def write(self, key: str, value: Any, expected_version: int | None = None) -> int:
        with self._lock:
            current = self._rows.get(key)
            actual = current.version if current else 0
            if expected_version is not None and expected_version != actual:
                raise RuntimeError("version conflict")
            version = actual + 1
            self._rows[key] = VersionedValue(version, value)
            return version

    def read(self, key: str) -> VersionedValue | None:
        with self._lock:
            return self._rows.get(key)

    def snapshot(self) -> StoreSnapshot:
        with self._lock:
            return StoreSnapshot(dict(self._rows))

    def restore(self, snapshot: StoreSnapshot) -> None:
        with self._lock:
            self._rows = dict(snapshot.rows)

