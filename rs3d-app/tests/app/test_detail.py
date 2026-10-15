import numpy as np
from obspy import Stream, Trace, UTCDateTime

from rs3d.app.detail import detail_chart_options

T0 = UTCDateTime("2026-10-12T00:00:00")


def stream(seconds=120, channel="EHZ"):
    t = np.arange(0, seconds, 0.01)
    tr = Trace((1000 * np.sin(2 * np.pi * 5 * t)).astype("float64"), header={
        "network": "AM", "station": "R77A7", "location": "00", "channel": channel,
        "sampling_rate": 100.0, "starttime": T0})
    return Stream([tr])


def test_waveform_mode_is_a_line_chart_with_the_channel_name():
    opt = detail_chart_options("waveform", stream(), "EHZ", True)
    assert opt["series"][0]["name"] == "EHZ" and len(opt["series"][0]["data"]) > 100


def test_spectra_mode_is_log_log_and_peaks_near_5hz():
    opt = detail_chart_options("spectra", stream(), "EHZ", True)
    assert opt["xAxis"]["type"] == "log"
    data = opt["series"][0]["data"]
    assert abs(max(data, key=lambda p: p[1])[0] - 5.0) < 0.1


def test_spectrogram_mode_is_a_heatmap():
    opt = detail_chart_options("spectrogram", stream(), "EHZ", True)
    assert opt["series"][0]["type"] == "heatmap" and opt["series"][0]["data"]


def test_empty_window_or_other_channel_gives_none():
    assert detail_chart_options("waveform", Stream(), "EHZ", True) is None
    assert detail_chart_options("spectra", stream(channel="EHN"), "EHZ", True) is None


def test_panel_message_for_a_window_with_no_data():
    empty = Stream([Trace(np.zeros(0), header={"channel": "EHZ", "sampling_rate": 100.0, "starttime": T0})])
    assert detail_chart_options("waveform", empty, "EHZ", True) is None
