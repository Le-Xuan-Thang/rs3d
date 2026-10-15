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
        self.error = ""  # why the last write failed; "" when writes work
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

    def _read(self) -> list[Event]:
        out: list[Event] = []
        self.skipped = 0
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return out
        except OSError as exc:
            self.error = str(exc)
            return out
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                out.append(Event(**json.loads(line)))
            except (ValueError, TypeError):
                self.skipped += 1
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
            events = self._read()
        return [e for e in self._listed(events) if e.start <= t1 and e.end >= t0]

    def latest(self, n: int) -> list[Event]:
        """The n most recent events, newest first."""
        with self._lock:
            events = self._read()
        return self._listed(events)[::-1][:n]

    def replace_scan_events(self, t0: float, t1: float, events: list[Event]) -> bool:
        """Swap the scan events that start in [t0, t1) for `events`. Live events stay."""
        with self._lock:
            kept = [e for e in self._read() if not (e.source == "scan" and t0 <= e.start < t1)]
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
