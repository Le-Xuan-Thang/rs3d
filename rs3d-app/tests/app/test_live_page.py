from rs3d.app.pages.live import WINDOWS, band_for, status_text
from rs3d.core.live import RingBuffer


def test_status_shows_error_reason_while_reconnecting():
    assert status_text("reconnecting", False, "[Errno 111] Connection refused") == \
        "reconnecting… ([Errno 111] Connection refused)"
    assert status_text("reconnecting", False, "") == "reconnecting…"


def test_status_live_and_stale():
    assert status_text("live", False, "") == "live"
    assert status_text("live", True, "") == "waiting for data…"


def test_band_for_accepts_only_a_valid_band():
    assert band_for(True, 1.0, 10.0) == (1.0, 10.0)
    assert band_for(False, 1.0, 10.0) is None
    assert band_for(True, 10.0, 1.0) is None
    assert band_for(True, None, 10.0) is None
    assert band_for(True, 0.0, 10.0) is None


def test_longest_window_fits_the_ring_buffer():
    assert max(WINDOWS) <= RingBuffer().seconds
    assert 600 in WINDOWS


def test_heli_spans_shade_the_channel_and_the_open_event():
    from rs3d.app.pages.live import heli_spans
    from rs3d.core.events import Event
    e = [Event(start=10.0, end=20.0, channel="EHZ", peak_ratio=5.0, peak_amplitude=100.0, source="live"),
         Event(start=30.0, end=40.0, channel="EHN", peak_ratio=5.0, peak_amplitude=100.0, source="live")]
    assert heli_spans(e, "EHZ", None, "EHZ", 99.0) == [(10.0, 20.0)]
    assert heli_spans(e, "EHZ", (50.0, 5.0), "EHZ", 99.0) == [(10.0, 20.0), (50.0, 99.0)]
    assert heli_spans(e, "EHN", (50.0, 5.0), "EHZ", 99.0) == [(30.0, 40.0)]  # the open event is on another channel
    assert heli_spans(e, "EHZ", (50.0, 5.0), "EHZ", 40.0) == [(10.0, 20.0), (50.0, 50.0)]  # stale stream: never ends before it starts


def test_heli_options_has_48_rows_and_event_shading():
    from datetime import date

    from rs3d.app.pages.live import heli_options
    from rs3d.core.day_trace import DayTrace
    d = DayTrace(date(2026, 10, 12))
    options = heli_options(d.rows("EHZ"), 1.0, [(d.start + 60, d.start + 120)])
    assert len(options["series"]) == 49  # 48 rows plus the click grid
    assert options["series"][-1]["markArea"]["data"]


def test_helicorder_link_points_at_the_same_day():
    from datetime import date

    from rs3d.app.pages.live import helicorder_link
    from rs3d.core.models import Device
    link = helicorder_link(Device(name="s", host="h", station="R77A7"), "EHZ", date(2026, 10, 12))
    assert link == "/helicorder?station=AM.R77A7.00&channel=EHZ&day=2026-10-12"
