"""Overview of a time range for the Frequencies page: decimated waveforms, a day at a time."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from rs3d.core.live import minmax_decimate
from rs3d.core.models import Selection
from rs3d.core.store import Store

CHUNK = 86400  # seconds loaded at a time


@dataclass
class Preview:
    start: float  # epoch seconds
    end: float
    waveforms: dict[str, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict)  # channel -> (t, counts)


def build_preview(store: Store, sel: Selection, max_points: int = 2000) -> Preview:
    """Load `sel` a day at a time. Waveforms are min/max decimated (counts, offset removed), gaps are NaN."""
    duration = sel.end - sel.start
    out = Preview(sel.start.timestamp, sel.end.timestamp)
    waves: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {ch: [] for ch in sel.channels}
    t = sel.start
    while t < sel.end:
        t_end = min(t + CHUNK, sel.end)
        budget = max(int(max_points * (t_end - t) / duration), 16)
        st = store.load(Selection(sel.network, sel.station, sel.location, t, t_end, channels=sel.channels))
        st.merge(method=0)
        for ch in sel.channels:
            for tr in st.select(channel=ch):
                data = np.ma.filled(tr.data.astype(float), np.nan)
                times = tr.stats.starttime.timestamp + np.arange(len(data)) / tr.stats.sampling_rate
                waves[ch].append(minmax_decimate(times, data, budget) if len(data) > budget else (times, data))
        t = t_end
    for ch in sel.channels:
        if waves[ch]:
            tt = np.concatenate([w[0] for w in waves[ch]])
            vv = np.concatenate([w[1] for w in waves[ch]])
            out.waveforms[ch] = (tt, vv - np.nanmedian(vv) if np.isfinite(vv).any() else vv)
    return out
