"""Which parts of a time range are downloaded, only on the Shake, or missing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

from obspy import UTCDateTime, read

from rs3d.core.store import Store


class State(str, Enum):
    LOCAL = "local"    # downloaded to the laptop
    REMOTE = "remote"  # on the Shake, not downloaded yet
    GAP = "gap"        # no data anywhere


@dataclass(frozen=True)
class Segment:
    start: UTCDateTime
    end: UTCDateTime
    state: State


def _day_start(day: date) -> UTCDateTime:
    return UTCDateTime(day.year, day.month, day.day)


def _days_between(start: UTCDateTime, end: UTCDateTime) -> list[date]:
    first, last = start.date, (end - 1e-6).date
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def local_spans(
    store: Store, network: str, station: str, location: str, channel: str,
    start: UTCDateTime, end: UTCDateTime,
) -> list[tuple[UTCDateTime, UTCDateTime]]:
    """Time spans with local data, clipped to [start, end] and merged.

    Two traces are joined when the hole between them is at most 1.5 samples.
    """
    spans: list[tuple[UTCDateTime, UTCDateTime, float]] = []
    for day in _days_between(start, end):
        path = store.day_path(network, station, location, channel, day)
        if not path.exists():
            continue
        for tr in read(str(path), headonly=True):
            delta = tr.stats.delta
            s, e = tr.stats.starttime, tr.stats.endtime + delta
            if e > start and s < end:
                spans.append((max(s, start), min(e, end), delta))
    spans.sort(key=lambda x: x[0])
    merged: list[tuple[UTCDateTime, UTCDateTime]] = []
    for s, e, delta in spans:
        if merged and s - merged[-1][1] <= 0.5 * delta:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def coverage(
    store: Store, network: str, station: str, location: str, channel: str,
    start: UTCDateTime, end: UTCDateTime, remote_days: set[date],
) -> list[Segment]:
    """Split [start, end] into LOCAL / REMOTE / GAP segments for one channel.

    Time without local data counts as REMOTE when its day exists on the Shake and is
    either not downloaded yet or is the newest remote day (the file still growing).
    """
    if end <= start:
        raise ValueError("end must be after start")
    spans = local_spans(store, network, station, location, channel, start, end)
    local_days = store.days(network, station, location, channel)
    newest_remote = max(remote_days) if remote_days else None

    cuts = [start, end]  # UTCDateTime is not hashable: dedupe by nanoseconds
    for day in _days_between(start, end):
        for t in (_day_start(day), _day_start(day + timedelta(days=1))):
            if start < t < end:
                cuts.append(t)
    for s, e in spans:
        cuts += [s, e]
    points = sorted({t.ns: t for t in cuts}.values())

    segments: list[Segment] = []
    for a, b in zip(points, points[1:]):
        if b <= a:
            continue
        mid = a + (b - a) / 2
        if any(s <= mid < e for s, e in spans):
            state = State.LOCAL
        else:
            day = mid.date
            if day in remote_days and (day not in local_days or day == newest_remote):
                state = State.REMOTE
            else:
                state = State.GAP
        if segments and segments[-1].state == state and segments[-1].end == a:
            segments[-1] = Segment(segments[-1].start, b, state)
        else:
            segments.append(Segment(a, b, state))
    return segments
