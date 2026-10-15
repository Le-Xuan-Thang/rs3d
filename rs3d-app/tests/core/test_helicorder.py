import time

import numpy as np
import pytest
from obspy import Stream, Trace, UTCDateTime

from rs3d.core.helicorder import (MAX_SPAN, MIN_SPAN, build_rows, click_to_time, load_day, load_window,
                                  process_safe, scale_for, shift_window, zoom_window)
from rs3d.core.models import Selection
from tests.conftest import DAY2

DAY = UTCDateTime("2026-10-12T00:00:00")


def trace(start_s: float, data: np.ndarray, rate: float = 100.0) -> Trace:
    return Trace(data=data.astype("float64"), header={
        "network": "AM", "station": "R77A7", "location": "00", "channel": "EHZ",
        "sampling_rate": rate, "starttime": DAY + start_s})


def test_48_rows_with_start_times():
    rows = build_rows(Stream([trace(0, np.zeros(100))]), DAY)
    assert len(rows) == 48
    assert rows[1].start - rows[0].start == 1800 and rows[47].start == DAY + 47 * 1800


def test_peak_survives_decimation():
    data = np.zeros(180000)  # 30 minutes
    data[90050] = 5000.0     # t = 900.5 s
    rows = build_rows(Stream([trace(0, data)]), DAY, points=300)
    r = rows[0]
    assert len(r.values) <= 320 and r.values.max() == 5000.0
    assert abs(r.seconds[np.argmax(r.values)] - 900.5) < 0.011


def test_gap_between_traces_is_one_nan_inside_the_gap():
    st = Stream([trace(0, np.ones(6000)), trace(120, np.ones(6000))])  # 0-60 s and 120-180 s
    r = build_rows(st, DAY)[0]
    nan = np.flatnonzero(np.isnan(r.values))
    assert len(nan) == 1 and 60 < r.seconds[nan[0]] < 120


def test_contiguous_traces_have_no_nan():
    st = Stream([trace(0, np.ones(6000)), trace(60, np.ones(6000))])
    assert not np.isnan(build_rows(st, DAY)[0].values).any()


def test_rows_without_data_are_empty():
    rows = build_rows(Stream([trace(0, np.ones(100))]), DAY)
    assert len(rows[0].values) > 0 and all(len(r.values) == 0 for r in rows[1:])


def test_fixture_store_day_has_gap_in_first_row_only(store):
    st = load_day(store, "AM", "R77A7", "00", "EHZ", DAY2)
    rows = build_rows(st, DAY)
    assert np.isnan(rows[0].values).sum() == 1          # 00:02-00:03 hole
    assert all(len(r.values) == 0 for r in rows[1:])    # data ends 00:10


def test_full_day_of_100hz_is_fast_and_bounded():
    big = trace(0, np.random.default_rng(0).normal(0, 100, 86400 * 100))
    best = float("inf")
    for _ in range(3):  # best of 3: a busy machine must not fail the test, a real slowdown still does
        t0 = time.perf_counter()
        rows = build_rows(Stream([big]), DAY)
        best = min(best, time.perf_counter() - t0)
    assert best < 2.0
    assert all(len(r.values) <= 3100 for r in rows)


def test_scale_ignores_one_huge_outlier():
    quiet = np.ones(6000)
    spike = np.ones(6000)
    spike[3000] = 1e6
    rows = build_rows(Stream([trace(0, quiet), trace(1800, spike)]), DAY)
    assert scale_for(rows) < 10
    assert scale_for(rows, factor=2.0) == scale_for(rows) / 2
    assert scale_for(build_rows(Stream(), DAY)) == 1.0


def test_click_to_time_maps_row_and_fraction():
    assert click_to_time(DAY, 30, 0, 0.0) == DAY
    assert click_to_time(DAY, 30, 2, 0.5) == DAY + 2 * 1800 + 900
    assert click_to_time(DAY, 30, 1, 1.7) == DAY + 2 * 1800  # clamped to the row end


def test_zoom_and_shift_windows_and_clamp():
    a, b = DAY + 100, DAY + 220  # 120 s
    za, zb = zoom_window(a, b, 2.0)
    assert zb - za == 240.0
    assert abs((za.timestamp + zb.timestamp) / 2 - (a.timestamp + b.timestamp) / 2) < 1e-6
    sa, sb = shift_window(a, b, 1)
    assert sa - a == 60 and sb - b == 60
    ta, tb = zoom_window(a, b, 0.001)
    assert tb - ta == MIN_SPAN
    ua, ub = zoom_window(a, b, 1000.0)
    assert ub - ua == MAX_SPAN


def test_window_with_band_pass_survives_tiny_fragments(store):
    sel = Selection("AM", "R77A7", "00", DAY + 0, DAY + 600, channels=("EHZ",), filter=(1.0, 10.0))
    for n in (1, 5, 30):  # fragments left between gaps can be a handful of samples
        out = process_safe(Stream([trace(0, np.ones(n))]), sel, None)
        assert len(out) == 1 and out[0].stats.npts == n
    ok = load_window(store, "AM", "R77A7", "00", "EHZ", DAY + 10, DAY + 100, band=(1.0, 10.0))
    assert len(ok) >= 1


def test_metres_per_second_without_response_raises_clearly(store):
    with pytest.raises(ValueError, match="response"):
        load_window(store, "AM", "R77A7", "00", "EHZ", DAY + 10, DAY + 100, units="m/s")
