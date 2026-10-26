"""Find the frequencies a structure vibrates at: Welch spectra of many blocks, median + peak picking.

Method (the same as the room-floor study): cut the selection into blocks, estimate a Welch PSD per block and
channel, take the median over blocks, and report the peaks that stand out. A peak that shows up in most blocks is a
stable line (structure or a steady machine); one that shows up rarely is probably an event.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from obspy import Inventory, Stream, UTCDateTime
from scipy import signal

from rs3d.core.models import Selection
from rs3d.core.store import Store

BLOCKS = (300, 600, 900, 1200, 1800)  # seconds; all divide a day
BAND = (0.7, 35.0)  # Hz searched for peaks
PROMINENCE_DB = 6.0  # a candidate must stand this far above its surroundings in the median spectrum
OCCURRENCE_DB = 3.0  # ...and this far in a single block to count as "present" there
MIN_SEPARATION_HZ = 0.25
TOP_PEAKS = 6
CLIP_COUNTS = 0.99 * 2 ** 23  # blocks at the digitizer limit are skipped
MAX_NPERSEG = 8192


@dataclass(frozen=True)
class Peak:
    freq: float
    level_db: float
    prominence_db: float
    contrast_db: float  # peak against the median of its sidebands 0.08-0.30 Hz away
    occurrence: float  # fraction of blocks that contain this peak
    p10: float  # frequency spread of the matched peaks
    p90: float


@dataclass
class ChannelResult:
    channel: str
    freqs: np.ndarray
    p10_db: np.ndarray
    median_db: np.ndarray
    p90_db: np.ndarray
    n_blocks: int
    peaks: list[Peak] = field(default_factory=list)


@dataclass
class Analysis:
    start: UTCDateTime
    end: UTCDateTime
    units: str
    block_s: int
    nperseg: int
    resolution_hz: float
    hours_used: float
    skipped: dict[str, int]  # reason -> number of blocks
    channels: dict[str, ChannelResult]


def block_length(duration_s: float) -> int:
    """About 20 blocks for the selection, between 5 and 30 minutes, so occurrence rates mean something."""
    want = duration_s / 20.0
    return max((b for b in BLOCKS if b <= want), default=BLOCKS[0])


def welch_db(data: np.ndarray, rate: float, nperseg: int) -> tuple[np.ndarray, np.ndarray]:
    """(freqs, PSD in dB) of one block: Hann window, 50 % overlap, linear detrend."""
    freqs, psd = signal.welch(data, fs=rate, window="hann", nperseg=nperseg, noverlap=nperseg // 2,
                              detrend="linear", scaling="density")
    with np.errstate(divide="ignore"):
        return freqs, 10.0 * np.log10(psd)


def pick_peaks(freqs: np.ndarray, db: np.ndarray, prominence: float = PROMINENCE_DB, band: tuple[float, float] = BAND,
               min_sep: float = MIN_SEPARATION_HZ, top: int | None = TOP_PEAKS) -> list[tuple[float, float, float]]:
    """[(freq, level_db, prominence_db)] of the most prominent peaks inside `band`, strongest first."""
    df = float(freqs[1] - freqs[0])
    ok = np.isfinite(db)
    idx, props = signal.find_peaks(np.where(ok, db, np.nanmin(db[ok]) if ok.any() else 0.0),
                                   prominence=prominence, distance=max(1, int(round(min_sep / df))))
    found = [(float(freqs[i]), float(db[i]), float(p)) for i, p in zip(idx, props["prominences"])
             if band[0] <= freqs[i] <= band[1]]
    found.sort(key=lambda x: -x[2])
    return found[:top] if top else found


def contrast_db(freqs: np.ndarray, db: np.ndarray, f0: float) -> float:
    side = (np.abs(freqs - f0) >= 0.08) & (np.abs(freqs - f0) <= 0.30)
    here = np.argmin(np.abs(freqs - f0))
    return float(db[here] - np.median(db[side])) if side.any() else float("nan")


def occurrence(freqs: np.ndarray, block_dbs: np.ndarray, f0: float) -> tuple[float, float, float]:
    """(fraction of blocks with a peak near f0, p10, p90 of those peaks' frequencies)."""
    tol = max(0.05, 2.0 * float(freqs[1] - freqs[0]))
    hits = []
    for db in block_dbs:
        near = [f for f, _, _ in pick_peaks(freqs, db, OCCURRENCE_DB, band=(f0 - tol, f0 + tol), min_sep=0.0, top=1)]
        if near:
            hits.append(near[0])
    if not hits:
        return 0.0, f0, f0
    lo, hi = np.percentile(hits, [10, 90])
    return len(hits) / len(block_dbs), float(lo), float(hi)


def summarise(channel: str, freqs: np.ndarray, block_dbs: np.ndarray) -> ChannelResult:
    """Median and 10-90 % over blocks, and the peaks of the median."""
    p10, med, p90 = np.nanpercentile(block_dbs, [10, 50, 90], axis=0)
    result = ChannelResult(channel, freqs, p10, med, p90, len(block_dbs))
    for f, level, prom in pick_peaks(freqs, med):
        occ, lo, hi = occurrence(freqs, block_dbs, f)
        result.peaks.append(Peak(f, level, prom, contrast_db(freqs, med, f), occ, lo, hi))
    return result


def _nperseg(block_s: float, rate: float) -> int:
    """8192 samples (82 s at 100 Hz) when the block holds at least 4 of them, else the largest power of two that does."""
    n = int(block_s * rate)
    return MAX_NPERSEG if n >= 4 * MAX_NPERSEG else max(64, 2 ** int(np.log2(max(n // 4, 64))))


def analyse(store: Store, sel: Selection, inventory: Inventory | None = None, *, block_s: int | None = None,
            progress: Callable[[float], None] | None = None) -> Analysis:
    """Spectra and peaks for the selection. Units "m/s" need `inventory`; PSD is then in (m/s)^2/Hz.

    Blocks with a gap, too few samples or samples at the digitizer limit are skipped (and counted).
    """
    duration = sel.end - sel.start
    block_s = block_s or block_length(duration)
    skipped = {"gap": 0, "clipped": 0, "short": 0}
    collected: dict[str, list[np.ndarray]] = {ch: [] for ch in sel.channels}
    freqs: dict[str, np.ndarray] = {}
    used = 0.0
    nperseg = MAX_NPERSEG
    chunk = 86400  # load one day at a time; day files are what the store reads anyway
    t = sel.start
    while t < sel.end:
        t_end = min(t + chunk, sel.end)
        st = store.load(Selection(sel.network, sel.station, sel.location, t, t_end, channels=sel.channels))
        st.merge(method=0)
        b0 = t
        while b0 < t_end:
            b1 = min(b0 + block_s, t_end)
            if b1 - b0 >= max(block_s / 3.0, 60.0):
                for ch in sel.channels:
                    seg = st.select(channel=ch).slice(b0, b1 - 1e-6, nearest_sample=False)
                    reason = _block_problem(seg, b1 - b0)
                    if reason:
                        skipped[reason] += 1
                        continue
                    tr = seg[0]
                    if sel.units == "m/s":
                        tr = _to_velocity(tr, inventory)
                    rate = tr.stats.sampling_rate
                    nperseg = _nperseg(b1 - b0, rate)
                    f, db = welch_db(tr.data.astype(float), rate, nperseg)
                    freqs[ch] = f
                    collected[ch].append(db)
                    used += (b1 - b0) / len(sel.channels)
            b0 = b1
        t = t_end
        if progress:
            progress(min(1.0, (t - sel.start) / duration))
    channels = {ch: summarise(ch, freqs[ch], np.array(dbs)) for ch, dbs in collected.items() if dbs}
    rate = next((r.freqs[1] for r in channels.values()), 0.0)
    return Analysis(sel.start, sel.end, sel.units, block_s, nperseg, float(rate), used / 3600.0, skipped, channels)


def _block_problem(seg: Stream, length_s: float) -> str | None:
    if len(seg) != 1 or np.ma.is_masked(seg[0].data):
        return "gap"
    tr = seg[0]
    if tr.stats.npts / tr.stats.sampling_rate < 0.95 * length_s:
        return "short" if len(seg) else "gap"
    if np.abs(tr.data).max() >= CLIP_COUNTS:
        return "clipped"
    return None


def _to_velocity(tr, inventory: Inventory | None):
    if inventory is None:
        raise ValueError("units 'm/s' need an instrument response (inventory)")
    tr = tr.copy()
    tr.detrend("demean")
    tr.taper(0.05)
    tr.remove_response(inventory=inventory, output="VEL", pre_filt=(0.2, 0.4, 40.0, 45.0), water_level=60)
    return tr


STABLE = 0.8  # a line present in at least this share of the blocks counts as stable


def stable_lines(analysis: Analysis, tol: float = 0.15) -> list[tuple[float, list[str], float]]:
    """[(freq, channels, lowest occurrence)] of the stable peaks, merged across channels, strongest first."""
    merged: list[dict] = []
    for ch, r in analysis.channels.items():
        for p in r.peaks:
            if p.occurrence < STABLE:
                continue
            for m in merged:
                if abs(m["freq"] - p.freq) <= tol:
                    m["channels"].append(ch)
                    m["occ"] = min(m["occ"], p.occurrence)
                    m["prom"] = max(m["prom"], p.prominence_db)
                    break
            else:
                merged.append({"freq": p.freq, "channels": [ch], "occ": p.occurrence, "prom": p.prominence_db})
    merged.sort(key=lambda m: -m["prom"])
    return [(m["freq"], m["channels"], m["occ"]) for m in merged]
