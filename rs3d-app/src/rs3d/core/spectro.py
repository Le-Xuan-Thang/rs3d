"""Spectrogram of one trace: power in dB per (frequency, window), NaN where the window touches a gap."""

from __future__ import annotations

import numpy as np
from obspy import Trace
from scipy import signal


def window_for(duration_s: float) -> float:
    """Window length in seconds: finer for short selections, coarser for long ones."""
    return float(min(max(duration_s / 360.0, 1.0), 600.0))


def spectrogram(tr: Trace, window_s: float, overlap: float = 0.5) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (times, freqs, power_db). times are epoch seconds of window centres, power_db is (freqs, times)."""
    rate = tr.stats.sampling_rate
    data = tr.data
    bad = np.ma.getmaskarray(data) | ~np.isfinite(np.ma.getdata(data).astype(float))
    values = np.ma.getdata(data).astype(float)
    values[bad] = 0.0
    nperseg = max(int(round(window_s * rate)), 8)
    noverlap = int(nperseg * overlap)
    freqs, t, power = signal.spectrogram(values - values[~bad].mean() if (~bad).any() else values, fs=rate,
                                         nperseg=nperseg, noverlap=noverlap, detrend="constant", mode="psd")
    with np.errstate(divide="ignore"):
        db = 10.0 * np.log10(power)
    step = nperseg - noverlap
    for i in range(db.shape[1]):
        if bad[i * step:i * step + nperseg].any():
            db[:, i] = np.nan
    return t + tr.stats.starttime.timestamp, freqs, db
