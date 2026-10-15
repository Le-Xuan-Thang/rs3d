import csv

import numpy as np
import pytest
from obspy import UTCDateTime, read

from rs3d.core.export import load_processed, process, write_csv, write_mseed, write_plot
from rs3d.core.models import Selection
from tests.conftest import GAP_END, GAP_START, T_START


def sel(**kw):
    args = dict(network="AM", station="R77A7", location="00",
                start=T_START + 10, end=T_START + 20)
    args.update(kw)
    return Selection(**args)


def test_counts_without_filter_are_unchanged(store):
    s = sel()
    raw = store.load(s)
    out = load_processed(store, s)
    for a, b in zip(raw, out):
        np.testing.assert_array_equal(a.data, b.data)


def test_filter_changes_data_and_removes_mean(store):
    out = load_processed(store, sel(filter=(1.0, 10.0)))
    assert all(abs(tr.data.mean()) < 50 for tr in out)


def test_m_s_needs_inventory(store):
    with pytest.raises(ValueError, match="inventory"):
        load_processed(store, sel(units="m/s"))


def test_m_s_scales_to_small_velocities(store, inventory):
    out = load_processed(store, sel(units="m/s"), inventory)
    assert all(np.abs(tr.data).max() < 1e-3 for tr in out)


def test_process_does_not_modify_input(store):
    s = sel(filter=(1.0, 10.0))
    raw = store.load(s)
    before = raw[0].data.copy()
    process(raw, s)
    np.testing.assert_array_equal(raw[0].data, before)


def test_write_mseed_roundtrip(store, tmp_path):
    out = load_processed(store, sel())
    path = write_mseed(out, tmp_path / "x.mseed")
    back = read(str(path))
    assert sorted(tr.id for tr in back) == sorted(tr.id for tr in out)


def test_write_csv_columns_and_gap(store, tmp_path):
    s = sel(start=GAP_START - 0.05, end=GAP_END + 0.05)
    out = load_processed(store, s)
    path = write_csv(out, tmp_path / "x.csv", s.channels)
    rows = list(csv.reader(path.open()))
    assert rows[0] == ["time_utc", "EHZ", "EHN", "EHE"]
    assert rows[1][0] == "2026-10-12T00:01:59.950000Z"
    assert all(v != "" for v in rows[1][1:])
    gap_row = next(r for r in rows[1:] if r[0] == "2026-10-12T00:02:30.000000Z")
    assert gap_row[1:] == ["", "", ""]
    assert rows[-1][0] == "2026-10-12T00:03:00.050000Z"


def test_write_csv_rejects_mixed_rates(store, tmp_path):
    out = load_processed(store, sel())
    out[0].stats.sampling_rate = 50.0
    with pytest.raises(ValueError, match="sampling rate"):
        write_csv(out, tmp_path / "x.csv", ("EHZ", "EHN", "EHE"))


@pytest.mark.parametrize("suffix", [".png", ".pdf"])
def test_write_plot(store, tmp_path, suffix):
    out = load_processed(store, sel())
    path = write_plot(out, tmp_path / f"x{suffix}")
    assert path.stat().st_size > 1000


def test_write_plot_rejects_other_suffix(store, tmp_path):
    with pytest.raises(ValueError):
        write_plot(load_processed(store, sel()), tmp_path / "x.jpg")


def test_clipboard_title_states_station_channel_range_units_and_filter():
    from obspy import UTCDateTime
    from rs3d.core.export import clipboard_title
    t = clipboard_title("AM", "R77A7", "00", "EHZ", UTCDateTime("2026-10-12T00:00:00"),
                        UTCDateTime("2026-10-12T00:02:00"), "m/s", (1.0, 10.0))
    assert t == "AM.R77A7.00.EHZ  2026-10-12 00:00:00 → 00:02:00 UTC  m/s  band-pass 1–10 Hz"
    assert clipboard_title("AM", "R77A7", "00", "EHZ", UTCDateTime("2026-10-12T00:00:00"),
                           UTCDateTime("2026-10-12T00:02:00"), "counts", None).endswith("counts")


def test_clipboard_png_is_a_real_non_blank_image(tmp_path):
    import numpy as np
    from matplotlib import image
    from obspy import Stream, Trace, UTCDateTime
    from rs3d.core.export import write_clipboard_png
    t = np.arange(0, 60, 0.01)
    st = Stream([Trace(1000 * np.sin(2 * np.pi * 5 * t), header={
        "network": "AM", "station": "R77A7", "location": "00", "channel": "EHZ", "sampling_rate": 100.0,
        "starttime": UTCDateTime("2026-10-12T00:00:00")})])
    out = write_clipboard_png(st, tmp_path / "clip.png", "title")
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    img = image.imread(out)
    assert img.shape[0] > 500 and (img[..., :3] < 0.9).mean() > 0.02


def test_clipboard_png_refuses_an_empty_stream(tmp_path):
    import pytest
    from obspy import Stream
    from rs3d.core.export import write_clipboard_png
    with pytest.raises(ValueError, match="no data"):
        write_clipboard_png(Stream(), tmp_path / "x.png", "t")
