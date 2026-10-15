"""Run the detector over stored days and keep the result in the event log."""

from __future__ import annotations

from datetime import date, timedelta

from obspy import Trace, UTCDateTime

from rs3d.core.events import EventDetector, EventSettings
from rs3d.core.events_store import EventStore
from rs3d.core.models import Selection
from rs3d.core.store import Store


def days_between(first: date, last: date) -> list[date]:
    """Every date from `first` to `last`, both included."""
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def chunked(tr: Trace, seconds: float = 3600.0):
    """Pieces of `tr` of at most `seconds` each (copies), so a whole day is never filtered in one block."""
    step = max(1, int(seconds * tr.stats.sampling_rate))
    for i in range(0, tr.stats.npts, step):
        piece = tr.copy()
        piece.data = tr.data[i:i + step].copy()
        piece.stats.starttime = tr.stats.starttime + i / tr.stats.sampling_rate
        yield piece


def scan_day(store: Store, events: EventStore, settings: EventSettings, net: str, sta: str, loc: str,
             day: date) -> int:
    """Detect events on one UTC day and replace that day's scan events in the log. Returns the count.

    The previous `2 * lta` seconds are loaded as warm-up: the detector is silent for the first `lta` seconds of
    data and needs about one more `lta` to settle, so shaking right after midnight is not lost. Only events that
    start inside the day are kept.
    """
    t0 = UTCDateTime(day.year, day.month, day.day)
    t1 = t0 + 86400
    found = []
    if day in store.days(net, sta, loc, settings.channel):  # no file for this day: nothing can start in it
        sel = Selection(net, sta, loc, t0 - 2 * settings.lta, t1, channels=(settings.channel,))
        out: list = []
        detector = EventDetector(settings, out.append, source="scan")
        for tr in sorted(store.load(sel), key=lambda t: t.stats.starttime):
            for piece in chunked(tr):
                detector.feed(piece)
        detector.flush()
        found = [e for e in out if t0.timestamp <= e.start < t1.timestamp]
    events.replace_scan_events(t0.timestamp, t1.timestamp, found)
    return len(found)
