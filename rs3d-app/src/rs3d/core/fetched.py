"""Which time spans of the Shake's archive were already requested, so a gap on the Shake is not asked for twice.

A partly downloaded day file cannot tell "not copied yet" from "the Shake has nothing there". This ledger keeps the
spans that were copied (clipped to the data the Shake had at that moment). A day file with no entry here, other than
the newest day on the Shake, is a whole-day copy.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from obspy import UTCDateTime


def _merge(spans: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


class Fetched:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, list[list[float]]]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}  # missing or unreadable: nothing is claimed as fetched

    @staticmethod
    def key(network: str, station: str, location: str, channel: str) -> str:
        return f"{network}.{station}.{location}.{channel}"

    def spans(self, key: str) -> list[tuple[float, float]]:
        return [(s, e) for s, e in self._load().get(key, [])]

    def add(self, key: str, start: float, end: float) -> None:
        if end <= start:
            return
        data = self._load()
        data[key] = _merge(data.get(key, []) + [[start, end]])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, self.path)

    def has_day(self, key: str, day: date) -> bool:
        a = UTCDateTime(day.year, day.month, day.day).timestamp
        return any(s < a + 86400 and e > a for s, e in self.spans(key))
