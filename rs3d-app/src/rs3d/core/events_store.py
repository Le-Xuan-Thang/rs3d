"""Event log: one JSON object per line in events.jsonl."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from pathlib import Path

from rs3d.core.events import Event


class EventStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.error = ""  # why the last read or write failed; "" when it worked
        self.skipped = 0  # corrupt lines seen by the last read
        self._lock = threading.Lock()

    def append(self, event: Event) -> bool:
        """Add one event. False (and `error` set) when the file cannot be written."""
        line = json.dumps(asdict(event)) + "\n"
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self._ends_mid_line():
                    line = "\n" + line  # a crash left a cut-off line; don't join onto it
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line)  # one write call per line keeps appends whole
            except OSError as exc:
                self.error = str(exc)
                return False
            self.error = ""
            return True

    def _ends_mid_line(self) -> bool:
        """True when the file has content but its last byte is not a newline."""
        try:
            with open(self.path, "rb") as f:
                f.seek(0, os.SEEK_END)
                if f.tell() == 0:
                    return False
                f.seek(-1, os.SEEK_END)
                return f.read(1) != b"\n"
        except FileNotFoundError:
            return False

    _NUMBERS = ("start", "end", "peak_ratio", "peak_amplitude")
    _STRINGS = ("channel", "source")

    @classmethod
    def _parse(cls, line: str) -> Event | None:
        try:
            d = json.loads(line)
        except ValueError:
            return None
        if not isinstance(d, dict):
            return None
        for k in cls._NUMBERS:
            v = d.get(k)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                return None
        for k in cls._STRINGS:
            if not isinstance(d.get(k), str):
                return None
        return Event(**{k: d[k] for k in cls._NUMBERS + cls._STRINGS})

    def _read(self) -> list[Event] | None:
        """The logged events, or None when the file exists but cannot be read (`error` is set)."""
        out: list[Event] = []
        self.skipped = 0
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return out
        except OSError as exc:
            self.error = f"cannot read {self.path.name}: {exc}"
            return None
        for line in raw.decode("utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            ev = self._parse(line)
            if ev is None:
                self.skipped += 1
            else:
                out.append(ev)
        return out

    @staticmethod
    def _listed(events: list[Event]) -> list[Event]:
        """Sorted by start; a scan event that overlaps a live event is dropped."""
        live = [e for e in events if e.source == "live"]
        keep = [e for e in events
                if e.source == "live" or not any(e.start <= v.end and v.start <= e.end for v in live)]
        return sorted(keep, key=lambda e: e.start)

    def events_between(self, t0: float, t1: float) -> list[Event]:
        """Events that overlap [t0, t1]."""
        with self._lock:
            events = self._read() or []
        return [e for e in self._listed(events) if e.start <= t1 and e.end >= t0]

    def latest(self, n: int) -> list[Event]:
        """The n most recent events, newest first."""
        with self._lock:
            events = self._read() or []
        return self._listed(events)[::-1][:n]

    def replace_scan_events(self, t0: float, t1: float, events: list[Event]) -> bool:
        """Swap the scan events that start in [t0, t1) for `events`. Live events stay."""
        with self._lock:
            current = self._read()
            if current is None:
                return False  # unreadable: rewriting would lose the log
            kept = [e for e in current if not (e.source == "scan" and t0 <= e.start < t1)]
            lines = "".join(json.dumps(asdict(e)) + "\n" for e in kept + list(events))
            tmp = self.path.with_name(self.path.name + ".tmp")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(lines, encoding="utf-8")
                os.replace(tmp, self.path)
            except OSError as exc:
                self.error = str(exc)
                return False
            self.error = ""
            return True
