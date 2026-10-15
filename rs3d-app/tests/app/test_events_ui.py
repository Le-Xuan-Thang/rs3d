from rs3d.app.pages.settings import channel_note, event_settings_from_form
from rs3d.core.events import EventSettings

NUMBERS = {"sta": 6.0, "lta": 30.0, "on": 3.95, "reset": 0.9, "highpass": 0.8, "lowpass": 9.0}


def test_form_builds_settings():
    new, err = event_settings_from_form(EventSettings(), True, "EHN", {**NUMBERS, "on": 5.0})
    assert err == "" and new == EventSettings(channel="EHN", on=5.0)


def test_form_rejects_empty_number():
    new, err = event_settings_from_form(EventSettings(), True, "EHZ", {**NUMBERS, "sta": None})
    assert new is None and err


def test_form_rejects_invalid_values_with_a_message():
    new, err = event_settings_from_form(EventSettings(), True, "EHZ", {**NUMBERS, "lta": 3.0})
    assert new is None and "LTA" in err
    new, err = event_settings_from_form(EventSettings(), True, "EHZ", {**NUMBERS, "reset": 4.0})
    assert new is None and "Reset" in err
    new, err = event_settings_from_form(EventSettings(), True, "EHZ", {**NUMBERS, "lowpass": 80.0})
    assert new is None and "Band-pass" in err


def test_channel_note():
    assert channel_note(True, "EHZ", {"EHN", "EHE"}) != ""        # data flows but not the chosen channel
    assert channel_note(True, "EHZ", {"EHZ", "EHN"}) == ""
    assert channel_note(True, "EHZ", set()) == ""                  # nothing has arrived yet
    assert channel_note(False, "EHZ", {"EHN"}) == ""               # detection is off


from rs3d.app.pages.live import banner_state, clock, event_row_text, live_spans
from rs3d.core.events import Event

T = 1_700_000_000.0  # 2023-11-14 22:13:20 UTC


def test_clock_utc():
    assert clock(T, False) == "22:13:20"


def test_banner_active():
    kind, text = banner_state((T, 5.234), None, False)
    assert kind == "active" and "22:13:20" in text and "5.2" in text


def test_banner_ended_after_active():
    last = Event(T, T + 12.4, 6.0, 1234.0, "EHZ", "live")
    kind, text = banner_state(None, last, False)
    assert kind == "ended" and "12 s" in text and "6.0" in text and "1234" in text


def test_banner_active_wins_over_last():
    last = Event(T - 100, T - 90, 6.0, 10.0, "EHZ", "live")
    assert banner_state((T, 4.0), last, False)[0] == "active"


def test_banner_nothing():
    assert banner_state(None, None, False) == ("", "")


def test_event_row_text():
    text = event_row_text(Event(T, T + 12.4, 6.04, 1234.0, "EHZ", "scan"), False)
    assert "22:13:20" in text and "12 s" in text and "6.0" in text and "scan" in text


def test_live_spans_clip_to_window_and_include_open_event():
    recent = [Event(T - 500, T - 490, 5.0, 1.0, "EHZ", "live"), Event(T - 20, T - 10, 5.0, 1.0, "EHZ", "live")]
    spans = live_spans(recent, (T - 5, 4.0), (T - 60, T))
    assert spans == [(T - 20, T - 10), (T - 5, T)]


from datetime import date

from obspy import UTCDateTime

from rs3d.app.pages.data import scan_dates


def test_scan_dates_only_days_that_exist():
    have = {date(2026, 10, 11), date(2026, 10, 13)}
    got = scan_dates(UTCDateTime("2026-10-11T12:00:00"), UTCDateTime("2026-10-13T06:00:00"), have)
    assert got == [date(2026, 10, 11), date(2026, 10, 13)]


def test_scan_dates_end_exactly_at_midnight_excludes_next_day():
    have = {date(2026, 10, 12), date(2026, 10, 13)}
    got = scan_dates(UTCDateTime("2026-10-12T00:00:00"), UTCDateTime("2026-10-13T00:00:00"), have)
    assert got == [date(2026, 10, 12)]
