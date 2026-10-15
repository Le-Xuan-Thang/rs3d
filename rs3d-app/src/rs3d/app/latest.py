"""Keep only the newest of several overlapping loads: older ones check `is_current` and drop their result."""

from __future__ import annotations


class LatestOnly:
    def __init__(self) -> None:
        self._n = 0

    def next(self) -> int:
        self._n += 1
        return self._n

    def is_current(self, token: int) -> bool:
        return token == self._n
