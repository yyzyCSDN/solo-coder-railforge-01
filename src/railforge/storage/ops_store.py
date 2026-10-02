from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class VersionedValue:
    version: int
    value: Any


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

    def restore(self, key: str, row: VersionedValue | None) -> None:
        """Restore a previous read() snapshot, or remove the key when row is None.

        Used to roll back the store side of a failed atomic commit."""
        with self._lock:
            if row is None:
                self._rows.pop(key, None)
            else:
                self._rows[key] = row

    def snapshot(self) -> dict[str, VersionedValue]:
        with self._lock:
            return dict(self._rows)

