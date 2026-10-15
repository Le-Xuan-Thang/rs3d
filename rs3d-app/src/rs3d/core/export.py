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


def clipboard_title(net: str, sta: str, loc: str, channel: str, start, end, units: str,
                    band: tuple[float, float] | None) -> str:
    text = (f"{net}.{sta}.{loc}.{channel}  {start.strftime('%Y-%m-%d %H:%M:%S')} → "
            f"{end.strftime('%H:%M:%S')} UTC  {units}")
    if band is not None:
        text += f"  band-pass {band[0]:g}–{band[1]:g} Hz"
    return text


def write_clipboard_png(st: Stream, path: Path, title: str, ylabel: str = "amplitude") -> Path:
    """Waveform, spectrogram and amplitude spectrum of the first channel, stacked, as one PNG."""
    if not len(st):
        raise ValueError("no data")
    import matplotlib.pyplot as plt

    from rs3d.core.spectro import amplitude_spectrum, spectrogram, window_for

    tr = st.copy().merge(method=0)[0]
    data = np.ma.filled(tr.data.astype(float), np.nan)
    t = np.arange(tr.stats.npts) / tr.stats.sampling_rate
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 9), constrained_layout=True)
    ax1.plot(t, data, lw=0.6, color="#444444")
    ax1.set_xlim(0, t[-1] if len(t) else 1)
    ax1.set_ylabel(ylabel)
    times, freqs, db = spectrogram(tr, window_for(tr.stats.endtime - tr.stats.starttime))
    ax2.pcolormesh(times - tr.stats.starttime.timestamp, freqs, db, shading="auto", cmap="inferno")
    ax2.set_xlim(0, t[-1] if len(t) else 1)
    ax2.set_ylabel("f in Hz")
    f, a = amplitude_spectrum(tr)
    if len(f):
        ax3.loglog(f, a, color="#e53935", lw=0.8)
    ax3.set_xlabel("Frequency in Hz")
    ax3.set_ylabel("Amplitude")
    ax3.grid(True, which="both", alpha=0.3)
    fig.suptitle(title)
    fig.savefig(str(path), dpi=100)
    plt.close(fig)
    return path
