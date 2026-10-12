from datetime import date

import pytest
from obspy import UTCDateTime

from rs3d.core.coverage import State, coverage, local_spans
from tests.conftest import DAY1, DAY2, GAP_END, GAP_START, T_END, T_START

NSLC = ("AM", "R77A7", "00", "EHZ")


def states(segments):
    return [(str(s.start), str(s.end), s.state) for s in segments]


def test_local_spans_merge_across_midnight_and_keep_gap(store):
    spans = local_spans(store, *NSLC, T_START - 60, T_END + 60)
    assert spans == [(T_START, GAP_START), (GAP_END, T_END)]


def test_coverage_with_everything_downloaded(store):
    segs = coverage(store, *NSLC, T_START, T_END, remote_days={DAY1, DAY2})
    # DAY2 is the newest remote day: time without local data there is REMOTE (file still growing)
    assert states(segs) == [
        (str(T_START), str(GAP_START), State.LOCAL),
        (str(GAP_START), str(GAP_END), State.REMOTE),
        (str(GAP_END), str(T_END), State.LOCAL),
    ]


def test_gap_in_a_finished_day_is_gap(store):
    day3 = date(2026, 10, 13)
    segs = coverage(store, *NSLC, T_START, T_END, remote_days={DAY1, DAY2, day3})
    assert [s.state for s in segs] == [State.LOCAL, State.GAP, State.LOCAL]


def test_days_only_on_shake_are_remote(store):
    start, end = UTCDateTime("2026-10-13T00:00:00"), UTCDateTime("2026-10-14T00:00:00")
    segs = coverage(store, *NSLC, start, end, remote_days={DAY1, DAY2, date(2026, 10, 13)})
    assert states(segs) == [(str(start), str(end), State.REMOTE)]


def test_nothing_anywhere_is_gap(store):
    start, end = UTCDateTime("2026-10-01T00:00:00"), UTCDateTime("2026-10-01T06:00:00")
    segs = coverage(store, *NSLC, start, end, remote_days=set())
    assert states(segs) == [(str(start), str(end), State.GAP)]


def test_rejects_empty_range(store):
    with pytest.raises(ValueError):
        coverage(store, *NSLC, T_END, T_START, remote_days=set())
