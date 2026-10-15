"""Build every plot of the theory manual from the demo recording, using the app's own functions.

Run from rs3d-app so the project's environment is used:
    cd rs3d-app && uv run python ../docs/manual/scripts/make_figures.py [name ...]
With no names every figure is built. Output: docs/manual/figures/<name>.pdf
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from obspy import Stream, Trace, UTCDateTime
from scipy import signal

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import demo_data as dd  # noqa: E402

from rs3d.core.helicorder import build_rows, scale_for  # noqa: E402
from rs3d.core.live import minmax_decimate  # noqa: E402
from rs3d.core.spectro import amplitude_spectrum, psd_summary, spectrogram, window_for  # noqa: E402

FIG = HERE.parent / "figures"
BUILD = HERE.parent / "build"
BLUE, DARK, GREY, RED, GREEN, PINK, AMBER = "#2F6FDE", "#263238", "#607D8B", "#D23C3C", "#2E9E4F", "#EC407A", "#F9A825"
W = 6.2  # text width in inches

plt.rcParams.update({
    "font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8, "legend.fontsize": 7, "xtick.labelsize": 7,
    "ytick.labelsize": 7, "axes.edgecolor": GREY, "axes.labelcolor": DARK, "xtick.color": DARK,
    "ytick.color": DARK, "text.color": DARK, "axes.grid": True, "grid.color": "#CFD8DC", "grid.linewidth": 0.4,
    "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 0.9, "pdf.fonttype": 42,
    "savefig.bbox": "tight", "savefig.pad_inches": 0.03, "figure.dpi": 150,
})

FIGURES: dict = {}
_cache: dict = {}


def figure(fn):
    FIGURES[fn.__name__.removeprefix("fig_").replace("_", "-")] = fn
    return fn


def save(fig, name: str) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / f"{name}.pdf")
    plt.close(fig)
    print("  wrote", name)


def day() -> Stream:
    """The demo day (cached on disk as miniSEED)."""
    if "day" not in _cache:
        BUILD.mkdir(parents=True, exist_ok=True)
        path = BUILD / "demo_day.mseed"
        if not path.exists():
            dd.make_day().write(str(path), format="MSEED")
        from obspy import read
        _cache["day"] = read(str(path))
    return _cache["day"]


def seg(channel: str, t0: str | UTCDateTime, t1: str | UTCDateTime, demean: bool = True) -> Trace:
    """One merged trace of `channel` between t0 and t1 (strings are times on the demo day)."""
    a = UTCDateTime(f"2026-10-15T{t0}") if isinstance(t0, str) else t0
    b = UTCDateTime(f"2026-10-15T{t1}") if isinstance(t1, str) else t1
    st = dd.cut(day().select(channel=channel), a, b)
    tr = st.merge(method=0)[0]
    if demean:
        tr.data = tr.data.astype(float) - np.ma.mean(tr.data)
    return tr


def tvec(tr: Trace) -> np.ndarray:
    return np.arange(tr.stats.npts) / tr.stats.sampling_rate


# =========================================================================================== fundamentals
@figure
def fig_aliasing():
    fs = 100.0
    t = np.linspace(0, 0.4, 4000)
    n = np.arange(0, 41)
    fig, ax = plt.subplots(figsize=(W, 2.0))
    ax.plot(t, np.cos(2 * np.pi * 10 * t), color=BLUE, label="10 Hz (below Nyquist)")
    ax.plot(t, np.cos(2 * np.pi * 90 * t), color=PINK, lw=0.6, label="90 Hz (above Nyquist)")
    ax.plot(n / fs, np.cos(2 * np.pi * 10 * n / fs), "o", color=DARK, ms=3, label="samples at 100 Hz (identical)")
    ax.set(xlabel="time (s)", ylabel="amplitude", xlim=(0, 0.4))
    ax.legend(loc="upper right", ncol=3, frameon=False, bbox_to_anchor=(1.0, 1.22))
    save(fig, "theory-aliasing")


@figure
def fig_response():
    f = np.logspace(-1, 2, 600)
    f0 = 4.5
    fig, (a, b) = plt.subplots(1, 2, figsize=(W, 2.3), constrained_layout=True)
    for h, col in ((0.5, GREY), (0.707, BLUE)):
        s = 1j * f / f0
        T = s**2 / (s**2 + 2 * h * s + 1)
        a.semilogx(f, 20 * np.log10(np.abs(T)), color=col, label=f"damping h = {h}")
        b.semilogx(f, np.degrees(np.unwrap(np.angle(T))), color=col)
    a.axvline(f0, color=RED, lw=0.6, ls="--")
    b.axvline(f0, color=RED, lw=0.6, ls="--")
    a.text(f0 * 1.08, -52, "$f_0$ = 4.5 Hz", color=RED, fontsize=7)
    a.set(xlabel="frequency (Hz)", ylabel="amplitude (dB re. flat band)", ylim=(-60, 5))
    b.set(xlabel="frequency (Hz)", ylabel="phase (degrees)")
    a.legend(frameon=False, loc="upper left")
    save(fig, "theory-response")


@figure
def fig_butterworth():
    fs = 100.0
    fig, ax = plt.subplots(figsize=(W, 2.6))
    for order, col in ((2, GREY), (4, BLUE)):
        sos = signal.butter(order, [1, 10], btype="bandpass", fs=fs, output="sos")
        w, h = signal.sosfreqz(sos, worN=np.logspace(-1.5, np.log10(49.9), 800), fs=fs)
        ax.semilogx(w, 20 * np.log10(np.abs(h) + 1e-12), color=col, label=f"order {order}, one pass")
        if order == 4:
            ax.semilogx(w, 40 * np.log10(np.abs(h) + 1e-12), color=PINK, label="order 4, forward + backward (zero phase)")
    ax.axhline(-3, color=GREY, lw=0.5, ls=":")
    ax.axhline(-6, color=PINK, lw=0.5, ls=":")
    ax.text(0.035, -2.4, "−3 dB", fontsize=6.5, color=GREY)
    ax.text(0.035, -5.4, "−6 dB", fontsize=6.5, color=PINK)
    ax.set(xlabel="frequency (Hz)", ylabel="gain (dB)", ylim=(-60, 3), xlim=(0.03, 50))
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3)
    save(fig, "theory-butterworth")


@figure
def fig_zerophase():
    fs = 100.0
    t = np.arange(0, 12, 1 / fs)
    onset = 6.0
    x = np.where(t > onset, np.sin(2 * np.pi * 4 * (t - onset)) * np.exp(-(t - onset) / 1.5), 0.0)
    sos = signal.butter(4, [1, 10], btype="bandpass", fs=fs, output="sos")
    causal = signal.sosfilt(sos, x)
    zero = signal.sosfiltfilt(sos, x)
    rows = ((x, GREY, "input: silence, then an arrival at 6 s"),
            (causal, BLUE, "causal band-pass 1–10 Hz (one pass)"),
            (zero, PINK, "zero-phase band-pass 1–10 Hz (forward + backward)"))
    fig, axes = plt.subplots(3, 2, figsize=(W, 3.6), gridspec_kw={"width_ratios": [2.2, 1]}, constrained_layout=True)
    for (y, col, title), (a_full, a_zoom) in zip(rows, axes):
        a_full.plot(t, y, color=col)
        a_full.set_title(title, loc="left")
        a_zoom.plot(t, y, color=col)
        a_zoom.set(xlim=(4.5, 6.5), ylim=(-0.06, 0.06))
        for ax in (a_full, a_zoom):
            ax.axvline(onset, color=RED, lw=0.6, ls="--")
        a_full.set_ylabel("amplitude")
    axes[0, 1].set_title("zoom: amplitude ±0.06", loc="left")
    axes[2, 1].annotate("energy before\nthe true onset", xy=(5.7, 0.012), xytext=(4.6, 0.04), fontsize=6.5, color=RED,
                        arrowprops=dict(arrowstyle="->", color=RED, lw=0.6))
    axes[2, 0].set_xlabel("time (s)")
    axes[2, 1].set_xlabel("time (s)")
    save(fig, "theory-zerophase")


# =========================================================================================== spectral analysis
@figure
def fig_window_leakage():
    fs, n = 100.0, 1000
    t = np.arange(n) / fs
    x = np.cos(2 * np.pi * 5.05 * t) + 0.003 * np.cos(2 * np.pi * 8.0 * t)
    nfft = 2**16
    f = np.fft.rfftfreq(nfft, 1 / fs)
    fig, ax = plt.subplots(figsize=(W, 2.5))
    for name, w, col in (("rectangular", np.ones(n), GREY), ("Hann", np.hanning(n), BLUE)):
        X = np.abs(np.fft.rfft(x * w, nfft)) * 2 / w.sum()
        ax.plot(f, 20 * np.log10(X + 1e-12), color=col, label=name)
    ax.annotate("weak tone at 8 Hz\n(−50 dB)", xy=(8.0, -50), xytext=(8.6, -22), fontsize=7, color=RED,
                arrowprops=dict(arrowstyle="->", color=RED, lw=0.6))
    ax.set(xlim=(2, 12), ylim=(-110, 5), xlabel="frequency (Hz)", ylabel="amplitude (dB re. 1)")
    ax.legend(frameon=False)
    save(fig, "theory-window-leakage")


@figure
def fig_amplitude_scaling():
    fs = 100.0
    t = np.arange(0, 60, 1 / fs)
    rng = np.random.default_rng(5)
    x = 1000 * np.sin(2 * np.pi * 5 * t) + 150 * rng.normal(size=t.size)
    hdr = {"sampling_rate": fs, "starttime": UTCDateTime(0), "channel": "EHZ"}
    full = Trace(x.copy(), header=hdr)
    mask = np.zeros(t.size, bool)
    mask[2000:4000] = True
    gapped = Trace(np.ma.masked_array(x.copy(), mask=mask), header=hdr)
    fig, ax = plt.subplots(figsize=(W, 2.3))
    f1, a1 = amplitude_spectrum(full)
    f2, a2 = amplitude_spectrum(gapped)
    ax.plot(f1, a1, color=BLUE, label="complete trace")
    ax.plot(f2, a2, color=PINK, lw=0.7, label="20 s of 60 s masked (gap)")
    ax.axhline(1000, color=GREY, lw=0.6, ls="--")
    ax.text(10.5, 1060, "true amplitude 1000 counts", fontsize=7, color=GREY)
    ax.set(xlim=(0, 25), ylim=(0, 1300), xlabel="frequency (Hz)", ylabel="amplitude (counts)")
    ax.legend(frameon=False, loc="center right")
    save(fig, "theory-amplitude-scaling")


@figure
def fig_noise_spectrum():
    n_seg, seg_s = 24, 120
    t0 = UTCDateTime("2026-10-15T02:00:00")
    spectra = []
    for k in range(n_seg):
        tr = seg("EHZ", t0 + k * seg_s, t0 + (k + 1) * seg_s)
        f, a = amplitude_spectrum(tr)
        spectra.append(a)
    spectra = np.array(spectra)
    fig, ax = plt.subplots(figsize=(W, 2.6))
    ax.loglog(f, spectra[0], color=GREY, lw=0.5, label="one 2-minute window")
    ax.loglog(f, np.sqrt((spectra**2).mean(axis=0)), color=BLUE, lw=1.1, label=f"RMS average of {n_seg} windows (Welch)")
    ax.set(xlim=(0.05, 50), xlabel="frequency (Hz)", ylabel="amplitude (counts)")
    ax.legend(frameon=False)
    save(fig, "theory-noise-spectrum")


# =========================================================================================== spectrogram
def _specgram(ax, tr: Trace, win: float, fmax: float = 50.0, vmin=None, vmax=None, title=None):
    times, freqs, db = spectrogram(tr, win)
    rel = times - tr.stats.starttime.timestamp
    m = ax.pcolormesh(rel, freqs, db, shading="auto", cmap="inferno", vmin=vmin, vmax=vmax, rasterized=True)
    ax.set(ylim=(0, fmax), ylabel="frequency (Hz)")
    ax.grid(False)
    if title:
        ax.set_title(title, loc="left")
    return m


@figure
def fig_spectrogram_tradeoff():
    tr = seg("EHZ", "03:12:05", "03:13:35")
    fig, axes = plt.subplots(3, 1, figsize=(W, 5.0), sharex=True, constrained_layout=True)
    for ax, win in zip(axes, (0.5, 2.0, 10.0)):
        m = _specgram(ax, tr, win, fmax=30, vmin=0, vmax=75,
                      title=f"window {win:g} s  →  frequency resolution {1 / win:.2g} Hz, time resolution {win:g} s")
    axes[-1].set_xlabel("time since 03:12:05 UTC (s)")
    fig.colorbar(m, ax=axes, label="power (dB re. 1 count²/Hz)", shrink=0.8, pad=0.01)
    save(fig, "theory-spectrogram-tradeoff")


@figure
def fig_window_rule():
    T = np.logspace(np.log10(30), np.log10(86400), 300)
    N = np.array([window_for(x) for x in T])
    fig, (a, b) = plt.subplots(1, 2, figsize=(W, 2.4), constrained_layout=True)
    a.loglog(T / 60, N, color=BLUE)
    b.loglog(T / 60, 1 / N, color=PINK)
    for dur, lab in ((120, "2 min"), (3600, "1 h"), (6.7 * 3600, "6.7 h"), (86400, "24 h")):
        for ax, y in ((a, window_for(dur)), (b, 1 / window_for(dur))):
            ax.plot(dur / 60, y, "o", color=DARK, ms=3)
        a.annotate(lab, (dur / 60, window_for(dur)), textcoords="offset points", xytext=(-4, 6), fontsize=6.5, ha="right")
    a.set(xlabel="selected duration (min)", ylabel="window length (s)")
    b.set(xlabel="selected duration (min)", ylabel="frequency resolution (Hz)")
    save(fig, "theory-window-rule")


@figure
def fig_spectrogram_day():
    tr = seg("EHZ", "00:00:00", "23:59:59")
    times, freqs, db = spectrogram(tr, window_for(86400))
    hours = (times - tr.stats.starttime.timestamp) / 3600
    fig, ax = plt.subplots(figsize=(W, 3.0))
    m = ax.pcolormesh(hours, freqs, db, shading="auto", cmap="inferno", vmin=0, vmax=70, rasterized=True)
    ax.set(ylim=(0.0, 50), xlim=(0, 24), xlabel="hour of day (UTC)", ylabel="frequency (Hz)")
    ax.set_xticks(range(0, 25, 3))
    ax.grid(False)
    for hh, lab in ((3.2, "local\nquake"), (10.8, "bursts"), (14.67, "distant\nquake")):
        ax.annotate(lab, (hh, 47), color="white", fontsize=6.5, ha="center", va="top")
    ax.annotate("30 Hz line", (20.2, 30), color="white", fontsize=6.5, va="bottom")
    ax.annotate("gaps", (17.4, 4), color="white", fontsize=6.5, ha="center")
    fig.colorbar(m, ax=ax, label="power (dB re. 1 count²/Hz)", pad=0.01)
    save(fig, "theory-spectrogram-day")


@figure
def fig_psd_summary():
    fig, ax = plt.subplots(figsize=(W, 2.8))
    for (a, b, col, lab) in (("02:00:00", "03:00:00", BLUE, "night 02:00–03:00"),
                              ("12:00:00", "13:00:00", PINK, "midday 12:00–13:00")):
        tr = seg("EHZ", a, b)
        times, freqs, db = spectrogram(tr, window_for(3600))
        f, lo, med, hi = psd_summary(freqs, db)
        ax.semilogx(f, med, color=col, label=lab + " (median)")
        ax.fill_between(f, lo, hi, color=col, alpha=0.18, lw=0)
    ax.set(xlim=(0.02, 50), xlabel="frequency (Hz)", ylabel="power (dB re. 1 count²/Hz)")
    ax.legend(frameon=False, loc="lower left")
    for x, y, t in ((0.25, 53, "microseism"), (5, 43, "cultural noise"), (26, 47, "30 Hz line")):
        ax.annotate(t, (x, y), fontsize=7, color=GREY, ha="center")
    save(fig, "theory-psd-summary")


# =========================================================================================== visualisation
@figure
def fig_minmax():
    fs = 100.0
    n = 3000
    rng = np.random.default_rng(11)
    t = np.arange(n) / fs
    x = np.sin(2 * np.pi * 1.2 * t) + 0.25 * rng.normal(size=n)
    x[1500] += 4.0   # one-sample spike
    ms = 120
    ts, vs = t[:: n // ms], x[:: n // ms]
    tm, vm = minmax_decimate(t, x, ms)
    fig, axes = plt.subplots(3, 1, figsize=(W, 3.8), sharex=True, constrained_layout=True)
    axes[0].plot(t, x, color=DARK, lw=0.5)
    axes[0].set_title(f"raw: {n} samples", loc="left")
    axes[1].plot(ts, vs, color=GREY, lw=0.7)
    axes[1].set_title(f"every {n // ms}-th sample (stride): {ts.size} points, spike lost", loc="left")
    axes[2].plot(tm, vm, color=BLUE, lw=0.7)
    axes[2].set_title(f"min/max per bin (RS3D live and helicorder): {tm.size} points, spike kept", loc="left")
    for ax in axes:
        ax.set_ylim(-2.2, 5.2)
        ax.axvline(15.0, color=RED, lw=0.5, ls="--")
    axes[2].set_xlabel("time (s)")
    save(fig, "theory-minmax")


@figure
def fig_helicorder():
    st = day()
    d = dd.cut(st.select(channel="EHZ"), dd.DAY, dd.DAY + 86400)
    rows = build_rows(d, dd.DAY)
    s = scale_for(rows)
    fig, ax = plt.subplots(figsize=(W, 6.4))
    for i, r in enumerate(rows):
        ax.plot(r.seconds / 60, i - r.values / s, color=(DARK, PINK)[i % 2], lw=0.5)
    ax.set(xlim=(0, 30), ylim=(47.7, -0.8), xlabel="minutes within the row")
    ax.set_yticks(range(0, 48, 2))
    ax.set_yticklabels([f"{i // 2:02d}:00" for i in range(0, 48, 2)])
    ax.set_ylabel("UTC hour (row start)")
    ax.grid(axis="x", lw=0.3)
    ax.grid(False, axis="y")
    for (row, x, lab) in ((6, 12.3, "local quake"), (20, 5.0, "burst"), (23, 0.3, "burst"), (29, 12.0, "distant quake")):
        ax.annotate(lab, (x, row), xytext=(30.6, row), fontsize=6.5, color=RED, va="center", annotation_clip=False,
                    arrowprops=dict(arrowstyle="-", color=RED, lw=0.4, shrinkA=0, shrinkB=0))
    save(fig, "theory-helicorder")


@figure
def fig_dc_offset():
    tr = seg("EHZ", "01:00:00", "04:00:00", demean=False)
    st = Stream([tr])
    start = UTCDateTime("2026-10-15T01:00:00")
    base = build_rows(st, start - 2 * 1800)  # rows 2.. contain the data
    fig, axes = plt.subplots(1, 2, figsize=(W, 3.3), sharey=True, constrained_layout=True)
    rows = [r for r in base if len(r.values)][:6]
    for ax, remove, title in ((axes[0], False, "raw counts (DC offset ≈ 15 000)"),
                              (axes[1], True, "median of each row removed (RS3D)")):
        vals = []
        for r in rows:
            v = r.values.copy()
            if not remove:   # undo the median subtraction that build_rows applies
                v = v + 15000.0
            vals.append(v)
        flat = np.concatenate([np.abs(v[np.isfinite(v)] - (0 if remove else np.nanmedian(v))) for v in vals])
        s = 2 * np.percentile(np.abs(np.concatenate([v[np.isfinite(v)] for v in vals])), 99)
        for i, (r, v) in enumerate(zip(rows, vals)):
            ax.plot(r.seconds / 60, i - v / s, color=(DARK, PINK)[i % 2], lw=0.5)
        ax.set(xlim=(0, 30), ylim=(5.8, -1.2), xlabel="minutes within the row")
        ax.set_title(title, loc="left")
        ax.grid(False)
    axes[0].set_ylabel("row index")
    save(fig, "theory-dc-offset")


@figure
def fig_window_table():
    """Not a plot: writes figures/window-table.tex with the measured properties of the three windows."""
    from scipy.signal import windows
    n, pad = 1024, 64
    cases = (("Rectangular", np.ones(n), "(no taper)"),
             ("Hann", np.hanning(n), "amplitude spectrum"),
             ("Tukey, $\\alpha = 0.25$", windows.tukey(n, 0.25, sym=False), "spectrogram"))
    lines = [r"\setlength{\tabcolsep}{4pt}\begin{tabular}{@{}lccccl@{}}", r"\toprule",
             r"Window & $\sum w / N$ & ENBW & Main lobe & Sidelobe (dB) & Used for \\ \midrule"]
    for name, w, use in cases:
        W_ = np.abs(np.fft.rfft(w, n * pad))
        W_ /= W_[0]
        k = np.argmax(np.diff(W_) > 0)            # first null: spectrum starts rising again
        lobe = 2 * k / pad
        side = 20 * np.log10(W_[k:n * pad // 2].max())
        enbw = n * np.sum(w**2) / np.sum(w) ** 2
        lines.append(f"{name} & {np.sum(w) / n:.3f} & {enbw:.3f} & {lobe:.1f} & {side:.1f} & {use} \\\\".replace("& -", "& −"))
    lines += [r"\bottomrule", r"\end{tabular}"]
    (FIG / "window-table.tex").write_text("\n".join(lines) + "\n")
    print((FIG / "window-table.tex").read_text())


# =========================================================================================== event detection
from obspy.signal.trigger import classic_sta_lta, recursive_sta_lta, trigger_onset  # noqa: E402

BAND = (1.0, 10.0)
STA_S, LTA_S, THR_ON, THR_OFF, HOLD_OFF = 1.0, 30.0, 5.0, 2.0, 30.0


def causal_bandpass(x: np.ndarray, f1: float = BAND[0], f2: float = BAND[1], fs: float = 100.0) -> np.ndarray:
    """A causal (one-pass) band-pass: it never moves energy before the true arrival."""
    sos = signal.butter(4, [f1, f2], btype="bandpass", fs=fs, output="sos")
    return signal.sosfilt(sos, x - np.mean(x))


def _ratio(x: np.ndarray, sta: float, lta: float, kind: str = "classic") -> np.ndarray:
    fn = classic_sta_lta if kind == "classic" else recursive_sta_lta
    return fn(np.ascontiguousarray(x, dtype=float), int(sta * 100), int(lta * 100))


@figure
def fig_stalta_example():
    t_start = UTCDateTime("2026-10-15T03:10:40")
    tr = seg("EHZ", t_start, "03:14:00")
    x = causal_bandpass(tr.data.astype(float))
    t = tvec(tr) - 50.0                      # seconds relative to 03:11:30
    cf = x**2
    sta = classic_sta_lta(x, int(STA_S * 100), int(LTA_S * 100))
    # STA and LTA of the characteristic function (the ratio's numerator and denominator)
    csum = np.concatenate([[0], np.cumsum(cf)])
    n_s, n_l = int(STA_S * 100), int(LTA_S * 100)
    sta_v = np.full(cf.size, np.nan)
    lta_v = np.full(cf.size, np.nan)
    sta_v[n_l - 1:] = (csum[n_l:] - csum[n_l - n_s:-n_s]) / n_s if False else (csum[n_s:][n_l - n_s:] - csum[:-n_s][n_l - n_s:]) / n_s
    lta_v[n_l - 1:] = (csum[n_l:] - csum[:-n_l]) / n_l
    on_off = trigger_onset(sta, THR_ON, THR_OFF)
    fig, axes = plt.subplots(3, 1, figsize=(W, 5.4), sharex=True, constrained_layout=True)
    axes[0].plot(t, x, color=DARK, lw=0.5)
    axes[0].set(ylabel="counts", title="(a) band-passed 1–10 Hz, causal filter")
    axes[1].semilogy(t, sta_v, color=BLUE, label=f"STA ({STA_S:g} s)")
    axes[1].semilogy(t, lta_v, color=PINK, label=f"LTA ({LTA_S:g} s)")
    axes[1].set(ylabel="mean of x² (counts²)", title="(b) short-term and long-term average of the characteristic function x²")
    axes[1].legend(frameon=False, loc="upper right")
    axes[2].plot(t, sta, color=DARK)
    axes[2].axhline(THR_ON, color=RED, lw=0.7, ls="--")
    axes[2].axhline(THR_OFF, color=AMBER, lw=0.7, ls="--")
    axes[2].text(t[-1], THR_ON + 0.4, f"trigger ON {THR_ON:g}", color=RED, ha="right", fontsize=7)
    axes[2].text(t[-1], THR_OFF - 1.2, f"trigger OFF {THR_OFF:g}", color=AMBER, ha="right", fontsize=7)
    for on, off in on_off:
        for ax in axes:
            ax.axvspan(t[on], t[off], color=RED, alpha=0.08, lw=0)
    axes[2].set(ylabel="STA / LTA", xlabel="time since 03:11:30 UTC (s)", title="(c) STA/LTA ratio and trigger interval")
    p_arr = (dd.LOCAL_QUAKE - UTCDateTime("2026-10-15T03:11:30"))
    for ax in axes:
        ax.axvline(p_arr, color=GREEN, lw=0.7, ls=":")
    axes[0].text(p_arr + 0.8, axes[0].get_ylim()[1] * 0.75, "true P arrival", color=GREEN, fontsize=7)
    xmin = 0.0
    axes[0].set_xlim(xmin, 150)
    save(fig, "theory-stalta-example")


@figure
def fig_stalta_params():
    t_start = UTCDateTime("2026-10-15T03:10:40")
    tr = seg("EHZ", t_start, "03:14:00")
    x = causal_bandpass(tr.data.astype(float))
    t = tvec(tr) - 50.0
    fig, (a, b) = plt.subplots(1, 2, figsize=(W, 2.6), sharey=True, constrained_layout=True)
    for sta, col in ((0.3, GREY), (1.0, BLUE), (4.0, PINK)):
        a.plot(t, _ratio(x, sta, LTA_S), color=col, lw=0.8, label=f"STA = {sta:g} s")
    for lta, col in ((8.0, GREY), (30.0, BLUE), (100.0, PINK)):
        r = _ratio(x, STA_S, min(lta, 60.0 if False else lta))
        b.plot(t, r, color=col, lw=0.8, label=f"LTA = {lta:g} s")
    for ax, ttl in ((a, "LTA fixed at 30 s"), (b, "STA fixed at 1 s")):
        ax.axhline(THR_ON, color=RED, lw=0.6, ls="--")
        ax.set(xlim=(0, 150), xlabel="time since 03:11:30 UTC (s)", title=ttl, ylim=(0, 14))
        ax.legend(frameon=False, loc="upper right")
    a.set_ylabel("STA / LTA")
    save(fig, "theory-stalta-params")


@figure
def fig_stalta_compare():
    cases = (("local earthquake", dd.LOCAL_QUAKE, BLUE), ("noise burst (10:05)", dd.BURSTS[0], PINK),
             ("distant earthquake", dd.DISTANT_QUAKE, GREEN))
    fig, axes = plt.subplots(2, 1, figsize=(W, 4.2), sharex=True, constrained_layout=True)
    for name, t0, col in cases:
        tr = seg("EHZ", t0 - 70, t0 + 110)
        x = causal_bandpass(tr.data.astype(float))
        t = tvec(tr) - 70.0
        r = _ratio(x, STA_S, LTA_S, "recursive")
        axes[0].plot(t, x / np.abs(x[7000:]).max(), color=col, lw=0.4, label=name)
        axes[1].plot(t, r, color=col, lw=0.9, label=name)
    axes[0].set(ylabel="normalised amplitude", xlim=(-30, 110), title="band-passed 1–10 Hz, each normalised to its own maximum")
    axes[1].axhline(THR_ON, color=RED, lw=0.6, ls="--")
    axes[1].axhline(THR_OFF, color=AMBER, lw=0.6, ls="--")
    axes[1].set(ylabel="STA / LTA (recursive)", xlabel="time since the event start (s)", title="the same three events seen by the trigger")
    axes[1].legend(frameon=False, loc="upper right")
    save(fig, "theory-stalta-compare")


KNOWN = ((dd.LOCAL_QUAKE, "local earthquake"), (dd.DISTANT_QUAKE, "distant earthquake"),
         (dd.BURSTS[0], "noise burst"), (dd.BURSTS[1], "noise burst"))


def day_ratios() -> list[tuple[UTCDateTime, np.ndarray]]:
    """Recursive STA/LTA of every contiguous EHZ piece of the demo day (band-passed 1-10 Hz, causal)."""
    if "ratios" not in _cache:
        out = []
        for tr in sorted(day().select(channel="EHZ"), key=lambda q: q.stats.starttime):
            if tr.stats.npts >= (LTA_S + 5) * 100:
                out.append((tr.stats.starttime, _ratio(causal_bandpass(tr.data.astype(float)), STA_S, LTA_S, "recursive")))
        _cache["ratios"] = out
    return _cache["ratios"]


def detect(on: float, off: float, hold_off: float = HOLD_OFF) -> list[tuple[UTCDateTime, float, float, str]]:
    """Events (onset, duration s, peak ratio, cause): triggers closer than `hold_off` seconds are merged."""
    trig = []
    for t0, r in day_ratios():
        for a, b in trigger_onset(r, on, off):
            trig.append((t0 + a / 100, (b - a) / 100, float(r[a:b + 1].max())))
    trig.sort(key=lambda q: q[0].timestamp)
    merged: list[tuple[UTCDateTime, float, float]] = []
    for t_on, dur, peak in trig:
        if merged and t_on - (merged[-1][0] + merged[-1][1]) < hold_off:
            m = merged[-1]
            merged[-1] = (m[0], (t_on + dur) - m[0], max(m[2], peak))
        else:
            merged.append((t_on, dur, peak))
    events = []
    for t_on, dur, peak in merged:
        cause = next((name for t_k, name in KNOWN if abs(t_on - t_k) < 120), "unexplained")
        events.append((t_on, dur, peak, cause))
    return events


@figure
def fig_stalta_day():
    fig, ax = plt.subplots(figsize=(W, 2.6))
    for t0, r in day_ratios():
        hours = (t0 - dd.DAY) / 3600 + np.arange(r.size) / 100 / 3600
        k = 1000  # 10 s bins: draw the maximum so short peaks stay visible
        n = r.size // k * k
        ax.plot(hours[:n:k], r[:n].reshape(-1, k).max(axis=1), color=BLUE, lw=0.6)
    ax.axhline(THR_ON, color=RED, lw=0.6, ls="--")
    ax.text(23.9, THR_ON + 0.3, f"trigger ON = {THR_ON:g}", color=RED, ha="right", fontsize=7)
    for hh, lab in ((3.2, "local\nquake"), (10.8, "bursts"), (14.67, "distant\nquake")):
        ax.annotate(lab, (hh, 18), fontsize=6.5, ha="center", color=GREY)
    ax.set(xlim=(0, 24), ylim=(0, 24), xlabel="hour of day (UTC)", ylabel="STA / LTA (peak per 10 s)")
    ax.set_xticks(range(0, 25, 3))
    save(fig, "theory-stalta-day")
    events = detect(THR_ON, THR_OFF)
    lines = [r"\begin{tabular}{@{}lrrl@{}}", r"\toprule",
             r"Onset (UTC) & Duration (s) & Peak ratio & Cause \\ \midrule"]
    for t_on, dur, peak, cause in events:
        lines.append(f"{t_on.strftime('%H:%M:%S')} & {dur:.0f} & {peak:.1f} & {cause} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (FIG / "stalta-day-triggers.tex").write_text("\n".join(lines) + "\n")
    print("  events:", [(t.strftime("%H:%M:%S"), round(d_), round(p, 1), c) for t, d_, p, c in events])


@figure
def fig_stalta_sweep():
    thresholds = np.array([2.5, 3, 3.5, 4, 5, 6, 8, 10, 12, 14, 16])
    rows = []
    for on in thresholds:
        ev = detect(float(on), float(on) * 0.4)
        false = sum(1 for e in ev if e[3] == "unexplained")
        found = {k for e in ev for k, (t_k, _) in enumerate(KNOWN) if abs(e[0] - t_k) < 120}
        rows.append((false, len(found)))
    false = np.array([r[0] for r in rows])
    fig, ax = plt.subplots(figsize=(W, 2.6))
    ax.semilogy(thresholds, np.maximum(false, 0.7), "o-", color=PINK, ms=3, label="false alarms per day")
    ax.set(xlabel="trigger-on threshold (OFF = 0.4 × ON)", ylabel="false alarms per day (log; 0 plotted at 0.7)")
    ax2 = ax.twinx()
    ax2.step(thresholds, [r[1] for r in rows], where="mid", color=BLUE, label="real events found")
    ax2.set(ylabel="real events found (of 4)", ylim=(0, 4.3))
    ax2.grid(False)
    ax2.spines["right"].set_visible(True)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, frameon=False, loc="upper right")
    save(fig, "theory-stalta-sweep")
    print("  sweep:", list(zip(thresholds.tolist(), rows)))


@figure
def fig_stalta_null():
    """False alarms per day: stationary Gaussian noise (simulation + F-distribution theory) versus the demo day."""
    from scipy import stats
    thresholds = np.array([2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0])
    rng = np.random.default_rng(99)
    n = int(86400 * 100)
    x = causal_bandpass(dd._band(rng, n, 1.0, 20.0) * 100.0)   # stationary noise, same pass band as the detector
    r = _ratio(x, STA_S, LTA_S, "recursive")
    stat = []
    for on in thresholds:
        ev = trigger_onset(r, float(on), float(on) * 0.4)
        merged, last_end = 0, -1e9
        for a, b in ev:
            if a / 100 - last_end >= HOLD_OFF:
                merged += 1
            last_end = b / 100
        stat.append(merged)
    demo = [sum(1 for e in detect(float(on), float(on) * 0.4) if e[3] == "unexplained") for on in thresholds]
    nu1, nu2 = 2 * 9.0 * STA_S, 2 * 9.0 * LTA_S      # effective degrees of freedom: 2 B T, B ~ 9 Hz
    tail = stats.f.sf(thresholds, nu1, nu2)
    fig, ax = plt.subplots(figsize=(W, 2.7))
    ax.semilogy(thresholds, np.maximum(stat, 0.5), "o-", color=BLUE, ms=3, label="stationary Gaussian noise (simulated day)")
    ax.semilogy(thresholds, np.maximum(demo, 0.5), "s-", color=PINK, ms=3, label="demo day (non-stationary noise)")
    ax.set(xlabel="trigger-on threshold", ylabel="false alarms per day (0 plotted at 0.5)", ylim=(0.3, 2000))
    ax.legend(frameon=False, loc="upper right", fontsize=6.5)
    save(fig, "theory-stalta-null")
    rows = [r"\begin{tabular}{@{}rrrr@{}}", r"\toprule",
            r"Threshold & F tail $P(R>r)$ & Stationary noise & Demo day \\ \midrule"]
    for t, p_, a, b in zip(thresholds, tail, stat, demo):
        rows.append(f"{t:g} & {p_:.1e} & {a} & {b} \\\\")
    rows += [r"\bottomrule", r"\end{tabular}"]
    (FIG / "stalta-null-table.tex").write_text("\n".join(rows) + "\n")
    print((FIG / "stalta-null-table.tex").read_text())


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    wanted = sys.argv[1:] or list(FIGURES)
    for name in wanted:
        print(name)
        FIGURES[name]()
