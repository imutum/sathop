from __future__ import annotations

import threading


class NamedLockRegistry:
    """Lazily-allocated, named threading.Lock registry.

    The guard lock serializes only dict access — actual critical sections
    run outside it. Used wherever several threads might race on the same
    resource keyed by string (bundle ref, shared-file name, etc.).
    """

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, name: str) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(name)
            if lock is None:
                lock = threading.Lock()
                self._locks[name] = lock
            return lock
