"""Turn a Selection into processed data and write it as miniSEED, CSV, PNG or PDF."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # the app renders files on a server, never on screen

import numpy as np
from obspy import Inventory, Stream

from rs3d.core.models import Selection
from rs3d.core.store import Store


def process(st: Stream, sel: Selection, inventory: Inventory | None = None) -> Stream:
    """Apply the selection's units and filter. Returns a new Stream; gaps stay gaps."""
    st = st.copy()
    if sel.units == "m/s":
        if inventory is None:
            raise ValueError("units 'm/s' need an instrument response (inventory)")
        st.remove_response(inventory=inventory, output="VEL")
    if sel.filter is not None:
        fmin, fmax = sel.filter
        st.detrend("demean")
        st.filter("bandpass", freqmin=fmin, freqmax=fmax, corners=4, zerophase=True)
    return st


def load_processed(store: Store, sel: Selection, inventory: Inventory | None = None) -> Stream:
    return process(store.load(sel), sel, inventory)


def write_mseed(st: Stream, path: Path) -> Path:
    st.write(str(path), format="MSEED")
    return path


def write_plot(st: Stream, path: Path) -> Path:
    """PNG or PDF, chosen by the file extension."""
    if path.suffix.lower() not in (".png", ".pdf"):
        raise ValueError("plot path must end in .png or .pdf")
    st.plot(outfile=str(path), size=(1200, 300 * max(len({tr.id for tr in st}), 1)))
    return path


def write_csv(st: Stream, path: Path, channels: tuple[str, ...]) -> Path:
    """One row per sample: time_utc, then one column per channel. Missing samples are empty."""
    rates = {tr.stats.sampling_rate for tr in st}
    if len(rates) > 1:
        raise ValueError(f"all channels need the same sampling rate, got {sorted(rates)}")
    if not st:
        path.write_text("time_utc," + ",".join(channels) + "\n", encoding="utf-8")
        return path
    rate = rates.pop()
    t0 = min(tr.stats.starttime for tr in st)
    t1 = max(tr.stats.endtime for tr in st)
    n = int(round((t1 - t0) * rate)) + 1
    table = np.full((n, len(channels)), np.nan)
    for col, channel in enumerate(channels):
        for tr in st.select(channel=channel):
            i0 = int(round((tr.stats.starttime - t0) * rate))
            table[i0:i0 + tr.stats.npts, col] = tr.data
    base = np.datetime64(t0.datetime, "us")
    times = base + (np.arange(n) * (1e6 / rate)).round().astype("timedelta64[us]")
    stamps = np.datetime_as_string(times, unit="us")
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_utc", *channels])
        for stamp, row in zip(stamps, table):
            w.writerow([stamp + "Z", *("" if np.isnan(v) else repr(float(v)) for v in row)])
    return path
