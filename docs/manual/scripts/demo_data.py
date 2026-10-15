"""Synthetic demo recording for the manuals: one UTC day, three channels, 100 Hz, seeded (always identical).

Station AM.DEMO1.00 is fictitious. The day contains
  * microseism (0.1-0.5 Hz) and day/night cultural noise (1-20 Hz) on top of a DC offset, like raw Shake counts,
  * a 30 Hz instrument line,
  * a local earthquake   at 03:12:20 (P at 03:12:20, S 9 s later, 2-8 Hz),
  * a distant earthquake at 14:40:00 (long period, 0.05-0.4 Hz, ten minutes),
  * two man-made noise bursts at 10:05:00 and 11:30:00 (footsteps / a truck: they look like events to a trigger),
  * two data gaps: 05:00:00-05:00:30 and 17:20:00-17:22:30.
"""

from __future__ import annotations

import numpy as np
from obspy import Stream, Trace, UTCDateTime
from scipy import signal

RATE = 100.0
NET, STA, LOC = "AM", "DEMO1", "00"
CHANNELS = ("EHZ", "EHN", "EHE")
DAY = UTCDateTime("2026-10-15T00:00:00")

LOCAL_QUAKE = UTCDateTime("2026-10-15T03:12:20")
DISTANT_QUAKE = UTCDateTime("2026-10-15T14:40:00")
BURSTS = (UTCDateTime("2026-10-15T10:05:00"), UTCDateTime("2026-10-15T11:30:00"))
GAPS = ((UTCDateTime("2026-10-15T05:00:00"), UTCDateTime("2026-10-15T05:00:30")),
        (UTCDateTime("2026-10-15T17:20:00"), UTCDateTime("2026-10-15T17:22:30")))

OFFSET = {"EHZ": 15000, "EHN": 20000, "EHE": -8000}   # raw counts sit on a large DC offset
MICRO = {"EHZ": 220.0, "EHN": 320.0, "EHE": 320.0}
CULTURAL = {"EHZ": 110.0, "EHN": 140.0, "EHE": 140.0}


def _band(rng: np.random.Generator, n: int, f1: float, f2: float, order: int = 4) -> np.ndarray:
    """Unit-variance band-limited noise."""
    sos = signal.butter(order, [f1, f2], btype="bandpass", fs=RATE, output="sos")
    x = signal.sosfilt(sos, rng.normal(size=n))
    return x / x.std()


def _smooth_random(rng: np.random.Generator, n: int, seconds: float) -> np.ndarray:
    """Slowly varying positive factor (log-normal, correlation time ~ `seconds`)."""
    k = max(int(seconds * RATE), 1)
    knots = rng.normal(size=n // k + 3)
    x = np.interp(np.arange(n) / k, np.arange(knots.size), knots)
    return np.exp(0.35 * x)


def _envelope(t: np.ndarray, t0: float, rise: float, decay: float) -> np.ndarray:
    """Zero before t0, grows over `rise` seconds, then decays exponentially with time constant `decay`."""
    u = np.maximum(t - t0, 0.0)
    env = (1 - np.exp(-u / rise)) * np.exp(-u / decay)
    return env / env.max()


def _add_event(x: np.ndarray, rng: np.random.Generator, t: np.ndarray, channel: str) -> None:
    """Local earthquake: P wave 2-8 Hz (strong on Z), S wave 1.5-6 Hz (strong on N/E), long coda."""
    n = t.size
    t0 = LOCAL_QUAKE - DAY
    p_amp, s_amp = (1500.0, 3500.0) if channel == "EHZ" else (500.0, 7000.0)
    x += p_amp * _envelope(t, t0, 0.4, 3.5) * _band(rng, n, 2.0, 8.0)
    x += s_amp * _envelope(t, t0 + 9.0, 0.9, 14.0) * _band(rng, n, 1.5, 6.0)


def _add_distant(x: np.ndarray, rng: np.random.Generator, t: np.ndarray, channel: str) -> None:
    """Distant earthquake: long-period surface waves, slowly building, ten minutes."""
    n = t.size
    t0 = DISTANT_QUAKE - DAY
    amp = 5200.0 if channel == "EHZ" else 6500.0
    x += amp * _envelope(t, t0, 90.0, 220.0) * _band(rng, n, 0.05, 0.4, order=3)
    x += 0.12 * amp * _envelope(t, t0 + 20.0, 20.0, 60.0) * _band(rng, n, 0.5, 3.0)


def _add_burst(x: np.ndarray, rng: np.random.Generator, t: np.ndarray, start: UTCDateTime, amp: float) -> None:
    """A man-made burst: broadband 4-25 Hz, short, abrupt, then silence (no coda)."""
    n = t.size
    t0 = start - DAY
    env = np.where((t > t0) & (t < t0 + 12.0), 1.0, 0.0)
    env = np.convolve(env, np.ones(50) / 50, mode="same")
    x += amp * env * _band(rng, n, 4.0, 25.0)


def make_day(seed: int = 20261015) -> Stream:
    """The whole demo day as a Stream (one Trace per channel and contiguous piece, int32 counts)."""
    n = int(86400 * RATE)
    t = np.arange(n) / RATE
    hour = t / 3600.0
    day_night = 1.0 + 2.6 * np.exp(-0.5 * ((hour - 13.0) / 4.5) ** 2)   # busier around midday
    st = Stream()
    for i, ch in enumerate(CHANNELS):
        rng = np.random.default_rng([seed, i])
        x = (MICRO[ch] * _band(rng, n, 0.1, 0.5, order=3)
             + CULTURAL[ch] * day_night * _smooth_random(rng, n, 40.0) * _band(rng, n, 1.0, 20.0)
             + 40.0 * np.sin(2 * np.pi * 30.0 * t + i))
        _add_event(x, rng, t, ch)
        _add_distant(x, rng, t, ch)
        for k, burst in enumerate(BURSTS):
            _add_burst(x, rng, t, burst, (4200.0, 1800.0)[k])
        x = np.clip(x + OFFSET[ch], -2**31 + 1, 2**31 - 1).astype(np.int32)
        edges = [0]
        for a, b in GAPS:
            edges += [int((a - DAY) * RATE), int((b - DAY) * RATE)]
        edges.append(n)
        for a, b in zip(edges[0::2], edges[1::2]):
            st += Trace(x[a:b], header={"network": NET, "station": STA, "location": LOC, "channel": ch,
                                        "sampling_rate": RATE, "starttime": DAY + a / RATE})
    return st


def cut(st: Stream, start: UTCDateTime, end: UTCDateTime) -> Stream:
    """A copy of `st` restricted to [start, end)."""
    return st.slice(start, end - 1e-6).copy()


if __name__ == "__main__":
    import sys
    from pathlib import Path

    out = Path(sys.argv[1] if len(sys.argv) > 1 else "demo_day.mseed")
    make_day().write(str(out), format="MSEED")
    print("wrote", out, out.stat().st_size // 1_000_000, "MB")
