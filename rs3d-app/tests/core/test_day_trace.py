from datetime import date

import numpy as np
from obspy import Stream, Trace, UTCDateTime

from rs3d.core.day_trace import SECONDS, DayTrace, day_start

DAY = date(2026, 10, 12)
T0 = day_start(DAY)


def trace(values, start, channel="EHZ", rate=1.0):
    return Trace(np.asarray(values, dtype=float),
                 header={"sampling_rate": rate, "starttime": UTCDateTime(start), "channel": channel})


def test_add_keeps_min_and_max_per_second():
    d = DayTrace(DAY)
    d.add(trace([1, 5, -3, 2], T0 + 10, rate=2.0))  # two samples per second: (1,5) in second 10, (-3,2) in 11
    lo, hi = d._lo["EHZ"], d._hi["EHZ"]
    assert (lo[10], hi[10], lo[11], hi[11]) == (1, 5, -3, 2)
    assert np.isnan(lo[9]) and np.isnan(lo[12])


def test_a_second_split_across_two_traces_is_extended():
    d = DayTrace(DAY)
    d.add(trace([1, 2], T0 + 0.0, rate=4.0))
    d.add(trace([9, -4], T0 + 0.5, rate=4.0))
    assert (d._lo["EHZ"][0], d._hi["EHZ"][0]) == (-4, 9)


def test_other_days_and_channels():
    d = DayTrace(DAY)
    d.add(trace([1], T0 - 5))  # yesterday: ignored
    assert not d.has_data("EHZ")
    d.add(trace([7], T0 + 3, channel="EHN"))
    assert d.has_data("EHN") and not d.has_data("EHZ")


def test_a_later_day_starts_a_new_day():
    d = DayTrace(DAY)
    d.add(trace([1], T0 + 5))
    d.add(trace([2], T0 + SECONDS + 1))
    assert d.day == date(2026, 10, 13) and d.start == T0 + SECONDS
    assert d._lo["EHZ"][1] == 2 and np.isnan(d._lo["EHZ"][5])


def test_an_earlier_day_is_ignored_after_a_rollover():
    d = DayTrace(DAY)
    d.add(trace([2], T0 + SECONDS + 1))
    d.add(trace([9], T0 + 5))  # a late trace from the earlier day
    assert d.day == date(2026, 10, 13)
    assert d._lo["EHZ"][1] == 2 and d._hi["EHZ"][1] == 2
    assert int(np.isfinite(d._lo["EHZ"]).sum()) == 1


def test_archive_never_overwrites_live_seconds():
    d = DayTrace(DAY)
    d.add(trace([5, 6], T0 + 100))
    d.replace_from(Stream([trace([1, 1, 1, 1], T0 + 99)]))  # seconds 99..102
    lo, hi = d._lo["EHZ"], d._hi["EHZ"]
    assert (lo[99], hi[99]) == (1, 1) and (lo[100], hi[100]) == (5, 5) and (lo[101], hi[101]) == (6, 6)
    assert (lo[102], hi[102]) == (1, 1)


def test_archive_replaced_by_first_live_packet_not_extended():
    d = DayTrace(DAY)
    d.replace_from(Stream([trace([100, -100], T0 + 50)]))
    d.add(trace([1], T0 + 50))
    assert (d._lo["EHZ"][50], d._hi["EHZ"][50]) == (1, 1)


def test_rows_shape_cut_and_median():
    d = DayTrace(DAY)
    d.add(trace([10, 10, 20, 20], T0 + 1790))      # seconds 1790..1793, the end of row 0
    d.add(trace([10, 12], T0 + 1800 + 4))          # seconds 4 and 5 of row 1
    rows = d.rows("EHZ")
    assert len(rows) == 48 and rows[0].start == UTCDateTime(T0) and rows[1].start == UTCDateTime(T0 + 1800)
    assert len(rows[5].values) == 0                # a row without data is empty
    r0 = rows[0]                                   # cut to the data: starts at second 1790 (bin 895 of step 2)
    assert r0.seconds[0] == 1790.5 and r0.seconds[-1] == 1793.5 and len(r0.values) == 4
    assert abs(np.median(r0.values)) < 1e-9
    assert len(rows[1].values) == 2 and rows[1].seconds[0] == 4.5


def test_rows_break_the_line_on_a_gap():
    d = DayTrace(DAY)
    d.add(trace([1, 1], T0 + 0))
    d.add(trace([1, 1], T0 + 10))
    r = d.rows("EHZ")[0]
    assert np.isnan(r.values).any()
    assert r.seconds[0] < 2 and r.seconds[-1] > 10


def test_rows_for_an_unknown_channel_are_empty():
    rows = DayTrace(DAY).rows("EHE")
    assert len(rows) == 48 and all(len(r.values) == 0 for r in rows)
