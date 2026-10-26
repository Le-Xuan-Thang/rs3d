"""Overview of a time range for the Frequencies page: decimated waveforms and a frequency-versus-time map."""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np

from rs3d.core.live import minmax_decimate
from rs3d.core.models import Selection
from rs3d.core.spectro import spectrogram, window_for
from rs3d.core.store import Store

FMAX = 40.0  # Hz shown in the frequency-versus-time map
MAX_ROWS = 320  # frequency rows kept per map
CHUNK = 86400  # seconds loaded at a time


@dataclass
class Preview:
    start: float  # epoch seconds
    end: float
    window_s: float  # length of one spectrogram window
    waveforms: dict[str, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict)  # channel -> (t, counts)
    maps: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = field(default_factory=dict)  # (times, freqs, dB)


def _group_mean(a: np.ndarray, groups: int, axis: int) -> np.ndarray:
    """Average `a` down to `groups` slices along `axis` (NaN-aware: a group of only NaN stays NaN)."""
    n = a.shape[axis]
    if n <= groups:
        return a
    edges = np.linspace(0, n, groups + 1).astype(int)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN slices are gaps, not errors
        parts = [np.nanmean(np.take(a, range(lo, hi), axis=axis), axis=axis) for lo, hi in zip(edges[:-1], edges[1:])]
    return np.stack(parts, axis=axis)


def build_preview(store: Store, sel: Selection, max_points: int = 2000, max_columns: int = 480) -> Preview:
    """Load `sel` a day at a time. Waveforms are min/max decimated (counts, offset removed); the map is the
    spectrogram in dB up to FMAX Hz, averaged down to a size the browser can draw."""
    duration = sel.end - sel.start
    window_s = window_for(duration)
    out = Preview(sel.start.timestamp, sel.end.timestamp, window_s)
    waves: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {ch: [] for ch in sel.channels}
    maps: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {ch: [] for ch in sel.channels}
    freqs: dict[str, np.ndarray] = {}
    t = sel.start
    while t < sel.end:
        t_end = min(t + CHUNK, sel.end)
        share = (t_end - t) / duration
        st = store.load(Selection(sel.network, sel.station, sel.location, t, t_end, channels=sel.channels))
        st.merge(method=0)
        for ch in sel.channels:
            for tr in st.select(channel=ch):
                data = np.ma.filled(tr.data.astype(float), np.nan)
                times = tr.stats.starttime.timestamp + np.arange(len(data)) / tr.stats.sampling_rate
                waves[ch].append(minmax_decimate(times, data, max(int(max_points * share), 16))
                                 if len(data) > max_points * share else (times, data))
                if tr.stats.npts * tr.stats.delta >= 2 * window_s:
                    ts, f, db = spectrogram(tr, window_s)
                    keep = (f > 0) & (f <= FMAX)
                    freqs[ch] = f[keep]
                    cols = max(int(max_columns * share), 8)
                    maps[ch].append((_group_mean(ts[None, :], cols, 1)[0], _group_mean(db[keep], cols, 1)))
        t = t_end
    for ch in sel.channels:
        if waves[ch]:
            tt = np.concatenate([w[0] for w in waves[ch]])
            vv = np.concatenate([w[1] for w in waves[ch]])
            out.waveforms[ch] = (tt, vv - np.nanmedian(vv) if np.isfinite(vv).any() else vv)
        if maps[ch]:
            ts = np.concatenate([m[0] for m in maps[ch]])
            db = np.concatenate([m[1] for m in maps[ch]], axis=1)
            rows = min(len(freqs[ch]), MAX_ROWS)
            out.maps[ch] = (ts, _group_mean(freqs[ch][:, None], rows, 0)[:, 0], _group_mean(db, rows, 0))
    return out
