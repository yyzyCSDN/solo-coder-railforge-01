from __future__ import annotations
from dataclasses import dataclass
from threading import RLock
from typing import Generic, TypeVar
T = TypeVar('T')

class VersionConflict(RuntimeError):
    """Raised when an optimistic version check fails."""

@dataclass(frozen=True)
class Versioned(Generic[T]):
    value: T
    version: int

class Cell(Generic[T]):

    def __init__(self, value: T):
        self._value = value
        self._version = 0
        self._lock = RLock()

    def snapshot(self):
        with self._lock:
            return Versioned(self._value, self._version)

    def compare_and_set(self, expected: int, value: T):
        with self._lock:
            if self._version != expected:
                raise VersionConflict(f'expected={expected} actual={self._version}')
            self._value = value
            self._version += 1
            return Versioned(value, self._version)
