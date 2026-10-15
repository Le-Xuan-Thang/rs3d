"""STA/LTA event detection, shared by the live stream and the scan of downloaded days."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

import numpy as np
from obspy import Stream, Trace
from scipy.signal import butter, lfilter, sosfilt, sosfilt_zi

GAP_TOLERANCE = 1.5  # samples: a start further than this from the expected next sample is a gap


@dataclass
class EventSettings:
    enabled: bool = True
    channel: str = "EHZ"
    sta: float = 6.0
    lta: float = 30.0
    on: float = 3.95
    reset: float = 0.9
    highpass: float = 0.8
    lowpass: float = 9.0


@dataclass
class Event:
    start: float  # epoch seconds
    end: float
    peak_ratio: float
    peak_amplitude: float  # counts, after the band-pass
    channel: str
    source: str  # "live" or "scan"


def validate_settings(s: EventSettings, nyquist: float = 50.0) -> str:
    """'' when the settings can be used, else the reason they cannot."""
    if s.channel not in ("EHZ", "EHN", "EHE"):
        return "Channel must be EHZ, EHN or EHE."
    if s.sta <= 0:
        return "STA must be positive."
    if s.lta <= s.sta:
        return "LTA must be longer than STA."
    if s.reset >= s.on:
        return "Reset must be lower than On."
    if s.reset <= 0:
        return "Reset must be positive."
    if not 0 < s.highpass < s.lowpass < nyquist:
        return f"Band-pass must satisfy 0 < high-pass < low-pass < {nyquist:g} Hz."
    return ""


class EventDetector:
    """Feed it traces in time order. Calls `on_start(start, ratio)` when an event begins and
    `on_event(Event)` when it ends. Silent while the LTA window fills after a start or a gap."""

    def __init__(self, settings: EventSettings, on_event: Callable[[Event], None],
                 on_start: Callable[[float, float], None] | None = None, source: str = "live") -> None:
        self.settings = settings
        self._on_event = on_event
        self._on_start = on_start
        self._source = source
        self._open: dict | None = None
        self._last_t: float | None = None
        self._lock = threading.RLock()  # the live thread feeds while the UI thread may flush
        self._reset()

    @property
    def active(self) -> bool:
        return self._open is not None

    def _reset(self) -> None:
        self._rate = 0.0
        self._next: float | None = None
        self._seen = 0

    def _begin(self, rate: float, first: float) -> None:
        s = self.settings
        self._rate = rate
        self._seen = 0
        self._sos = butter(2, [s.highpass, min(s.lowpass, 0.45 * rate)], btype="bandpass", fs=rate, output="sos")
        self._bp_zi = sosfilt_zi(self._sos) * first  # start settled on the first sample: no step transient
        self._a_sta = 1.0 - 1.0 / (s.sta * rate)
        self._a_lta = 1.0 - 1.0 / (s.lta * rate)
        self._sta_zi = np.zeros(1)
        self._lta_zi = np.zeros(1)

    def feed(self, tr: Trace) -> None:
        with self._lock:
            self._feed(tr)

    def _feed(self, tr: Trace) -> None:
        s = self.settings
        if not s.enabled or tr.stats.channel != s.channel or tr.stats.npts == 0:
            return
        rate = float(tr.stats.sampling_rate)
        start = tr.stats.starttime.timestamp
        x = np.asarray(tr.data, dtype=float)
        if self._next is None or rate != self._rate or abs(start - self._next) > GAP_TOLERANCE / rate:
            self.flush()
            self._begin(rate, x[0])
        y, self._bp_zi = sosfilt(self._sos, x, zi=self._bp_zi)
        n = len(x)
        k = self._seen + np.arange(1, n + 1)
        sta_raw, self._sta_zi = lfilter([1 - self._a_sta], [1, -self._a_sta], y * y, zi=self._sta_zi)
        lta_raw, self._lta_zi = lfilter([1 - self._a_lta], [1, -self._a_lta], y * y, zi=self._lta_zi)
        sta = sta_raw / (1 - self._a_sta ** k)  # bias-corrected while the windows fill
        lta = lta_raw / (1 - self._a_lta ** k)
        ratio = np.divide(sta, lta, out=np.zeros(n), where=lta > 0)
        ratio[k < s.lta * rate] = 0.0  # warm-up: never trigger
        self._seen += n
        self._scan(ratio, y, start, rate)
        self._next = start + n / rate
        self._last_t = start + (n - 1) / rate

    def _scan(self, ratio: np.ndarray, y: np.ndarray, start: float, rate: float) -> None:
        s, n, i = self.settings, len(ratio), 0
        above, below = ratio > s.on, ratio < s.reset
        while i < n:
            if self._open is None:
                j = int(np.argmax(above[i:])) + i
                if not above[j]:
                    return
                self._open = {"start": start + j / rate, "ratio": float(ratio[j]), "amp": 0.0}
                if self._on_start:
                    self._on_start(self._open["start"], self._open["ratio"])
                i = j
            k = int(np.argmax(below[i:])) + i
            stop = k if below[k] else n
            if stop > i:
                self._open["ratio"] = max(self._open["ratio"], float(ratio[i:stop].max()))
                self._open["amp"] = max(self._open["amp"], float(np.abs(y[i:stop]).max()))
            if not below[k]:
                return
            self._close(start + k / rate)
            i = k + 1

    def _close(self, end: float | None) -> None:
        if self._open is None:
            return
        o, self._open = self._open, None
        self._on_event(Event(o["start"], end if end is not None else o["start"], o["ratio"], o["amp"],
                             self.settings.channel, self._source))

    def flush(self) -> None:
        """Close an event in progress at the last sample seen (end of data, a gap, new settings)."""
        with self._lock:
            self._close(self._last_t)


def detect(data: Trace | Stream, settings: EventSettings) -> list[Event]:
    """Events in recorded data. Same algorithm as the live detector."""
    traces = [data] if isinstance(data, Trace) else sorted(data, key=lambda t: t.stats.starttime)
    out: list[Event] = []
    detector = EventDetector(settings, out.append, source="scan")
    for tr in traces:
        detector.feed(tr)
    detector.flush()
    return out
