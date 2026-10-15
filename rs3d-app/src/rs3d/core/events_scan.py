"""Run the detector over stored days and keep the result in the event log."""

from __future__ import annotations

from datetime import date, timedelta

from obspy import UTCDateTime

from rs3d.core.events import EventSettings, detect
from rs3d.core.events_store import EventStore
from rs3d.core.models import Selection
from rs3d.core.store import Store


def days_between(first: date, last: date) -> list[date]:
    """Every date from `first` to `last`, both included."""
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def scan_day(store: Store, events: EventStore, settings: EventSettings, net: str, sta: str, loc: str,
             day: date) -> int:
    """Detect events on one UTC day and replace that day's scan events in the log. Returns the count.

    The previous `lta` seconds are loaded as warm-up so shaking right after midnight is not lost; only events
    that start inside the day are kept.
    """
    t0 = UTCDateTime(day.year, day.month, day.day)
    t1 = t0 + 86400
    found = []
    if day in store.days(net, sta, loc, settings.channel):  # no file for this day: nothing can start in it
        sel = Selection(net, sta, loc, t0 - settings.lta, t1, channels=(settings.channel,))
        found = [e for e in detect(store.load(sel), settings) if t0.timestamp <= e.start < t1.timestamp]
    events.replace_scan_events(t0.timestamp, t1.timestamp, found)
    return len(found)
