"""One UTC day of min/max pairs per second and channel: the data behind the live helicorder."""

from __future__ import annotations

import threading
from datetime import date, datetime, timezone

import numpy as np
from obspy import Stream, Trace, UTCDateTime

from rs3d.core.helicorder import ROW_MINUTES, Row

SECONDS = 86400


def day_start(day: date) -> float:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()


class DayTrace:
    """Per channel, the minimum and maximum of every second of one UTC day (NaN: no data). Thread-safe.

    Live traces (`add`) win over archive data (`replace_from`) for the same second. A live trace that starts on a
    later UTC day starts a new, empty day; a trace from an earlier day is ignored.
    """

    def __init__(self, day: date) -> None:
        self._lock = threading.Lock()
        self._reset(day)

    def _reset(self, day: date) -> None:
        self.day = day
        self.start = day_start(day)
        self._lo: dict[str, np.ndarray] = {}
        self._hi: dict[str, np.ndarray] = {}
        self._live: dict[str, np.ndarray] = {}

    def _arrays(self, channel: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if channel not in self._lo:
            self._lo[channel] = np.full(SECONDS, np.nan)
            self._hi[channel] = np.full(SECONDS, np.nan)
            self._live[channel] = np.zeros(SECONDS, dtype=bool)
        return self._lo[channel], self._hi[channel], self._live[channel]

    def _bins(self, tr: Trace) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(second index, min, max) for the samples of `tr` that fall inside this day."""
        v = tr.data.astype(float)
        t = tr.stats.starttime.timestamp + np.arange(len(v)) / tr.stats.sampling_rate
        sec = np.floor(t - self.start).astype(np.int64)
        keep = (sec >= 0) & (sec < SECONDS) & np.isfinite(v)
        sec, v = sec[keep], v[keep]
        if not len(v):
            return sec, v, v
        starts = np.concatenate([[0], np.flatnonzero(np.diff(sec)) + 1])
        return sec[starts], np.minimum.reduceat(v, starts), np.maximum.reduceat(v, starts)

    def add(self, tr: Trace) -> None:
        """Fold a live trace in."""
        trace_day = datetime.fromtimestamp(tr.stats.starttime.timestamp, timezone.utc).date()
        with self._lock:
            if trace_day > self.day:
                self._reset(trace_day)
            elif trace_day < self.day:
                return
            secs, lo_new, hi_new = self._bins(tr)
            if not len(secs):
                return
            lo, hi, live = self._arrays(tr.stats.channel)
            fresh = ~live[secs]
            lo[secs] = np.where(fresh, lo_new, np.fmin(lo[secs], lo_new))
            hi[secs] = np.where(fresh, hi_new, np.fmax(hi[secs], hi_new))
            live[secs] = True

    def replace_from(self, st: Stream) -> None:
        """Fill seconds from archive data. Seconds that live data already filled are left alone."""
        with self._lock:
            for tr in st:
                secs, lo_new, hi_new = self._bins(tr)
                if not len(secs):
                    continue
                lo, hi, live = self._arrays(tr.stats.channel)
                keep = ~live[secs]
                lo[secs[keep]] = lo_new[keep]
                hi[secs[keep]] = hi_new[keep]

    def has_data(self, channel: str) -> bool:
        with self._lock:
            return channel in self._lo and bool(np.isfinite(self._lo[channel]).any())

    def rows(self, channel: str, row_minutes: int = ROW_MINUTES, step: int = 2) -> list[Row]:
        """The day as rows for the helicorder chart: one min and one max point per `step` seconds.

        A second without data is a NaN point (the line breaks); empty seconds before the first and after the last
        sample of a row are cut. Each row is shown without its median, like the Helicorder page.
        """
        span = row_minutes * 60
        with self._lock:
            if channel not in self._lo:
                lo = hi = np.full(SECONDS, np.nan)
            else:
                lo, hi = self._lo[channel].copy(), self._hi[channel].copy()
        rows: list[Row] = []
        for i in range(SECONDS // span):
            a = i * span
            start = UTCDateTime(self.start + a)
            lo_r = np.fmin.reduce(lo[a:a + span].reshape(-1, step), axis=1)
            hi_r = np.fmax.reduce(hi[a:a + span].reshape(-1, step), axis=1)
            finite = np.flatnonzero(np.isfinite(lo_r) | np.isfinite(hi_r))
            if not len(finite):
                rows.append(Row(start, np.array([]), np.array([])))
                continue
            first, last = finite[0], finite[-1] + 1
            lo_r, hi_r = lo_r[first:last], hi_r[first:last]
            base = np.arange(first, last) * step
            t = np.column_stack([base + 0.25 * step, base + 0.75 * step]).ravel()
            v = np.column_stack([lo_r, hi_r]).ravel()
            v = v - np.median(v[np.isfinite(v)])
            rows.append(Row(start, t, v))
        return rows
