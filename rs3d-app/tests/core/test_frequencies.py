import numpy as np
from obspy import Trace, UTCDateTime

from rs3d.core.frequencies import analyse, block_length, pick_peaks, welch_db
from rs3d.core.models import Selection
from rs3d.core.store import Store

T0 = UTCDateTime("2026-10-12T00:00:00")


def write_day(root, channel, data, start=T0, rate=100.0):
    tr = Trace(data.astype("int32"), dict(network="AM", station="R77A7", location="00", channel=channel,
                                          sampling_rate=rate, starttime=start))
    path = Store(root).day_path("AM", "R77A7", "00", channel, start.date)
    path.parent.mkdir(parents=True, exist_ok=True)
    tr.write(str(path), format="MSEED")


def synthetic(seconds, freqs, rate=100.0, noise=20.0, seed=0):
    t = np.arange(int(seconds * rate)) / rate
    rng = np.random.default_rng(seed)
    return sum(1000.0 * np.sin(2 * np.pi * f * t) for f in freqs) + rng.normal(0, noise, len(t))


def test_block_length_gives_about_twenty_blocks_within_limits():
    assert block_length(3600) == 300 and block_length(86400) == 1800 and block_length(10 * 3600) == 1800
    assert block_length(4 * 3600) == 600 and block_length(60) == 300


def test_pick_peaks_finds_two_lines_and_ignores_the_noise_floor():
    data = synthetic(600, (3.8, 14.9))
    f, db = welch_db(data, 100.0, 8192)
    found = [round(p[0], 1) for p in pick_peaks(f, db)]
    assert 3.8 in found and 14.9 in found
    assert pick_peaks(f, db, prominence=100.0) == []


def test_analyse_reports_stable_peaks_with_full_occurrence(tmp_path):
    write_day(tmp_path, "EHZ", synthetic(7200, (4.7, 12.5)))
    sel = Selection("AM", "R77A7", "00", T0, T0 + 7200, channels=("EHZ",))
    a = analyse(Store(tmp_path), sel)
    r = a.channels["EHZ"]
    assert r.n_blocks == 24 and a.block_s == 300
    peaks = {round(p.freq, 1): p for p in r.peaks}
    assert set(peaks) >= {4.7, 12.5}
    assert peaks[4.7].occurrence == 1.0 and peaks[4.7].prominence_db > 20 and peaks[4.7].contrast_db > 20
    assert abs(a.hours_used - 2.0) < 0.01


def test_blocks_with_gaps_or_clipping_are_skipped_and_counted(tmp_path):
    data = synthetic(3600, (5.0,))
    data[1200 * 100:1500 * 100] = 2 ** 23  # one 300 s block at the digitizer limit
    write_day(tmp_path, "EHZ", data)
    sel = Selection("AM", "R77A7", "00", T0, T0 + 3600, channels=("EHZ",))
    a = analyse(Store(tmp_path), sel)
    assert a.skipped["clipped"] == 1 and a.channels["EHZ"].n_blocks == 11


def test_no_data_gives_an_empty_analysis(tmp_path):
    sel = Selection("AM", "R77A7", "00", T0, T0 + 3600, channels=("EHZ",))
    a = analyse(Store(tmp_path), sel)
    assert a.channels == {} and a.hours_used == 0


def analysed(tmp_path):
    write_day(tmp_path, "EHZ", synthetic(7200, (4.7, 12.5)))
    write_day(tmp_path, "EHN", synthetic(7200, (4.7,), seed=1))
    sel = Selection("AM", "R77A7", "00", T0, T0 + 7200, channels=("EHZ", "EHN"))
    return analyse(Store(tmp_path), sel)


def test_stable_lines_merge_the_same_frequency_across_channels(tmp_path):
    from rs3d.core.frequencies import stable_lines
    lines = {round(f, 1): chans for f, chans, _ in stable_lines(analysed(tmp_path))}
    assert sorted(lines[4.7]) == ["EHN", "EHZ"] and lines[12.5] == ["EHZ"]


def test_exports(tmp_path):
    from rs3d.core.frequencies_export import write_figure, write_peaks_csv, write_spectra_csv
    a = analysed(tmp_path / "sds")
    rows = write_peaks_csv(a, tmp_path / "p.csv").read_text().splitlines()
    assert rows[0].startswith("channel,frequency_hz") and any(r.startswith("EHZ,4.7") for r in rows)
    assert write_spectra_csv(a, tmp_path / "s.csv").read_text().splitlines()[0].startswith("frequency_hz,EHZ_p10_db")
    for ext in ("png", "pdf"):
        assert write_figure(a, tmp_path / f"f.{ext}").stat().st_size > 5000
