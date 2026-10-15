from datetime import timedelta

import pytest
from obspy import UTCDateTime

from rs3d.app import timeutil

NOW = UTCDateTime("2026-10-12T17:30:45")
LISBON = timedelta(hours=1)

def test_text_roundtrip_utc_and_local():
    t = UTCDateTime("2026-10-12T17:30:45")
    assert timeutil.to_text(t, False) == "2026-10-12 17:30:45"
    assert timeutil.to_text(t, True, LISBON) == "2026-10-12 18:30:45"
    assert timeutil.from_text("2026-10-12 18:30:45", True, LISBON) == t
    with pytest.raises(ValueError):
        timeutil.from_text("12/10/2026", False)


@pytest.mark.parametrize("name, start, end", [
    ("last_10_min", "2026-10-12T17:20:45", "2026-10-12T17:30:45"),
    ("last_hour", "2026-10-12T16:30:45", "2026-10-12T17:30:45"),
    ("today", "2026-10-12T00:00:00", "2026-10-12T17:30:45"),
    ("yesterday", "2026-10-11T00:00:00", "2026-10-12T00:00:00"),
    ("last_7_days", "2026-10-05T17:30:45", "2026-10-12T17:30:45"),
])
def test_presets_utc(name, start, end):
    assert timeutil.preset_range(name, NOW, False) == (UTCDateTime(start), UTCDateTime(end))


def test_today_follows_local_zone():
    late = UTCDateTime("2026-10-12T23:30:00")  # already 13 Oct 00:30 in Lisbon
    a, b = timeutil.preset_range("today", late, True, LISBON)
    assert a == UTCDateTime("2026-10-12T23:00:00") and b == late


def test_view_ranges_and_shift():
    assert timeutil.view_range("day", NOW) == (UTCDateTime("2026-10-12"), UTCDateTime("2026-10-13"))
    assert timeutil.view_range("hour", NOW) == (UTCDateTime("2026-10-12T17:00"), UTCDateTime("2026-10-12T18:00"))
    assert timeutil.view_range("week", NOW)[0] == UTCDateTime("2026-10-06")
    center = timeutil.shift_view("day", UTCDateTime("2026-10-12"), -1)
    assert timeutil.view_range("day", center)[0] == UTCDateTime("2026-10-11")


def test_percent_to_time():
    view = (UTCDateTime("2026-10-12"), UTCDateTime("2026-10-13"))
    assert timeutil.percent_to_time(view, 50) == UTCDateTime("2026-10-12T12:00:00")
    assert timeutil.percent_to_time(view, 150) == view[1]
