"""Live data: a background thread feeds a ring buffer; the UI takes snapshots."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np
from obspy import Trace, UTCDateTime

log = logging.getLogger(__name__)

BACKOFF = (2, 4, 8, 16, 30)  # seconds between reconnect attempts


class Source(Protocol):
    def run(self, on_trace: Callable[[Trace], None]) -> None: ...
    def close(self) -> None: ...


@dataclass
class _Chunk:
    start: float  # epoch seconds of the first sample
    rate: float
    data: np.ndarray

    @property
    def end(self) -> float:  # time just after the last sample
        return self.start + len(self.data) / self.rate


class RingBuffer:
    """Recent samples per channel, as a list of contiguous chunks. Thread-safe."""

    def __init__(self, seconds: float = 600.0) -> None:
        self.seconds = seconds
        self._chunks: dict[str, list[_Chunk]] = {}
        self._lock = threading.Lock()

    def add(self, tr: Trace) -> None:
        chunk = _Chunk(tr.stats.starttime.timestamp, tr.stats.sampling_rate, tr.data.astype(float))
        with self._lock:
            chunks = self._chunks.setdefault(tr.stats.channel, [])
            last = chunks[-1] if chunks else None
            if last and abs(chunk.start - last.end) <= 0.5 / chunk.rate and last.rate == chunk.rate:
                last.data = np.concatenate([last.data, chunk.data])
            else:
                chunks.append(chunk)
            horizon = chunk.end - self.seconds
            self._chunks[tr.stats.channel] = [c for c in chunks if c.end > horizon]

    def latest(self) -> float | None:
        with self._lock:
            ends = [cs[-1].end for cs in self._chunks.values() if cs]
        return max(ends) if ends else None

    def channels(self) -> list[str]:
        """Channels that currently hold data, sorted."""
        with self._lock:
            return sorted(ch for ch, cs in self._chunks.items() if cs)

    def snapshot(self, channel: str, seconds: float, end: float | None = None,
                 max_points: int = 2000, bandpass: tuple[float, float] | None = None,
                 ) -> tuple[np.ndarray, np.ndarray]:
        """(times, values) for the last `seconds` before `end`. A NaN separates non-contiguous chunks.

        `bandpass` filters each contiguous chunk on its own (zero-phase, 4 poles) before
        long windows are decimated by min/max pairs, so peaks stay visible.
        """
        end = end if end is not None else (self.latest() or time.time())
        start = end - seconds
        times, values = [], []
        with self._lock:
            chunks = list(self._chunks.get(channel, []))
        for c in chunks:
            if c.end <= start or c.start >= end:
                continue
            i0 = max(0, int(np.ceil((start - c.start) * c.rate)))
            i1 = min(len(c.data), int(np.floor((end - c.start) * c.rate)))
            if i1 <= i0:
                continue
            t = c.start + np.arange(i0, i1) / c.rate
            v = c.data[i0:i1]
            if bandpass is not None:
                v = _bandpass(v, c.rate, *bandpass)
            if times:
                times.append(np.array([t[0]]))
                values.append(np.array([np.nan]))
            times.append(t)
            values.append(v)
        if not times:
            return np.array([]), np.array([])
        t, v = np.concatenate(times), np.concatenate(values)
        if len(t) > max_points:
            t, v = minmax_decimate(t, v, max_points)
        return t, v


def _bandpass(v: np.ndarray, rate: float, fmin: float, fmax: float) -> np.ndarray:
    """Zero-phase Butterworth band-pass of one contiguous chunk; too-short chunks are only demeaned."""
    from scipy.signal import butter, sosfiltfilt

    v = v - v.mean()
    sos = butter(2, [fmin, min(fmax, 0.45 * rate)], btype="bandpass", fs=rate, output="sos")
    padlen = 3 * (2 * len(sos) + 1)
    return sosfiltfilt(sos, v) if len(v) > padlen else v


def minmax_decimate(t: np.ndarray, v: np.ndarray, max_points: int) -> tuple[np.ndarray, np.ndarray]:
    """Keep min and max of each bin. Each contiguous segment (between NaN markers) is decimated
    on its own, so gaps survive."""
    breaks = np.flatnonzero(np.isnan(v))
    bounds = np.concatenate([[-1], breaks, [len(v)]])
    segments = [(a + 1, b) for a, b in zip(bounds[:-1], bounds[1:]) if b > a + 1]
    total = sum(b - a for a, b in segments)
    out_t: list[float] = []
    out_v: list[float] = []
    for k, (a, b) in enumerate(segments):
        if k:
            out_t.append(t[a - 1])
            out_v.append(np.nan)
        bins = max(1, int(max_points // 2 * (b - a) / total))
        edges = np.linspace(a, b, bins + 1).astype(int)
        for lo_edge, hi_edge in zip(edges[:-1], edges[1:]):
            if hi_edge <= lo_edge:
                continue
            seg = v[lo_edge:hi_edge]
            lo, hi = lo_edge + int(np.argmin(seg)), lo_edge + int(np.argmax(seg))
            for i in sorted({lo, hi}):
                out_t.append(t[i])
                out_v.append(v[i])
    return np.array(out_t), np.array(out_v)


class LiveStream:
    """Keeps a Source running in a daemon thread; reconnects with backoff when it fails."""

    def __init__(self, source_factory: Callable[[], Source], buffer: RingBuffer | None = None,
                 sleep: Callable[[float], None] | None = None, detector=None, day_trace=None) -> None:
        self.buffer = buffer or RingBuffer()
        self.detector = detector  # anything with feed(trace) and optionally flush(); e.g. EventDetector. Replaced by AppState on new settings.
        self.day_trace = day_trace  # anything with add(trace); e.g. DayTrace, the data of the live helicorder
        self.state = "stopped"  # stopped | connecting | live | reconnecting
        self.error = ""
        self.last_data: float | None = None  # time.monotonic() of the last trace
        self._factory = source_factory
        self._stop = threading.Event()
        self._sleep = sleep or (lambda s: self._stop.wait(s))
        self._thread: threading.Thread | None = None
        self._source: Source | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="rs3d-live", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._source:
            self._source.close()
        if self._thread:
            self._thread.join(timeout)
        self.state = "stopped"

    def _on_trace(self, tr: Trace) -> None:
        self.state = "live"
        self.last_data = time.monotonic()
        self.buffer.add(tr)
        if self.day_trace is not None:
            try:
                self.day_trace.add(tr)
            except Exception:  # the helicorder must never stop the stream
                log.exception("day trace failed")
        detector = self.detector
        if detector is not None:
            try:
                detector.feed(tr)
            except Exception:  # a detector bug must never stop the stream
                log.exception("event detector failed")

    def _flush_detector(self) -> None:
        """Close an event left open by a stream that ended (the data after it will not continue it)."""
        flush = getattr(self.detector, "flush", None)
        if callable(flush):
            try:
                flush()
            except Exception:
                log.exception("event detector flush failed")

    def is_stale(self, seconds: float = 5.0) -> bool:
        """True when no data arrived recently (ObsPy may be reconnecting inside the source)."""
        return self.last_data is None or time.monotonic() - self.last_data > seconds

    def _loop(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            self.state = "connecting" if attempt == 0 else "reconnecting"
            try:
                self._source = self._factory()
                self._source.run(self._on_trace)
                self.error = "connection closed"
            except Exception as exc:
                self.error = str(exc) or type(exc).__name__
            self._flush_detector()
            if self._stop.is_set():
                break
            if self.state == "live":
                attempt = 0  # it worked for a while: start the backoff again
            delay = BACKOFF[min(attempt, len(BACKOFF) - 1)]
            attempt += 1
            self.state = "reconnecting"
            self._sleep(delay)
