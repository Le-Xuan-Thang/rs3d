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
