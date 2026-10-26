"""Write a frequency analysis as CSV (peaks, spectra) or a figure (PNG/PDF)."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # files are rendered on the server, never on screen

import matplotlib.pyplot as plt

from rs3d.core.frequencies import Analysis

COLORS = {"Z": "#0B4F6C", "N": "#F15A24", "E": "#475569"}


def unit_label(units: str) -> str:
    return "dB re 1 (m/s)²/Hz" if units == "m/s" else "dB re 1 count²/Hz"


def write_peaks_csv(a: Analysis, path: Path) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["channel", "frequency_hz", "level_db", "prominence_db", "contrast_db", "occurrence_percent",
                    "freq_p10_hz", "freq_p90_hz"])
        for ch, r in a.channels.items():
            for p in r.peaks:
                w.writerow([ch, f"{p.freq:.4f}", f"{p.level_db:.2f}", f"{p.prominence_db:.2f}",
                            f"{p.contrast_db:.2f}", f"{100 * p.occurrence:.1f}", f"{p.p10:.4f}", f"{p.p90:.4f}"])
    return path


def write_spectra_csv(a: Analysis, path: Path) -> Path:
    chans = list(a.channels.values())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["frequency_hz", *(f"{r.channel}_{k}_db" for r in chans for k in ("p10", "median", "p90"))])
        if chans:
            for i, hz in enumerate(chans[0].freqs):
                w.writerow([f"{hz:.5f}", *(f"{v[i]:.2f}" for r in chans for v in (r.p10_db, r.median_db, r.p90_db))])
    return path


def write_figure(a: Analysis, path: Path, title: str = "") -> Path:
    """Median spectrum with the 10-90 % band: linear 0-40 Hz on top, log frequency below. PNG or PDF by extension."""
    if path.suffix.lower() not in (".png", ".pdf"):
        raise ValueError("figure path must end in .png or .pdf")
    fig, axes = plt.subplots(2, 1, figsize=(10, 8), constrained_layout=True)
    for ax, log in zip(axes, (False, True)):
        for ch, r in a.channels.items():
            color = COLORS.get(ch[-1:], None)
            keep = r.freqs > 0
            ax.fill_between(r.freqs[keep], r.p10_db[keep], r.p90_db[keep], color=color, alpha=0.15, lw=0)
            ax.plot(r.freqs[keep], r.median_db[keep], color=color, lw=1.2, label=ch)
            for p in r.peaks:
                ax.plot(p.freq, p.level_db, "v", color=color, ms=6)
                if not log:
                    ax.annotate(f"{p.freq:.2f}", (p.freq, p.level_db), textcoords="offset points", xytext=(0, 8),
                                ha="center", fontsize=8, color=color)
        ax.set_xscale("log" if log else "linear")
        ax.set_xlim(0.5 if log else 0, 45 if log else 40)
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel(unit_label(a.units))
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right")
    axes[0].set_title(title or f"Median spectrum, {a.hours_used:.1f} h in blocks of {a.block_s // 60} min "
                      f"(band: 10-90 % of blocks)")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
